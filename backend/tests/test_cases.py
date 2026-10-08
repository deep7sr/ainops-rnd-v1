"""Cases: the draft code builds from a conversation, the engineer's review, and the API.

The conversations are real investigations recorded on the live lab (fixtures/runs, 5 Oct 2026),
with follow-ups added the way the API adds them.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ainops.api.runs import Run, RunRegistry
from ainops.case_store import CaseBook
from ainops.cases import (
    Case,
    CaseError,
    ReviewRequest,
    draft_case,
    follow,
    review_case,
    short_interface,
)
from ainops.config import REPO_ROOT

DEVICES = [
    "ISP-TRV-1",
    "FWL-TRV",
    "CORE-SW-TRV",
    "IPLC-RTR-TRV",
    "IPLC-RTR-MAA",
    "CORE-SW-MAA",
    "FWL-MAA",
    "ISP-MAA-1",
]
STARTED = "2026-10-05T15:29:13+00:00"


def recorded(name: str) -> dict[str, Any]:
    path = REPO_ROOT / "fixtures" / "runs" / f"{name}.json"
    return json.loads(path.read_text("utf-8"))  # type: ignore[no-any-return]


FAULT = recorded("fault1-leased-line-shut-run1")
HEALTHY = recorded("healthy-baseline")
REFUSED = recorded("refused-change-request")


def _case(events: list[dict[str, Any]], by_hand: bool = False) -> Case | None:
    return draft_case("inv-abc123", FAULT["title"], STARTED, events, DEVICES, by_hand=by_hand)


def _message(text: str, turn: int = 2) -> dict[str, Any]:
    return {"type": "message", "turn": turn, "text": text, "at": "2026-10-05T15:40:00+00:00"}


def _report(outcome: str, root_cause: str | None, cited: list[str], at_ms: int = 5000) -> Any:
    return {
        "type": "report",
        "report": {
            "outcome": outcome,
            "summary": f"{outcome} summary",
            "root_cause": root_cause,
            "root_cause_evidence": cited,
            "affected": [],
            "findings": [],
            "next_steps": [],
            "limitations": [],
        },
        "confidence": "high",
        "confidence_reasons": [],
        "tool_calls": 1,
        "skills_used": ["site-to-site-unreachable"],
        "at_ms": at_ms,
    }


def _ospf_result(eid: str = "E7") -> dict[str, Any]:
    return {
        "type": "tool_result",
        "id": eid,
        "tool": "get_ospf_neighbors",
        "server": "network",
        "device": "IPLC-RTR-TRV",
        "ok": True,
        "summary": "MISSING (FULL at discovery): IPLC-RTR-MAA on Fa2/0",
        "data": [],
        "evidence": {"source": "live"},
        "health": {"status": "problem", "issues": [{"text": "x", "interface": "FastEthernet2/0"}]},
        "duration_ms": 10,
        "at_ms": 900,
    }


# ---------- the draft: built by code from the conversation ----------


def test_a_diagnosis_drafts_a_pending_case_with_its_proof() -> None:
    case = _case(FAULT["events"])
    assert case is not None
    assert case.id == "case-abc123"
    assert (case.status, case.made_by, case.review) == ("pending", "ainops", None)
    assert case.question == FAULT["title"]
    draft = case.draft
    assert draft.outcome == "diagnosed"
    assert draft.root_cause and "Fa2/0" in draft.root_cause
    assert [(e.id, e.tool, e.device) for e in draft.evidence] == [
        ("E6", "get_interfaces", "IPLC-RTR-MAA")
    ]
    assert draft.evidence[0].summary == "3 interfaces; with an address but not up: Fa2/0"
    assert draft.devices == ["IPLC-RTR-MAA"]
    assert draft.interfaces == ["IPLC-RTR-MAA Fa2/0"]  # from `affected` and from E6's problem
    assert draft.path == ["CORE-SW-TRV", "IPLC-RTR-TRV", "IPLC-RTR-MAA", "CORE-SW-MAA"]
    assert draft.path_note == "cabled path (not traced)"
    assert len(draft.suggested_fix) == 1 and "no shutdown" in draft.suggested_fix[0]
    assert (case.checks, case.duration_ms) == (6, 82297)
    assert case.root_cause == draft.root_cause


def test_a_traced_route_is_the_path_and_says_where_traffic_stops() -> None:
    trace = {
        "type": "tool_result",
        "id": "E7",
        "tool": "trace_route",
        "device": None,
        "ok": True,
        "summary": "no route",
        "data": {"path": ["CORE-SW-TRV"], "status": "no_route", "stopped_at": "CORE-SW-TRV"},
    }
    events = [*FAULT["events"], _message("Trace it"), trace, _report("diagnosed", "x", ["E6"])]
    case = _case(events)
    assert case is not None
    assert case.draft.path == ["CORE-SW-TRV"]
    assert case.draft.path_note == "traced: no route at CORE-SW-TRV"


def test_a_healthy_or_refused_run_drafts_nothing_by_itself() -> None:
    assert _case(HEALTHY["events"]) is None
    assert _case(REFUSED["events"]) is None


def test_the_engineer_can_ask_for_a_case_of_a_healthy_run_but_not_of_a_refusal() -> None:
    case = _case(HEALTHY["events"], by_hand=True)
    assert case is not None
    assert (case.made_by, case.draft.outcome, case.draft.root_cause) == (
        "engineer",
        "no_fault_found",
        None,
    )
    assert _case(REFUSED["events"], by_hand=True) is None


def test_the_draft_follows_the_latest_diagnosis_and_keeps_the_conversation() -> None:
    events = [
        *FAULT["events"],
        _message("Fa2/0 is up, I checked. Look at OSPF."),
        _ospf_result(),
        _report("diagnosed", "OSPF neighbour lost on Fa2/0", ["E7"], at_ms=3000),
        _message("Why?", turn=3),
        _report("answered", None, [], at_ms=1000),  # an explanation: not a new diagnosis
    ]
    case = _case(events)
    assert case is not None
    assert case.draft.root_cause == "OSPF neighbour lost on Fa2/0"
    assert [e.id for e in case.draft.evidence] == ["E7"]
    assert case.draft.interfaces == ["IPLC-RTR-TRV Fa2/0"]  # long name made short
    assert case.draft.skills == ["site-to-site-unreachable"]
    assert [(x.message[:6], x.outcome) for x in case.conversation] == [
        ("Users ", "diagnosed"),
        ("Fa2/0 ", "diagnosed"),
        ("Why?", "answered"),
    ]
    assert case.conversation[0].root_cause == FAULT["events"][-1]["report"]["root_cause"]
    assert (case.checks, case.duration_ms) == (7, 82297 + 3000 + 1000)


def test_made_up_or_unknown_names_do_not_become_devices() -> None:
    events = [*FAULT["events"][:-1], _report("diagnosed", "x", ["E6", "E99"])]
    events[-1]["report"]["affected"] = ["ROUTER-X Fa0/0", "IPLC-RTR-MAA FastEthernet2/0"]
    case = _case(events)
    assert case is not None
    assert [e.id for e in case.draft.evidence] == ["E6"]  # E99 never ran
    assert case.draft.devices == ["IPLC-RTR-MAA"]
    assert case.draft.interfaces == ["IPLC-RTR-MAA Fa2/0"]


def test_short_interface_names() -> None:
    assert short_interface("FastEthernet2/0") == "Fa2/0"
    assert short_interface("GigabitEthernet0/0/1") == "Gi0/0/1"
    assert short_interface("ge-0/0/0") == "ge-0/0/0"


def test_a_pending_case_follows_a_newer_draft_a_reviewed_one_is_locked() -> None:
    first = _case(FAULT["events"])
    assert first is not None
    newer = first.model_copy(
        update={"created_at": "later", "draft": first.draft.model_copy(update={"root_cause": "B"})}
    )
    followed = follow(first, newer)
    assert followed.draft.root_cause == "B"
    assert followed.created_at == first.created_at
    approved = review_case(first, ReviewRequest(action="approve", reviewer="Deependra"))
    assert follow(approved, newer) is approved


# ---------- the engineer's review ----------


def _pending() -> Case:
    case = _case(FAULT["events"])
    assert case is not None
    return case


def test_approve_keeps_the_ai_root_cause_and_says_who() -> None:
    case = review_case(
        _pending(),
        ReviewRequest(
            action="approve", reviewer="  Deependra  ", fix_applied="no shut", fix_worked="yes"
        ),
    )
    assert case.status == "approved"
    assert case.review is not None
    assert (case.review.reviewer, case.review.fix_applied, case.review.fix_worked) == (
        "Deependra",
        "no shut",
        "yes",
    )
    assert case.root_cause == case.draft.root_cause


def test_correct_records_the_engineers_cause_and_keeps_the_ai_draft() -> None:
    before = _pending()
    case = review_case(
        before,
        ReviewRequest(
            action="correct",
            reviewer="Praveen",
            root_cause="Fa2/0 was shut during a change window",
            fix_applied="no shutdown on Fa2/0",
            fix_worked="unknown",
        ),
    )
    assert case.status == "approved"
    assert case.root_cause == "Fa2/0 was shut during a change window"
    assert case.draft == before.draft  # what the AI said is never changed
    assert case.model_dump()["root_cause"] == case.root_cause  # sent to the page


@pytest.mark.parametrize(
    ("request_", "problem"),
    [
        (ReviewRequest(action="approve", reviewer="   "), "type your name"),
        (ReviewRequest(action="reject", reviewer="D"), "say why"),
        (ReviewRequest(action="reject", reviewer="D", reason="  "), "say why"),
        (ReviewRequest(action="correct", reviewer="D"), "write the real root cause"),
    ],
)
def test_each_review_rule_is_explained(request_: ReviewRequest, problem: str) -> None:
    with pytest.raises(CaseError, match=problem):
        review_case(_pending(), request_)


def test_reject_keeps_the_reason_and_drops_any_fix() -> None:
    case = review_case(
        _pending(),
        ReviewRequest(action="reject", reviewer="D", reason="wrong device", fix_applied="x"),
    )
    assert case.status == "rejected"
    assert case.review is not None
    assert (case.review.reason, case.review.fix_applied) == ("wrong device", None)


def test_a_reviewed_case_cannot_be_reviewed_again() -> None:
    approved = review_case(_pending(), ReviewRequest(action="approve", reviewer="Deependra"))
    with pytest.raises(CaseError, match="already approved by Deependra"):
        review_case(approved, ReviewRequest(action="reject", reviewer="X", reason="no"))


def test_a_case_without_a_root_cause_needs_one_written_before_approval() -> None:
    case = _case(HEALTHY["events"], by_hand=True)
    assert case is not None
    with pytest.raises(CaseError, match="use Correct"):
        review_case(case, ReviewRequest(action="approve", reviewer="D"))
    fixed = review_case(case, ReviewRequest(action="correct", reviewer="D", root_cause="ARP"))
    assert fixed.root_cause == "ARP"


def test_typed_text_has_limits() -> None:
    with pytest.raises(ValidationError):
        ReviewRequest(action="correct", reviewer="D", root_cause="x" * 501)
    with pytest.raises(ValidationError):
        ReviewRequest(action="approve", reviewer="D" * 81)
    with pytest.raises(ValidationError):
        ReviewRequest.model_validate({"action": "delete", "reviewer": "D"})


# ---------- the API ----------


class MemoryCases:
    """The case book without Neo4j: same rules (CaseBook), kept in a dict."""

    def __init__(self) -> None:
        self.cases: dict[str, Case] = {}

    def get(self, case_id: str) -> Case | None:
        return self.cases.get(case_id)

    def for_run(self, run_id: str) -> Case | None:
        return next((c for c in self.cases.values() if c.run_id == run_id), None)

    def all(self, status: str | None = None) -> list[Case]:
        found = [c for c in self.cases.values() if status is None or c.status == status]
        return sorted(found, key=lambda c: c.updated_at, reverse=True)

    def counts(self) -> dict[str, int]:
        counts = {"pending": 0, "approved": 0, "rejected": 0}
        for case in self.cases.values():
            counts[case.status] += 1
        return counts

    def statuses(self, run_ids: list[str]) -> dict[str, str]:
        return {c.run_id: c.status for c in self.cases.values() if c.run_id in run_ids}

    def save(self, case: Case, only_if: str | None = None) -> bool:
        stored = self.cases.get(case.id)
        if only_if is not None and stored is not None and stored.status != only_if:
            return False
        self.cases[case.id] = case
        return True


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from ainops.api import app as module

    book: CaseBook = MemoryCases()
    monkeypatch.setattr(module, "registry", RunRegistry(tmp_path))
    monkeypatch.setattr(module, "cases", lambda: book)
    monkeypatch.setattr(module, "_device_names", lambda: DEVICES)
    monkeypatch.setattr(module, "book", book, raising=False)  # for the tests to look into
    return module


def _saved(api: Any, run: dict[str, Any], run_id: str = "inv-abc123") -> Run:
    events = [dict(e) for e in run["events"]]
    saved = Run(run_id, "investigation", run["title"], STARTED, events, True)
    api.registry.runs[run_id] = saved
    return saved


def _events(run: Run) -> list[dict[str, Any]]:
    return [e for e in run.events if e.get("type") == "case"]


def test_after_a_diagnosis_the_case_is_drafted_and_the_page_is_told(api: Any) -> None:
    run = _saved(api, FAULT)
    asyncio.run(api._record_case(run))
    assert _events(run) == [{"type": "case", "id": "case-abc123", "status": "pending"}]
    assert api.book.get("case-abc123").draft.devices == ["IPLC-RTR-MAA"]


def test_no_case_after_a_reply_that_found_no_root_cause(api: Any) -> None:
    run = _saved(api, FAULT)
    run.events += [_message("Why?"), _report("answered", None, [])]
    asyncio.run(api._record_case(run))
    assert _events(run) == []
    assert api.book.cases == {}


def test_a_later_diagnosis_updates_a_pending_case_but_not_a_reviewed_one(api: Any) -> None:
    run = _saved(api, FAULT)
    asyncio.run(api._record_case(run))
    run.events += [_message("Look at OSPF"), _ospf_result(), _report("diagnosed", "B", ["E7"])]
    asyncio.run(api._record_case(run))
    assert api.book.get("case-abc123").draft.root_cause == "B"

    client = TestClient(api.app)
    answer = client.post(
        "/api/cases/case-abc123/review", json={"action": "approve", "reviewer": "Deependra"}
    )
    assert answer.json()["status"] == "approved"
    run.events += [_message("And now?", 3), _report("diagnosed", "C", ["E7"])]
    asyncio.run(api._record_case(run))
    assert api.book.get("case-abc123").root_cause == "B"  # locked after the review
    assert _events(run)[-1] == {"type": "case", "id": "case-abc123", "status": "approved"}


def test_a_case_that_cannot_be_saved_does_not_fail_the_investigation(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down() -> CaseBook:
        raise ConnectionError("Neo4j is not running")

    monkeypatch.setattr(api, "cases", down)
    run = _saved(api, FAULT)
    asyncio.run(api._record_case(run))
    assert _events(run) == [{"type": "case", "error": "case not saved: ConnectionError"}]


def test_making_a_case_by_hand(api: Any) -> None:
    _saved(api, HEALTHY, "inv-healthy1")
    _saved(api, REFUSED, "inv-refused1")
    client = TestClient(api.app)
    assert client.get("/api/runs/inv-healthy1/case").json() == {"case": None, "can_make": True}
    assert client.get("/api/runs/inv-refused1/case").json()["can_make"] is False

    made = client.post("/api/runs/inv-healthy1/case")
    assert made.status_code == 200
    assert (made.json()["made_by"], made.json()["status"]) == ("engineer", "pending")
    again = client.post("/api/runs/inv-healthy1/case")
    assert (again.status_code, again.json()["detail"]) == (
        409,
        "this conversation already has a case",
    )
    assert client.post("/api/runs/inv-refused1/case").status_code == 409
    assert client.post("/api/runs/inv-nope/case").status_code == 404
    assert client.get("/api/runs/inv-healthy1/case").json()["can_make"] is False


def test_no_case_by_hand_while_ainops_is_still_replying(api: Any) -> None:
    run = _saved(api, HEALTHY, "inv-healthy1")
    run.done = False
    client = TestClient(api.app)
    assert client.post("/api/runs/inv-healthy1/case").status_code == 409
    assert client.get("/api/runs/inv-healthy1/case").json()["can_make"] is False


def test_review_through_the_api(api: Any) -> None:
    asyncio.run(api._record_case(_saved(api, FAULT)))
    client = TestClient(api.app)
    url = "/api/cases/case-abc123/review"
    refused = client.post(url, json={"action": "reject", "reviewer": "D"})
    assert (refused.status_code, refused.json()["detail"]) == (409, "say why the case is rejected")
    assert client.post(url, json={"action": "delete", "reviewer": "D"}).status_code == 422
    assert (
        client.post(
            "/api/cases/case-nope/review", json={"action": "approve", "reviewer": "D"}
        ).status_code
        == 404
    )

    done = client.post(url, json={"action": "reject", "reviewer": "D", "reason": "wrong"})
    assert done.json()["status"] == "rejected"
    twice = client.post(url, json={"action": "approve", "reviewer": "E"})
    assert (twice.status_code, twice.json()["detail"]) == (
        409,
        "this case was already rejected by D",
    )


def test_two_reviews_at_the_same_moment_only_one_wins(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(api._record_case(_saved(api, FAULT)))
    real_get = api.book.get

    def get_then_someone_else_reviews(case_id: str) -> Case | None:
        case: Case = real_get(case_id)  # read while still pending ...
        other = review_case(case, ReviewRequest(action="approve", reviewer="Other"))
        api.book.cases[case_id] = other  # ... and reviewed by someone else before this saves
        return case

    monkeypatch.setattr(api.book, "get", get_then_someone_else_reviews)
    answer = TestClient(api.app).post(
        "/api/cases/case-abc123/review", json={"action": "reject", "reviewer": "D", "reason": "x"}
    )
    assert answer.status_code == 409
    assert "someone else reviewed this case" in answer.json()["detail"]
    assert api.book.cases["case-abc123"].review.reviewer == "Other"


def test_the_case_list_with_counts(api: Any) -> None:
    asyncio.run(api._record_case(_saved(api, FAULT)))
    client = TestClient(api.app)
    client.post("/api/runs/inv-healthy1/case")  # unknown run: nothing made
    _saved(api, HEALTHY, "inv-healthy1")
    client.post("/api/runs/inv-healthy1/case")
    body = client.get("/api/cases").json()
    assert body["counts"] == {"pending": 2, "approved": 0, "rejected": 0}
    assert {c["run_id"] for c in body["cases"]} == {"inv-abc123", "inv-healthy1"}
    assert client.get("/api/cases?status=approved").json()["cases"] == []
    assert client.get("/api/cases/case-abc123").json()["question"] == FAULT["title"]
    assert client.get("/api/cases/case-nope").status_code == 404


def test_history_shows_each_conversations_case_status(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(api._record_case(_saved(api, FAULT)))
    _saved(api, HEALTHY, "inv-healthy1")
    client = TestClient(api.app)
    tags = {r["id"]: r["case_status"] for r in client.get("/api/investigations").json()}
    assert tags == {"inv-abc123": "pending", "inv-healthy1": None}

    def down() -> CaseBook:
        raise ConnectionError("Neo4j is not running")

    monkeypatch.setattr(api, "cases", down)
    runs = client.get("/api/investigations").json()  # still listed, just without tags
    assert [r["case_status"] for r in runs] == [None, None]


# ---------- the samples the frontend tests read ----------

SAMPLES = REPO_ROOT / "fixtures" / "cases" / "samples"
FIXED = "2026-10-07T10:00:00+00:00"


def _samples() -> dict[str, Case]:
    pending = _case(FAULT["events"])
    by_hand = _case(HEALTHY["events"], by_hand=True)
    assert pending is not None and by_hand is not None
    pending = pending.model_copy(update={"created_at": FIXED, "updated_at": FIXED})
    by_hand = by_hand.model_copy(
        update={
            "id": "case-healthy1",
            "run_id": "inv-healthy1",
            "created_at": FIXED,
            "updated_at": FIXED,
        }
    )
    corrected = review_case(
        pending,
        ReviewRequest(
            action="correct",
            reviewer="Praveen",
            root_cause="Fa2/0 on IPLC-RTR-MAA was shut during a change and not brought back",
            fix_applied="no shutdown on Fa2/0",
            fix_worked="yes",
        ),
    )
    assert corrected.review is not None
    corrected = corrected.model_copy(
        update={
            "updated_at": FIXED,
            "review": corrected.review.model_copy(update={"at": FIXED}),
        }
    )
    return {"fault1-pending": pending, "fault1-corrected": corrected, "healthy-by-hand": by_hand}


@pytest.mark.parametrize("name", ["fault1-pending", "fault1-corrected", "healthy-by-hand"])
def test_the_samples_the_frontend_tests_read_match_the_code(name: str) -> None:
    """After changing what a case holds: AINOPS_WRITE_SAMPLES=1 pytest -k samples"""
    produced = _samples()[name].model_dump(mode="json")
    path = SAMPLES / f"{name}.json"
    if os.environ.get("AINOPS_WRITE_SAMPLES"):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(produced, indent=2, ensure_ascii=False) + "\n")
    assert json.loads(path.read_text(encoding="utf-8")) == produced, "rewrite the samples"
