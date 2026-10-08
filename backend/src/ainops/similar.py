"""Similar past cases: hints from what engineers approved before, never evidence.

At the start of every reply, plain code (no LLM) compares what is known so far with the APPROVED
cases (cases.py): the devices, addresses, sites and words of the conversation, and the kind of
problem the checks found. The best few become hints in the agent's prompt, each with the reasons
it matched. A hint has no evidence id: the agent cannot cite it, it does not count towards the
confidence, and its addresses do not become usable in checks (runner.py keeps them out).

The scoring is simple on purpose, so every match can be explained to the engineer:

    shared device            3 each      a case must share at least one device,
    shared subnet            2 each      subnet or kind of problem; words and site
    same kind of problem     2 each      alone are not enough
    shared site              1 each
    similar wording          up to 4     (share of meaningful words both use)
"""

import ipaddress
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ainops.cases import Case

MAX_HINTS = 3
MIN_SCORE = 4.0
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b")
_WORD = re.compile(r"[a-z][a-z0-9-]{2,}")
_STOP = {
    "the", "and", "for", "are", "was", "why", "can", "cannot", "can't", "not", "does", "doesn't",
    "what", "with", "from", "this", "that", "there", "users", "user", "reach", "is", "any",
    "anything", "wrong", "between", "check", "please", "look", "still", "now", "site", "lan",
}  # fmt: skip
# The kind of problem a check found, from the code-written summaries (network/health.py).
_PROBLEMS = [
    ("interface shut", re.compile(r"administratively down|admin[- ]down|\bshut\b", re.I)),
    ("interface down", re.compile(r"not up|line protocol is down|\bis down\b", re.I)),
    ("OSPF neighbour missing", re.compile(r"\bmissing\b", re.I)),
    ("no route", re.compile(r"no route", re.I)),
    ("ping fails", re.compile(r"\b0/\d+\b|unreachable|0% success|timed out", re.I)),
]


@dataclass
class Clues:
    devices: set[str] = field(default_factory=set)
    subnets: set[str] = field(default_factory=set)
    sites: set[str] = field(default_factory=set)
    problems: set[str] = field(default_factory=set)
    words: set[str] = field(default_factory=set)


@dataclass
class Hint:
    case_id: str
    question: str
    root_cause: str
    corrected: bool  # the root cause is the engineer's correction
    fix: str | None  # what fixed it, or what AINOPS suggested
    fix_worked: str | None
    reviewer: str
    reasons: list[str]
    score: float

    def as_event(self) -> dict[str, Any]:
        return asdict(self)


def _subnets(text: str) -> set[str]:
    found = set()
    for match in _IPV4.findall(text):
        try:
            if "/" in match:
                found.add(str(ipaddress.ip_network(match, strict=False)))
            else:  # a plain address: its /24, the size of every lab LAN and link
                found.add(str(ipaddress.ip_interface(f"{match}/24").network))
        except ValueError:
            continue
    return found


def _problems(checks: list[tuple[str, str]]) -> set[str]:
    """Kinds of problem in (tool, summary) pairs. 'Shut' is also 'not up': only shut is kept."""
    kinds = set()
    for tool, summary in checks:
        for kind, pattern in _PROBLEMS:
            if kind == "OSPF neighbour missing" and "ospf" not in tool:
                continue
            if pattern.search(summary):
                kinds.add(kind)
    if "interface shut" in kinds:
        kinds.discard("interface down")
    return kinds


def clues_of(
    texts: list[str],
    checks: Sequence[tuple[str | None, str, str]],
    device_sites: dict[str, str],
) -> Clues:
    """What is known: messages, and checks as (device, tool, summary)."""
    text = " ".join(texts)
    upper = {name.upper(): name for name in device_sites}
    named = {upper[w.upper()] for w in re.findall(r"[\w-]+", text) if w.upper() in upper}
    devices = named | {d for d, _, _ in checks if d}
    site_codes = {s.upper() for s in device_sites.values() if s}
    sites = {device_sites[d] for d in devices if device_sites.get(d)}
    sites |= {w.upper() for w in re.findall(r"[A-Za-z]+", text) if w.upper() in site_codes}
    words = {w for w in _WORD.findall(text.lower()) if w not in _STOP}
    return Clues(
        devices=devices,
        subnets=_subnets(text),
        sites=sites,
        problems=_problems([(tool, summary) for _, tool, summary in checks]),
        words=words - {d.lower() for d in device_sites},
    )


