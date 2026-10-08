"""Similar past cases as hints: which cases match and why, and that a hint is never evidence.

The cases are the samples made from investigations recorded on the live lab (fixtures/cases).
"""

import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from test_cases import FAULT, MemoryCases

from ainops.agent import runner
from ainops.agent.report import Report
from ainops.agent.runner import AinopsMiddleware, Investigation
from ainops.api.runs import Run, RunRegistry
from ainops.cases import Case, draft_case
from ainops.config import REPO_ROOT, Settings
from ainops.similar import (
    MAX_HINTS,
    Hint,
    Hints,
    case_clues,
    clues_of,
    hints_prompt,
    similar_cases,
)

SITES = {
    "ISP-TRV-1": "TRV",
    "FWL-TRV": "TRV",
    "CORE-SW-TRV": "TRV",
    "IPLC-RTR-TRV": "TRV",
    "IPLC-RTR-MAA": "MAA",
    "CORE-SW-MAA": "MAA",
    "FWL-MAA": "MAA",
    "ISP-MAA-1": "MAA",
}
QUESTION = "Users at TRV (192.168.100.0/24) cannot reach 192.168.200.10 at MAA. Why?"


def sample(name: str, **changes: Any) -> Case:
    path = REPO_ROOT / "fixtures" / "cases" / "samples" / f"{name}.json"
    return Case.model_validate_json(path.read_text("utf-8")).model_copy(update=changes)


APPROVED = sample("fault1-corrected")  # Praveen corrected the root cause; the fix worked


def look(
    texts: list[str], checks: Sequence[tuple[str | None, str, str]] = (), **kw: Any
) -> list[Hint]:
    return similar_cases(kw.pop("cases", [APPROVED]), clues_of(texts, checks, SITES), SITES, **kw)


# ---------- what is known, as clues ----------


def test_the_question_gives_subnets_and_sites() -> None:
    clues = clues_of([QUESTION], [], SITES)
    assert clues.subnets == {"192.168.100.0/24", "192.168.200.0/24"}
    assert clues.sites == {"TRV", "MAA"}
    assert clues.devices == set()
    assert "users" not in clues.words and "cannot" not in clues.words


def test_checks_give_devices_and_the_kind_of_problem() -> None:
    clues = clues_of(
        ["Why?"],
        [
            ("IPLC-RTR-MAA", "get_interfaces", "3 interfaces; with an address but not up: Fa2/0"),
            ("IPLC-RTR-TRV", "get_ospf_neighbors", "MISSING (FULL at discovery): IPLC-RTR-MAA"),
            ("CORE-SW-TRV", "trace_route", "CORE-SW-TRV has no route to 192.168.200.10"),
        ],
        SITES,
    )
    assert clues.devices == {"IPLC-RTR-MAA", "IPLC-RTR-TRV", "CORE-SW-TRV"}
    assert clues.problems == {"interface down", "OSPF neighbour missing", "no route"}
    assert clues_of(
        ["x"], [("R", "get_interfaces", "Fa2/0 is administratively down")], SITES
    ).problems == {"interface shut"}


def test_a_case_is_known_by_its_question_devices_and_proof() -> None:
    clues = case_clues(APPROVED, SITES)
    assert clues.devices == {"IPLC-RTR-MAA"}
    assert clues.problems == {"interface down"}
    assert "192.168.200.0/24" in clues.subnets


# ---------- which cases match, and why ----------


def test_the_same_question_again_finds_the_approved_case_with_its_reasons() -> None:
    [hint] = look([QUESTION])
    assert hint.case_id == APPROVED.id
    assert hint.reasons == [
        "same subnets 192.168.100.0/24, 192.168.200.0/24",
        "same site MAA, TRV",
        "a very similar question",
    ]
    # The engineer's correction and the fix that worked are what the hint passes on.
    assert hint.root_cause == APPROVED.root_cause
    assert hint.corrected is True
    assert (hint.fix, hint.fix_worked, hint.reviewer) == ("no shutdown on Fa2/0", "yes", "Praveen")


def test_a_device_found_in_a_follow_up_check_finds_the_case() -> None:
    checks = [("IPLC-RTR-MAA", "get_interfaces", "3 interfaces; with an address but not up: Fa2/0")]
    [hint] = look(["Is the leased line healthy?"], checks)
    assert hint.reasons[:2] == ["same device IPLC-RTR-MAA", "same kind of problem: interface down"]


def test_only_approved_cases_are_hints() -> None:
    pending = sample("fault1-pending")
    rejected = sample("fault1-pending", status="rejected", id="case-rejected")
    assert look([QUESTION], cases=[pending, rejected]) == []


