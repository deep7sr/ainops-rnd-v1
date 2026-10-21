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


# ---------- what the root cause blames must be shown by a cited check ----------

# The checks of the 2026-10-21 run on the simulator (fault-1: IPLC-RTR-MAA Fa2/0 shut), summaries
# as they were. The AI blamed CORE-SW-TRV Fa2/0, which none of them shows.
FAULT1_CHECKS = {
    "E6": EvidenceRecord(
        "E6", "get_routing_protocols", "CORE-SW-TRV",
        "protocols: ospf 1; OSPF networks: 10.10.2.0 area 0, 10.10.3.0 area 0, 192.168.100.0 "
        "area 0", "live", True,
    ),
    "E10": EvidenceRecord(
        "E10", "get_ospf_neighbors", "IPLC-RTR-TRV",
        "1 OSPF neighbour(s), all FULL; MISSING (FULL at discovery): IPLC-RTR-MAA on Fa2/0",
        "live", True,
    ),
    "E13": EvidenceRecord(
        "E13", "get_ospf_neighbors", "IPLC-RTR-MAA",
        "1 OSPF neighbour(s), all FULL; MISSING (FULL at discovery): IPLC-RTR-TRV on Fa2/0",
        "live", True,
    ),
    "E15": EvidenceRecord(
        "E15", "get_interfaces", "IPLC-RTR-TRV", "6 interfaces; all addressed interfaces up",
        "live", True,
    ),
    "E16": EvidenceRecord(
        "E16", "get_interfaces", "IPLC-RTR-MAA", "3 interfaces; with an address but not up: Fa2/0",
        "live", True,
    ),
}  # fmt: skip


def _blaming(affected: list[str], cited: list[str]) -> Report:
    return Report(
        outcome="diagnosed", summary="x", root_cause="y", root_cause_evidence=cited,
        affected=affected,
    )  # fmt: skip


def test_a_root_cause_no_cited_check_shows_is_low_however_many_checks_it_cites() -> None:
    verdict = verify(_blaming(["CORE-SW-TRV Fa2/0"], ["E6", "E10", "E13"]), FAULT1_CHECKS)
    assert verdict.confidence == "low"
    assert verdict.reasons[-1] == (
        "nothing cited for the root cause shows CORE-SW-TRV Fa2/0: check it directly"
    )


def test_a_check_of_the_blamed_device_naming_the_interface_shows_it() -> None:
    assert verify(_blaming(["IPLC-RTR-MAA Fa2/0"], ["E16"]), FAULT1_CHECKS).confidence == "medium"
    verdict = verify(_blaming(["IPLC-RTR-MAA Fa2/0"], ["E16", "E10"]), FAULT1_CHECKS)
    assert verdict.confidence == "high"
    assert not any("nothing cited" in r for r in verdict.reasons)


def test_the_interface_named_by_a_check_of_another_device_does_not_count() -> None:
    """E10 is IPLC-RTR-TRV's view: 'Fa2/0' there is its own Fa2/0, not IPLC-RTR-MAA's."""
    verdict = verify(_blaming(["IPLC-RTR-MAA Fa2/0"], ["E10", "E15"]), FAULT1_CHECKS)
    assert verdict.confidence == "low"


def test_a_check_of_the_device_that_does_not_name_the_interface_does_not_count() -> None:
    verdict = verify(_blaming(["IPLC-RTR-TRV Fa0/0"], ["E15", "E10"]), FAULT1_CHECKS)
    assert verdict.confidence == "low"


def test_both_spellings_of_an_interface_are_the_same_interface() -> None:
    long = verify(_blaming(["IPLC-RTR-MAA FastEthernet2/0"], ["E16"]), FAULT1_CHECKS)
    assert long.confidence == "medium"
    checks = {"E1": EvidenceRecord("E1", "get_interface_detail", "R1", "FastEthernet2/0 is "
                                   "administratively down", "live", True)}  # fmt: skip
    assert verify(_blaming(["R1 Fa2/0"], ["E1"]), checks).confidence == "medium"


def test_a_junos_interface_is_matched_too() -> None:
    checks = {
        "E3": EvidenceRecord(
            "E3", "get_firewall_zones", "FWL-TRV",
            "trust: -; untrust: -; NOT IN ANY ZONE: ge-0/0/0 (10.10.1.2/24), ge-0/0/1 "
            "(10.10.2.1/24)", "live", True,
        )
    }  # fmt: skip
    assert verify(_blaming(["FWL-TRV ge-0/0/1"], ["E3"]), checks).confidence == "medium"
    assert verify(_blaming(["FWL-TRV ge-0/0/2"], ["E3"]), checks).confidence == "low"


def test_an_interface_range_blames_its_first_interface() -> None:
    assert verify(_blaming(["IPLC-RTR-MAA Fa2/0-Fa2/1"], ["E16"]), FAULT1_CHECKS).confidence == (
        "medium"
    )
    assert verify(_blaming(["IPLC-RTR-MAA Fa1/0‑Fa2/0"], ["E16"]), FAULT1_CHECKS).confidence == (
        "low"
    )


def test_a_blamed_device_without_an_interface_needs_a_check_of_that_device() -> None:
    assert verify(_blaming(["IPLC-RTR-MAA (down)"], ["E16"]), FAULT1_CHECKS).confidence == "medium"
    assert verify(_blaming(["FWL-MAA"], ["E16"]), FAULT1_CHECKS).confidence == "low"


def test_one_shown_item_is_enough() -> None:
    report = _blaming(["CORE-SW-TRV Fa2/0", "IPLC-RTR-MAA Fa2/0"], ["E16", "E6"])
    assert verify(report, FAULT1_CHECKS).confidence == "high"


def test_a_failed_check_shows_nothing() -> None:
    failed = {"E16": EvidenceRecord("E16", "get_interfaces", "IPLC-RTR-MAA", "Fa2/0 timed out",
                                    "live", False)}  # fmt: skip
    verdict = verify(_blaming(["IPLC-RTR-MAA Fa2/0"], ["E16"]), failed)
    assert verdict.confidence == "low"
    assert verdict.reasons == ["the root cause cites no valid evidence"]  # said once, not twice
    # Next to a working check of another device, the failed one still shows nothing.
    checks = {**FAULT1_CHECKS, **failed}
    verdict = verify(_blaming(["IPLC-RTR-MAA Fa2/0"], ["E16", "E10"]), checks)
    assert verdict.confidence == "low"
    assert verdict.reasons[-1].startswith("nothing cited for the root cause shows")


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
