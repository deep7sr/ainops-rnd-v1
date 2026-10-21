"""The diagnosis the agent must return, and the code that checks it.

The LLM writes the Report (it must use this exact structure). Then plain code verifies it:
- every evidence id it cites must exist (made-up citations are removed and flagged);
- the confidence is computed by code from the evidence, never taken from the LLM;
- what it blames ("affected") must be shown by a cited check of that device, naming that
  interface: a root cause no cited check points at is low, however many checks it cites.

In a conversation, evidence from earlier replies stays valid to cite, but the network may have
changed since: a root cause that rests on checks older than STALE_AFTER gets a lower confidence.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from ainops.network.parsers import cisco_interface


class Finding(BaseModel):
    text: str = Field(description="One observed fact, in plain words")
    evidence: list[str] = Field(description="Evidence ids that show it, e.g. ['E3']")


class Action(BaseModel):
    text: str = Field(description="What an engineer should do next")
    kind: Literal["verify", "fix", "escalate"]


class Report(BaseModel):
    """The final answer to the engineer."""

    outcome: Literal["diagnosed", "no_fault_found", "inconclusive", "refused", "answered"] = Field(
        description=(
            "diagnosed: root cause found with evidence; no_fault_found: the path was checked and "
            "is healthy; inconclusive: not enough evidence; refused: the request asked to change "
            "the network or is out of scope; answered: a question that needed no investigation"
        )
    )
    summary: str = Field(description="2-4 plain sentences a junior engineer understands")
    root_cause: str | None = Field(
        default=None, description="The cause in one sentence (only when diagnosed)"
    )
    root_cause_evidence: list[str] = Field(
        default_factory=list, description="Evidence ids that prove the root cause"
    )
    affected: list[str] = Field(
        default_factory=list, description="Devices/interfaces at fault, e.g. 'IPLC-RTR-MAA Fa2/0'"
    )
    findings: list[Finding] = Field(default_factory=list)
    next_steps: list[Action] = Field(default_factory=list)
    limitations: list[str] = Field(
        default_factory=list, description="What was not or could not be checked"
    )


@dataclass
class EvidenceRecord:
    id: str
    tool: str
    device: str | None
    summary: str
    source: str  # live (graph for topology answers)
    ok: bool
    at: datetime | None = None  # when the check ran (None: unknown, counted as fresh)


STALE_AFTER = timedelta(minutes=15)
Level = Literal["high", "medium", "low"]
LOWER: dict[str, Level] = {"high": "medium", "medium": "low", "low": "low"}


def _old(record: EvidenceRecord, now: datetime) -> bool:
    return record.at is not None and now - record.at > STALE_AFTER


# An interface name in a check's summary: Fa2/0, FastEthernet2/0, E1/0, ge-0/0/1, ge-0/0/0.0.
_INTERFACE = re.compile(r"[A-Za-z][A-Za-z-]*\d+(?:/\d+)*(?:\.\d+)?")


def _same_interface(name: str) -> str:
    """One spelling to compare: Fa2/0 and FastEthernet2/0 -> fastethernet2/0."""
    return cisco_interface(name).lower()


def blamed(item: str) -> tuple[str, str | None]:
    """'IPLC-RTR-MAA Fa2/0' -> (device, interface); 'FWL-MAA (down)' -> ('FWL-MAA', None)."""
    words = item.split()
    if not words:
        return "", None
    # 'E1/1-E1/3' or 'Fa2/0,' still blame an interface (the first one); '(no' does not.
    named_interface = _INTERFACE.match(words[1]) if len(words) > 1 else None
    return words[0], named_interface.group() if named_interface else None


def same_interface(a: str, b: str) -> bool:
    return _same_interface(a) == _same_interface(b)


def _shown_by(item: str, records: list[EvidenceRecord]) -> bool:
    """Does a check of the blamed device show the blamed interface ('IPLC-RTR-MAA Fa2/0')?
    An item without an interface ('FWL-MAA') needs a check of that device."""
    device, interface = blamed(item)
    if not device:
        return False
    for record in records:
        if record.device != device:
            continue
        named = {_same_interface(n) for n in _INTERFACE.findall(record.summary)}
        if interface is None or _same_interface(interface) in named:
            return True
    return False


def not_shown(report: Report, evidence: dict[str, EvidenceRecord]) -> list[str]:
    """What a diagnosis blames when none of it is shown by a cited, working root-cause check
    (empty: something is shown, or there is nothing to judge)."""
    good = [evidence[e] for e in report.root_cause_evidence if e in evidence and evidence[e].ok]
    if report.outcome != "diagnosed" or not good or not report.affected:
        return []
    return [] if any(_shown_by(a, good) for a in report.affected) else list(report.affected)


@dataclass
class Verdict:
    confidence: Literal["high", "medium", "low"]
    reasons: list[str]
    invalid_citations: list[str]


def verify(
    report: Report, evidence: dict[str, EvidenceRecord], now: datetime | None = None
) -> Verdict:
    """Check the citations and compute the confidence (code only, explainable reasons)."""
    now = now or datetime.now(UTC)
    cited = set(report.root_cause_evidence) | {e for f in report.findings for e in f.evidence}
    invalid = sorted(c for c in cited if c not in evidence)
    report.root_cause_evidence = [e for e in report.root_cause_evidence if e in evidence]
    for finding in report.findings:
        finding.evidence = [e for e in finding.evidence if e in evidence]

    reasons: list[str] = []
    if invalid:
        reasons.append(f"removed citations of evidence that does not exist: {', '.join(invalid)}")
    good = [evidence[e] for e in report.root_cause_evidence if evidence[e].ok]
    devices = {e.device for e in good if e.device}

    if report.outcome in ("refused", "answered"):
        return Verdict("high", ["no network evidence needed for this answer"], invalid)
    if report.outcome == "diagnosed":
        if len(good) >= 2 and len(devices) >= 1 and not invalid:
            confidence: Literal["high", "medium", "low"] = "high"
            reasons.append(f"root cause backed by {len(good)} pieces of evidence")
        elif good:
            confidence = "medium"
            reasons.append(f"root cause backed by {len(good)} piece of evidence")
        else:
            confidence = "low"
            reasons.append("the root cause cites no valid evidence")
        blamed = not_shown(report, evidence)
        if blamed:
            confidence = "low"
            reasons.append(
                f"nothing cited for the root cause shows {', '.join(blamed)}: check it directly"
            )
        old = [e.id for e in good if _old(e, now)]
        if old:
            confidence = LOWER[confidence]
            reasons.append(
                f"{', '.join(old)} taken more than {STALE_AFTER.seconds // 60} minutes ago: "
                "re-check suggested"
            )
    elif report.outcome == "no_fault_found":
        ok = [r for r in evidence.values() if r.ok and r.device]
        checked = {r.device for r in ok if not _old(r, now)}
        confidence = "medium" if len(checked) >= 2 else "low"
        reasons.append(f"{len(checked)} device(s) checked and found healthy")
        if any(_old(r, now) for r in ok):
            reasons.append(
                f"checks older than {STALE_AFTER.seconds // 60} minutes are not counted: "
                "re-check suggested"
            )
    else:
        confidence = "low"
        reasons.append("the investigation could not reach a conclusion")
    return Verdict(confidence, reasons, invalid)