def test_words_or_a_site_alone_are_not_enough() -> None:
    assert look(["Why cannot users reach the MAA site? Something is wrong at MAA."]) == []
    assert look(["Is ISP-TRV-1 up at TRV?"]) == []
    # Almost the same words and both sites, but no shared device, address or problem: no hint.
    assert look(["Users at TRV cannot reach MAA. Why?"]) == []


def test_this_conversations_own_case_and_cases_already_offered_are_left_out() -> None:
    assert look([QUESTION], exclude={APPROVED.id}) == []


def test_at_most_three_best_first() -> None:
    cases = [APPROVED.model_copy(update={"id": f"case-{n}"}) for n in range(5)]
    cases.append(
        APPROVED.model_copy(
            update={
                "id": "case-best",
                "draft": APPROVED.draft.model_copy(
                    update={"devices": ["IPLC-RTR-MAA", "CORE-SW-MAA"]}
                ),
            }
        )
    )
    checks = [("CORE-SW-MAA", "get_interfaces", "ok")]
    hints = look([QUESTION], checks, cases=cases)
    assert len(hints) == MAX_HINTS
    assert hints[0].case_id == "case-best"


def test_the_prompt_says_hints_are_not_evidence() -> None:
    text = hints_prompt(look([QUESTION]))
    assert "They are NOT\nevidence: never cite them" in text
    assert f"- {APPROVED.id}: " in text and "Fix: no shutdown on Fa2/0 (it worked)." in text
    assert hints_prompt([]) == ""


# ---------- in a reply: shown, never evidence ----------

ODD_HINT = Hint(
    case_id="case-old",
    question="Can 172.16.5.5 reach the MAA LAN?",  # an address from the past, not from today
    root_cause="ACL on FWL-MAA",
    corrected=False,
    fix=None,
    fix_worked=None,
    reviewer="Praveen",
    reasons=["same site MAA"],
    score=5.0,
)