def case_clues(case: Case, device_sites: dict[str, str]) -> Clues:
    texts = [case.question, *(x.message for x in case.conversation[1:])]
    checks = [(e.device, e.tool, e.summary) for e in case.draft.evidence]
    clues = clues_of(texts, checks, device_sites)
    clues.devices |= set(case.draft.devices)
    clues.sites |= {device_sites[d] for d in case.draft.devices if device_sites.get(d)}
    return clues


def _score(now: Clues, then: Clues) -> tuple[float, list[str]]:
    devices = sorted(now.devices & then.devices)
    subnets = sorted(now.subnets & then.subnets)
    problems = sorted(now.problems & then.problems)
    sites = sorted(now.sites & then.sites)
    if not (devices or subnets or problems):
        return 0.0, []
    union = now.words | then.words
    wording = len(now.words & then.words) / len(union) if union else 0.0
    score = 3 * len(devices) + 2 * len(subnets) + 2 * len(problems) + len(sites) + 4 * wording
    reasons = []
    if devices:
        reasons.append(f"same device{'s' if len(devices) > 1 else ''} {', '.join(devices)}")
    if subnets:
        reasons.append(f"same subnet{'s' if len(subnets) > 1 else ''} {', '.join(subnets)}")
    if problems:
        reasons.append(f"same kind of problem: {', '.join(problems)}")
    if sites and not devices:
        reasons.append(f"same site {', '.join(sites)}")
    if wording >= 0.5:
        reasons.append("a very similar question")
    return round(score, 2), reasons


def similar_cases(
    cases: list[Case],
    now: Clues,
    device_sites: dict[str, str],
    exclude: set[str] | None = None,
) -> list[Hint]:
    """The best approved cases for what is known now (at most MAX_HINTS, best first)."""
    hints = []
    for case in cases:
        if case.status != "approved" or case.id in (exclude or set()) or not case.root_cause:
            continue
        score, reasons = _score(now, case_clues(case, device_sites))
        if score < MIN_SCORE:
            continue
        review = case.review
        fix = review.fix_applied if review and review.fix_applied else None
        hints.append(
            Hint(
                case_id=case.id,
                question=case.question,
                root_cause=case.root_cause,
                corrected=bool(review and review.root_cause),
                fix=fix or ("; ".join(case.draft.suggested_fix) or None),
                fix_worked=review.fix_worked if fix and review else None,
                reviewer=review.reviewer if review else "",
                reasons=reasons,
                score=score,
            )
        )
    hints.sort(key=lambda h: (-h.score, h.case_id))
    return hints[:MAX_HINTS]


def hints_prompt(hints: list[Hint]) -> str:
    """The hints as the agent reads them: clearly not evidence."""
    if not hints:
        return ""
    lines = [
        "",
        "Similar past cases: HINTS from investigations engineers approved. They are NOT",
        "evidence: never cite them, and check what they suggest on the live devices first.",
    ]
    for hint in hints:
        fix = ""
        if hint.fix:
            worked = {"yes": " (it worked)", "no": " (it did not work)"}.get(
                hint.fix_worked or "", ""
            )
            fix = f" Fix: {hint.fix}{worked}."
        lines.append(
            f'- {hint.case_id}: "{hint.question}" Root cause: {hint.root_cause}.{fix} '
            f"Similar because: {'; '.join(hint.reasons)}."
        )
    return "\n".join(lines) + "\n"


@dataclass
class Hints:
    """What the lookup gave for one reply: the hints, how many approved cases it looked at, and
    why it could not look (Neo4j down), if it could not."""

    cases: list[Hint] = field(default_factory=list)
    looked_at: int = 0
    error: str | None = None
