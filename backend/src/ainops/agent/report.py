"""The diagnosis the agent must return, and the code that checks it.

The LLM writes the Report (it must use this exact structure). Then plain code verifies it:
- every evidence id it cites must exist (made-up citations are removed and flagged);
- the confidence is computed by code from the evidence, never taken from the LLM.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


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


@dataclass
class Verdict:
    confidence: Literal["high", "medium", "low"]
    reasons: list[str]
    invalid_citations: list[str]


def verify(report: Report, evidence: dict[str, EvidenceRecord]) -> Verdict:
    """Check the citations and compute the confidence (code only, explainable reasons)."""
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
    elif report.outcome == "no_fault_found":
        checked = {r.device for r in evidence.values() if r.ok and r.device}
        confidence = "medium" if len(checked) >= 2 else "low"
        reasons.append(f"{len(checked)} device(s) checked and found healthy")
    else:
        confidence = "low"
        reasons.append("the investigation could not reach a conclusion")
    return Verdict(confidence, reasons, invalid)