def _fake_agent(monkeypatch: pytest.MonkeyPatch, report: Report) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    class Client:
        async def get_tools(self, server_name: str) -> list[Any]:
            return []

    class Agent:
        async def ainvoke(self, state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {"structured_response": report, "messages": []}

    def create_agent(model: Any, tools: Any, **kwargs: Any) -> Agent:
        seen["prompt"] = kwargs["system_prompt"]
        seen["run"] = kwargs["middleware"][0].run
        return Agent()

    monkeypatch.setattr(runner, "mcp_client", lambda settings: Client())
    monkeypatch.setattr(runner, "build_model", lambda settings: None)
    monkeypatch.setattr(runner, "create_agent", create_agent)
    return seen


def _investigate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, report: Report, hints: Hints | None
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    seen = _fake_agent(monkeypatch, report)
    events: list[dict[str, Any]] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    final = asyncio.run(
        runner.investigate("Why?", collect, Settings(skills_dir=tmp_path), hints=hints)
    )
    return seen, events, final


def test_hints_are_shown_and_put_in_the_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hints = Hints(cases=[ODD_HINT], looked_at=4)
    seen, events, _ = _investigate(
        monkeypatch, tmp_path, Report(outcome="answered", summary="x"), hints
    )
    assert [e["type"] for e in events[:2]] == ["started", "hints"]
    assert events[1]["cases"][0]["case_id"] == "case-old"
    assert events[1]["looked_at"] == 4
    assert "- case-old: " in seen["prompt"]


def test_a_hints_addresses_cannot_be_used_in_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen, _, _ = _investigate(
        monkeypatch, tmp_path, Report(outcome="answered", summary="x"), Hints([ODD_HINT], 1)
    )
    run: Investigation = seen["run"]
    assert "172.16.5.5" not in run.known_ips
    run.tool_servers["ping"] = "network"  # the fake agent has no tools
    refusal = run.check("ping", {"device": "FWL-MAA", "destination": "172.16.5.5"})
    assert refusal and "did not come from the question or earlier evidence" in refusal


def test_citing_a_hint_is_removed_and_gives_no_confidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = Report(
        outcome="diagnosed",
        summary="x",
        root_cause="ACL on FWL-MAA",
        root_cause_evidence=["case-old"],
    )
    _, _, final = _investigate(monkeypatch, tmp_path, report, Hints([ODD_HINT], 1))
    assert final["report"]["root_cause_evidence"] == []
    assert final["confidence"] == "low"
    assert (
        "removed citations of evidence that does not exist: case-old" in final["confidence_reasons"]
    )


def test_without_a_lookup_there_is_no_hints_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen, events, _ = _investigate(
        monkeypatch, tmp_path, Report(outcome="answered", summary="x"), None
    )
    assert "hints" not in [e["type"] for e in events]
    assert "Similar past cases" not in seen["prompt"]


def test_tokens_of_every_step_are_counted() -> None:
    async def ignore(event: dict[str, Any]) -> None:
        return None

    run = Investigation(question="Why?", emit=ignore, tool_servers={})
    middleware = AinopsMiddleware(run)
    for used in (100, 250):
        message = AIMessage(
            content="",
            usage_metadata={"input_tokens": used, "output_tokens": 10, "total_tokens": used + 10},
        )
        asyncio.run(middleware.aafter_model({"messages": [message]}, None))
    assert (run.tokens_in, run.tokens_out) == (350, 20)


def test_the_report_carries_the_tokens(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, _, final = _investigate(monkeypatch, tmp_path, Report(outcome="answered", summary="x"), None)
    assert final["tokens"] == {"input": 0, "output": 0}


# ---------- the API: looked up before every reply ----------


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from ainops.api import app as module

    book = MemoryCases()
    book.save(APPROVED)

    class Graph:
        def devices(self) -> list[dict[str, str]]:
            return [{"name": n, "site": s} for n, s in SITES.items()]

    monkeypatch.setattr(module, "registry", RunRegistry(tmp_path))
    monkeypatch.setattr(module, "cases", lambda: book)
    monkeypatch.setattr(module, "store", lambda: Graph())
    return module


def _run(run_id: str, events: list[dict[str, Any]] | None = None) -> Run:
    return Run(run_id, "investigation", QUESTION, "2026-10-08T09:00:00+00:00", events or [], True)


def test_the_api_looks_up_hints_for_a_new_question(api: Any) -> None:
    hints = api._look_up_hints(_run("inv-new1"), QUESTION, None)
    assert [h.case_id for h in hints.cases] == [APPROVED.id]
    assert (hints.looked_at, hints.error) == (1, None)


def test_the_api_never_offers_a_conversation_its_own_case(api: Any) -> None:
    own = _run(APPROVED.run_id)
    assert api._look_up_hints(own, QUESTION, None).cases == []


def test_a_case_offered_earlier_in_the_conversation_is_not_offered_again(api: Any) -> None:
    shown = {"type": "hints", "cases": [{"case_id": APPROVED.id}], "looked_at": 1, "at_ms": 1}
    assert api._look_up_hints(_run("inv-new1", [shown]), QUESTION, None).cases == []


def test_without_the_graph_the_reply_goes_on_without_hints(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down() -> Any:
        raise ConnectionError("Neo4j is not running")

    monkeypatch.setattr(api, "cases", down)
    hints = api._look_up_hints(_run("inv-new1"), QUESTION, None)
    assert (hints.cases, hints.error) == ([], "could not look up past cases: ConnectionError")


def test_a_case_records_its_tokens_and_the_hints_it_was_offered() -> None:
    events = [dict(e) for e in FAULT["events"]]
    events.insert(
        1, {"type": "hints", "cases": [{"case_id": "case-old"}], "looked_at": 3, "at_ms": 5}
    )
    events[-1] = {**events[-1], "tokens": {"input": 12000, "output": 800}}
    case = draft_case("inv-x", FAULT["title"], FAULT["started_at"], events, list(SITES))
    assert case is not None
    assert (case.tokens, case.hints_offered) == (12800, ["case-old"])


def test_old_runs_without_tokens_count_zero() -> None:
    case = draft_case("inv-x", FAULT["title"], FAULT["started_at"], FAULT["events"], list(SITES))
    assert case is not None and case.tokens == 0
    assert json.loads(case.model_dump_json())["hints_offered"] == []


# ---------- the sample the frontend tests read ----------


def test_the_hints_samples_the_frontend_tests_read_match_the_code() -> None:
    """After changing what a hint holds: AINOPS_WRITE_SAMPLES=1 pytest -k samples"""
    found = look([QUESTION])
    produced = {
        "type": "hints",
        "cases": [h.as_event() for h in found],
        "looked_at": 1,
        "error": None,
        "at_ms": 3,
    }
    path = REPO_ROOT / "fixtures" / "cases" / "samples" / "hints-event.json"
    if os.environ.get("AINOPS_WRITE_SAMPLES"):
        with path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(produced, indent=2, ensure_ascii=False) + "\n")
    assert json.loads(path.read_text(encoding="utf-8")) == produced, "rewrite the samples"
