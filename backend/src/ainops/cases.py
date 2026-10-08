"""Cases: what an investigation found, checked by an engineer before AINOPS may learn from it.

When a reply ends with a root cause, plain code (not the LLM) drafts a case from the conversation:
the question, the root cause and the evidence that proves it, the devices and interfaces, the path,
the skill used, the suggested fix, and how the engineer steered the AI. Nothing in it is invented:
every field comes from the run's events. An engineer then reviews it:

    pending --approve-------------> approved   (the AI's root cause stands)
            --correct and approve-> approved   (the engineer's root cause, fix applied, worked?)
            --reject (reason)-----> rejected

The AI's draft is never changed by a review, so how often the AI was right can be measured later.
While a case is pending it follows the latest diagnosis of its conversation; once reviewed it is
locked. Only approved cases will be offered to the agent (phase B), as hints, never as evidence.
"""

import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from ainops.agent.conversation import Turn, turns_of

Status = Literal["pending", "approved", "rejected"]
NAME_CHARS = 80
TEXT_CHARS = 500  # phase B shows these to the agent: short and plain


class CaseError(Exception):
    """A review the case cannot take; the message says why (shown to the engineer)."""


class CaseEvidence(BaseModel):
    id: str
    tool: str
    device: str | None
    summary: str


class Draft(BaseModel):
    """What AINOPS concluded, exactly as the reply said it (never changed by a review)."""

    outcome: str
    summary: str
    root_cause: str | None
    evidence: list[CaseEvidence]  # the checks that prove the root cause
    confidence: str | None
    devices: list[str]
    interfaces: list[str]  # "IPLC-RTR-MAA Fa2/0"
    path: list[str]
    path_note: str | None  # e.g. "traced: no route at CORE-SW-TRV"
    skills: list[str]
    suggested_fix: list[str]


class Exchange(BaseModel):
    """One message of the conversation and what the reply concluded."""

    message: str
    outcome: str | None  # None: the reply was stopped or failed
    root_cause: str | None


class Review(BaseModel):
    action: Literal["approve", "correct", "reject"]
    reviewer: str
    at: str
    root_cause: str | None = None  # the engineer's, when corrected
    fix_applied: str | None = None
    fix_worked: Literal["yes", "no", "unknown"] | None = None
    reason: str | None = None  # why it was rejected


class Case(BaseModel):
    id: str
    run_id: str
    status: Status
    made_by: Literal["ainops", "engineer"]  # drafted after a diagnosis, or asked for by hand
    created_at: str
    updated_at: str
    question: str
    draft: Draft
    conversation: list[Exchange]
    checks: int
    duration_ms: int
    tokens: int = 0  # what the LLM read and wrote, all replies together
    hints_offered: list[str] = Field(default_factory=list)  # similar past cases shown (ids)
    review: Review | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def root_cause(self) -> str | None:
        """The root cause the case stands for: the engineer's correction, else the AI's."""
        if self.review and self.review.root_cause:
            return self.review.root_cause
        return self.draft.root_cause


class ReviewRequest(BaseModel):
    action: Literal["approve", "correct", "reject"]
    reviewer: str = Field(max_length=NAME_CHARS)
    root_cause: str | None = Field(default=None, max_length=TEXT_CHARS)
    fix_applied: str | None = Field(default=None, max_length=TEXT_CHARS)
    fix_worked: Literal["yes", "no", "unknown"] | None = None
    reason: str | None = Field(default=None, max_length=TEXT_CHARS)


# ---------- drafting a case from a conversation ----------

_SHORT = [
    ("tengigabitethernet", "Te"),
    ("gigabitethernet", "Gi"),
    ("fastethernet", "Fa"),
    ("ethernet", "E"),
    ("serial", "Se"),
    ("loopback", "Lo"),
]
_INTERFACE = re.compile(r"^[A-Za-z]{1,20}-?\d{1,3}(?:/\d{1,3}){0,3}(?:\.\d{1,5})?$")
DIAGNOSED = ("diagnosed",)
BY_HAND = ("diagnosed", "inconclusive", "no_fault_found")  # what an engineer can make a case of


def short_interface(name: str) -> str:
    """'FastEthernet2/0' and 'Fa2/0' -> 'Fa2/0', the spelling the graph uses."""
    for long, short in _SHORT:
        if name.lower().startswith(long):
            return short + name[len(long) :]
    return name


def case_id(run_id: str) -> str:
    """One case per conversation."""
    return "case-" + run_id.removeprefix("inv-")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def _named(text: str, device_names: list[str]) -> list[tuple[str, str | None]]:
    """Devices named in an `affected` entry, with the interface written next to each."""
    by_upper = {n.upper(): n for n in device_names}
    words = [w.strip(",;()") for w in text.split()]
    found: list[tuple[str, str | None]] = []
    for index, word in enumerate(words):
        device = by_upper.get(word.upper())
        if device is None:
            continue
        rest = words[index + 1 : index + 2]
        interface = rest[0] if rest and _INTERFACE.match(rest[0]) else None
        found.append((device, short_interface(interface) if interface else None))
    return found


def _path(results: list[dict[str, Any]]) -> tuple[list[str], str | None]:
    """The traced route (where traffic really goes) if there is one, else the cabled path."""
    for event in reversed(results):
        data = event.get("data")
        if event.get("tool") == "trace_route" and event.get("ok") and isinstance(data, dict):
            path = [str(d) for d in data.get("path") or []]
            status = str(data.get("status") or "")
            if status == "reached":
                return path, "traced: traffic reaches the destination"
            where = data.get("stopped_at") or (path[-1] if path else "?")
            return path, f"traced: {status.replace('_', ' ')} at {where}"
    for event in reversed(results):
        data = event.get("data")
        if event.get("tool") == "get_path" and event.get("ok") and isinstance(data, dict):
            return [str(d) for d in data.get("devices") or []], "cabled path (not traced)"
    return [], None


