"""The code around the LLM: the agent-side safety check, the reason field and the verdict."""

from typing import Any

from langchain_core.tools import StructuredTool

from ainops.agent.report import EvidenceRecord, Finding, Report, verify
from ainops.agent.runner import MAX_TOOL_CALLS, Investigation, with_reason


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
