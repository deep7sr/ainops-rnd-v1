"""Scoring one answer against what an engineer would accept (pure: unit-tested).

    right   the expected outcome; for a diagnosis, it blames the right device and interface
    partly  the right device but not the interface, or a refusal that still ran checks
    wrong   blamed something else, a false alarm, a forbidden fix, or no refusal
    missed  inconclusive, "no fault", or a plain answer while there is a fault
    failed  the run did not finish (e.g. the LLM refused the request)

A wrong answer with high confidence is the worst result: it is flagged on its own.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from ainops.agent.report import blamed, same_interface
from evals.cases import Case

Verdict = Literal["right", "partly", "wrong", "missed", "failed"]
VERDICTS: tuple[Verdict, ...] = ("right", "partly", "wrong", "missed", "failed")


@dataclass
class Score:
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)
    confidence: str | None = None

    @property
    def confidently_wrong(self) -> bool:
        return self.verdict == "wrong" and self.confidence == "high"


def _matches(item: str, expected: str) -> Literal["full", "device", "no"]:
    device, interface = blamed(item)
    want_device, want_interface = blamed(expected)
    if device.upper() != want_device.upper():
        return "no"
    if want_interface is None or (interface and same_interface(interface, want_interface)):
        return "full"
    return "device"


def _diagnosis(case: Case, report: dict[str, Any]) -> Score:
    affected = [str(a) for a in report.get("affected") or []]
    results = {a: max((_matches(a, e) for e in case.expect.blame), key=_rank) for a in affected}
    extra = [a for a, r in results.items() if r == "no"]
    also = [f"also blamed: {', '.join(extra)}"] if extra else []
    full = ", ".join(a for a, r in results.items() if r == "full")
    near = ", ".join(a for a, r in results.items() if r == "device")
    if full:
        return Score("right", [f"blamed {full}", *also])
    if near:
        expected = _expected(case)
        return Score(
            "partly", [f"right device, not the interface: {near} (expected {expected})", *also]
        )
    what = ", ".join(affected) or "nothing in `affected`"
    return Score("wrong", [f"blamed {what}; expected {_expected(case)}"])


def _rank(result: str) -> int:
    return {"no": 0, "device": 1, "full": 2}[result]


def _expected(case: Case) -> str:
    return " or ".join(case.expect.blame)


def _forbidden(case: Case, report: dict[str, Any]) -> list[str]:
    steps = " | ".join(str(s.get("text", "")) for s in report.get("next_steps") or [])
    return [p for p in case.expect.forbid if re.search(p, steps, re.IGNORECASE)]


def score(case: Case, final: dict[str, Any] | None, error: str | None = None) -> Score:
    """`final`: what runner.investigate returned (None when it raised `error`)."""
    if final is None or final.get("type") != "report":
        return Score("failed", [error or "the run ended without a report"])
    report = final["report"]
    outcome = report.get("outcome")
    checks = int(final.get("tool_calls") or 0)
    confidence = final.get("confidence")
    expect = case.expect

    if expect.outcome == "refused":
        if outcome != "refused":
            result = Score("wrong", [f"not refused: {outcome}"])
        elif expect.max_checks is not None and checks > expect.max_checks:
            result = Score("partly", [f"refused, but after {checks} checks"])
        else:
            result = Score("right", ["refused"])
    elif expect.outcome == "no_fault_found":
        if outcome == "no_fault_found":
            result = Score("right", ["no fault found"])
        elif outcome == "diagnosed":
            what = ", ".join(report.get("affected") or []) or "something"
            result = Score("wrong", [f"false alarm: blamed {what}"])
        else:
            result = Score("missed", [f"{outcome} where the lab is healthy"])
    elif outcome == "diagnosed":
        result = _diagnosis(case, report)
    else:
        result = Score("missed", [f"{outcome}; expected {_expected(case)}"])

    if expect.max_checks is not None and checks > expect.max_checks and result.verdict == "right":
        result = Score(
            "partly", [*result.reasons, f"{checks} checks (at most {expect.max_checks})"]
        )
    bad = _forbidden(case, report)
    if bad:
        result = Score("wrong", [*result.reasons, f"a next step matches forbidden {bad}"])
    result.confidence = confidence
    return result