def _draft(
    turn: Turn, results: dict[str, dict[str, Any]], device_names: list[str], skills: list[str]
) -> Draft:
    report_event = turn.report or {}
    report = report_event.get("report") or {}
    cited = [str(e) for e in report.get("root_cause_evidence") or [] if str(e) in results]
    evidence = [
        CaseEvidence(
            id=eid,
            tool=str(results[eid].get("tool", "")),
            device=results[eid].get("device")
            if isinstance(results[eid].get("device"), str)
            else None,
            summary=str(results[eid].get("summary") or ""),
        )
        for eid in cited
    ]
    devices = [e.device for e in evidence if e.device]
    interfaces: list[str] = []
    for entry in report.get("affected") or []:
        for device, interface in _named(str(entry), device_names):
            devices.append(device)
            if interface:
                interfaces.append(f"{device} {interface}")
    for eid in cited:  # the problems code found in the evidence behind the root cause
        result = results[eid]
        health = result.get("health") or {}
        owner = result.get("device")
        if health.get("status") != "problem" or not isinstance(owner, str):
            continue
        for issue in health.get("issues") or []:
            if issue.get("interface"):
                interfaces.append(f"{owner} {short_interface(str(issue['interface']))}")
    path, path_note = _path(list(results.values()))
    return Draft(
        outcome=str(report.get("outcome", "")),
        summary=str(report.get("summary", "")),
        root_cause=report.get("root_cause") or None,
        evidence=evidence,
        confidence=report_event.get("confidence"),
        devices=_unique(devices),
        interfaces=_unique(interfaces),
        path=path,
        path_note=path_note,
        skills=_unique(skills),
        suggested_fix=[
            str(s.get("text", "")) for s in report.get("next_steps") or [] if s.get("kind") == "fix"
        ],
    )


def draft_case(
    run_id: str,
    title: str,
    started_at: str,
    events: list[dict[str, Any]],
    device_names: list[str],
    by_hand: bool = False,
) -> Case | None:
    """The case for a conversation, from its latest reply that found a root cause.

    With `by_hand` (the engineer asked for it), an inconclusive or healthy reply also makes a case:
    the engineer writes the real cause when reviewing it. None when there is nothing to draft.
    """
    turns = turns_of(events, title, started_at)
    allowed = BY_HAND if by_hand else DIAGNOSED
    chosen = next(
        (
            t
            for t in reversed(turns)
            if t.report and (t.report.get("report") or {}).get("outcome") in allowed
        ),
        None,
    )
    if chosen is None:
        return None
    results = {str(e["id"]): e for e in events if e.get("type") == "tool_result" and e.get("id")}
    now = _now()
    return Case(
        id=case_id(run_id),
        run_id=run_id,
        status="pending",
        made_by="engineer" if by_hand else "ainops",
        created_at=now,
        updated_at=now,
        question=turns[0].message,
        draft=_draft(
            chosen,
            results,
            device_names,
            [str(s) for t in turns if t.report for s in t.report.get("skills_used") or []],
        ),
        conversation=[
            Exchange(
                message=t.message,
                outcome=(t.report.get("report") or {}).get("outcome") if t.report else None,
                root_cause=(t.report.get("report") or {}).get("root_cause") if t.report else None,
            )
            for t in turns
        ],
        checks=len(results),
        duration_ms=sum(int(t.report.get("at_ms") or 0) for t in turns if t.report),
        tokens=sum(
            int((t.report.get("tokens") or {}).get(k) or 0)
            for t in turns
            if t.report
            for k in ("input", "output")
        ),
        hints_offered=_unique(
            [
                str(h.get("case_id"))
                for e in events
                if e.get("type") == "hints"
                for h in e.get("cases") or []
            ]
        ),
    )


def follow(existing: Case, newer: Case) -> Case:
    """A pending case follows the latest diagnosis of its conversation; a reviewed one is locked."""
    if existing.status != "pending":
        return existing
    return newer.model_copy(
        update={"id": existing.id, "created_at": existing.created_at, "made_by": existing.made_by}
    )


# ---------- the engineer's review ----------


def _text(value: str | None) -> str | None:
    value = " ".join((value or "").split())
    return value or None


def review_case(case: Case, request: ReviewRequest) -> Case:
    """Apply an engineer's review; raises CaseError when the rules say no."""
    if case.status != "pending":
        by = f" by {case.review.reviewer}" if case.review else ""
        raise CaseError(f"this case was already {case.status}{by}")
    reviewer = _text(request.reviewer)
    if reviewer is None:
        raise CaseError("type your name: every review says who made it")
    root_cause, reason = _text(request.root_cause), _text(request.reason)
    if request.action == "reject" and reason is None:
        raise CaseError("say why the case is rejected")
    if request.action == "correct" and root_cause is None:
        raise CaseError("write the real root cause to correct the case")
    if request.action == "approve" and not case.draft.root_cause:
        raise CaseError("AINOPS found no root cause here: use Correct to write the real one")
    review = Review(
        action=request.action,
        reviewer=reviewer,
        at=_now(),
        root_cause=root_cause if request.action == "correct" else None,
        fix_applied=_text(request.fix_applied) if request.action != "reject" else None,
        fix_worked=request.fix_worked if request.action != "reject" else None,
        reason=reason if request.action == "reject" else None,
    )
    status: Status = "rejected" if request.action == "reject" else "approved"
    return case.model_copy(update={"status": status, "review": review, "updated_at": review.at})
