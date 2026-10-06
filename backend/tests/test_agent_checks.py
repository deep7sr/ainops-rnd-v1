"""The code around the LLM: the agent-side safety check, the reason field and the verdict."""

import asyncio
import json
from typing import Any

from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import ToolCall, ToolMessage
from langchain_core.tools import StructuredTool

from ainops.agent.report import EvidenceRecord, Finding, Report, verify
from ainops.agent.runner import MAX_TOOL_CALLS, AinopsMiddleware, Investigation, with_reason


async def _ignore(event: dict[str, Any]) -> None:
    return None


def _run(question: str = "Why can't 192.168.100.10 reach 192.168.200.10?") -> Investigation:
    return Investigation(
        question=question,
        emit=_ignore,
        tool_servers={"ping": "network", "get_path": "topology", "find_device": "topology"},
    )


def test_addresses_from_the_question_are_allowed() -> None:
    run = _run()
    assert (
        run.check("get_path", {"source": "192.168.100.10", "destination": "192.168.200.10"}) is None
    )


def test_invented_address_is_refused() -> None:
    run = _run()
    refusal = run.check("ping", {"device": "IPLC-RTR-MAA", "destination": "10.10.4.1"})
    assert refusal and "did not come from the question or earlier evidence" in refusal


def test_address_seen_in_evidence_becomes_allowed() -> None:
    run = _run()
    run.known_ips.add("10.10.4.1")  # what the middleware does with every tool result
    assert run.check("ping", {"device": "IPLC-RTR-MAA", "destination": "10.10.4.1"}) is None


def test_unknown_tool_is_refused() -> None:
    assert "not an AINOPS tool" in (_run().check("configure_device", {}) or "")


def test_budget_is_enforced() -> None:
    run = _run()
    run.tool_calls = MAX_TOOL_CALLS
    assert "budget" in (run.check("find_device", {"query": "IPLC-RTR-MAA"}) or "")


def test_reason_is_added_first_and_required() -> None:
    async def noop(device: str) -> str:
        return device

    tool = StructuredTool(
        name="get_interfaces",
        description="x",
        args_schema={
            "type": "object",
            "properties": {"device": {"type": "string"}},
            "required": ["device"],
        },
        coroutine=noop,
    )
    schema = with_reason(tool).args_schema
    assert isinstance(schema, dict)
    assert list(schema["properties"]) == ["reason", "device"]
    assert schema["required"] == ["reason", "device"]
    assert "reason" not in tool.args_schema["properties"]  # type: ignore[index]  # original untouched


def _evidence(*records: tuple[str, str, bool]) -> dict[str, EvidenceRecord]:
    return {
        eid: EvidenceRecord(eid, "get_interfaces", device, "", "live", ok)
        for eid, device, ok in records
    }


def test_invented_citations_are_removed_and_lower_confidence() -> None:
    report = Report(
        outcome="diagnosed",
        summary="Fa2/0 is shut.",
        root_cause="Fa2/0 on IPLC-RTR-MAA is administratively down",
        root_cause_evidence=["E1", "E9"],
        findings=[Finding(text="Fa2/0 admin-down", evidence=["E1", "E7"])],
    )
    verdict = verify(report, _evidence(("E1", "IPLC-RTR-MAA", True)))
    assert verdict.invalid_citations == ["E7", "E9"]
    assert report.root_cause_evidence == ["E1"]
    assert report.findings[0].evidence == ["E1"]
    assert verdict.confidence == "medium"


def test_high_confidence_needs_two_good_pieces_of_evidence() -> None:
    report = Report(
        outcome="diagnosed", summary="x", root_cause="y", root_cause_evidence=["E1", "E2"]
    )
    evidence = _evidence(("E1", "IPLC-RTR-MAA", True), ("E2", "IPLC-RTR-TRV", True))
    assert verify(report, evidence).confidence == "high"


def test_failed_evidence_does_not_count() -> None:
    report = Report(
        outcome="diagnosed", summary="x", root_cause="y", root_cause_evidence=["E1", "E2"]
    )
    evidence = _evidence(("E1", "IPLC-RTR-MAA", False), ("E2", "IPLC-RTR-TRV", False))
    assert verify(report, evidence).confidence == "low"


def test_inconclusive_is_low() -> None:
    assert verify(Report(outcome="inconclusive", summary="x"), {}).confidence == "low"


def test_tool_result_event_carries_the_code_verdict_for_the_live_map() -> None:
    events: list[dict[str, Any]] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    run = Investigation(question="Why?", emit=collect, tool_servers={"get_interfaces": "network"})
    health = {"status": "problem", "issues": [{"text": "Fa2/0 is down", "interface": "Fa2/0"}]}
    payload = {
        "device": "IPLC-RTR-MAA",
        "summary": "3 interfaces; with an address but not up: Fa2/0",
        "data": [],
        "health": health,
        "evidence": {"command": "show ip interface", "source": "replay"},
    }
    call = ToolCall(
        name="get_interfaces", args={"device": "IPLC-RTR-MAA", "reason": "Check MAA"}, id="c1"
    )
    request = ToolCallRequest(tool_call=call, tool=None, state={}, runtime=None)  # type: ignore[arg-type]

    async def handler(req: ToolCallRequest) -> ToolMessage:
        assert "reason" not in req.tool_call["args"]  # shown to the engineer, never sent to MCP
        return ToolMessage(content=json.dumps(payload), tool_call_id="c1", name="get_interfaces")

    message = asyncio.run(AinopsMiddleware(run).awrap_tool_call(request, handler))
    call_event, result_event = events
    assert call_event["why"] == "Check MAA"
    assert result_event["health"] == health
    assert result_event["device"] == "IPLC-RTR-MAA"
    assert isinstance(message, ToolMessage)
    assert '"health"' in str(message.content)  # the agent reads the verdict too


def test_a_device_record_is_not_passed_on_as_a_device_name() -> None:
    """find_device by name returns the whole record under "device"; the UI expects a name."""
    events: list[dict[str, Any]] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    run = Investigation(question="Why?", emit=collect, tool_servers={"find_device": "topology"})
    payload = {"summary": "IPLC-RTR-TRV", "device": {"name": "IPLC-RTR-TRV", "site": "TRV"}}
    call = ToolCall(
        name="find_device", args={"query": "IPLC-RTR-TRV", "reason": "Find it"}, id="c2"
    )
    request = ToolCallRequest(tool_call=call, tool=None, state={}, runtime=None)  # type: ignore[arg-type]

    async def handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content=json.dumps(payload), tool_call_id="c2", name="find_device")

    asyncio.run(AinopsMiddleware(run).awrap_tool_call(request, handler))
    assert events[1]["device"] is None
    assert events[1]["data"] == payload  # the record itself still reaches the UI as data
