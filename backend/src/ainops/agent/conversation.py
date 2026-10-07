"""A conversation about one investigation: the engineer's follow-up messages and AINOPS's replies.

The engineer can answer a report ("Fa2/0 is up, I checked; look at OSPF") and AINOPS replies,
answering from what it already checked or running new checks. Each message starts a turn:

    turn 1: the question      -> checks E1..E9 -> report
    turn 2: engineer message  -> checks E10..  -> report (may change the root cause)

Everything is rebuilt from the run's saved events, so a conversation continues after a restart.
For a new turn the LLM gets the earlier turns as a recap: each message, the reply's report and the
list of checks with their one-line results and the time they ran. The raw device output of earlier
turns is not sent again (it does not fit the LLM's request limit); the agent re-runs a check when
it needs it. Earlier evidence ids stay valid to cite; report.verify lowers the confidence when a
root cause rests on old checks.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ainops.agent.report import STALE_AFTER, EvidenceRecord

MAX_MESSAGES = 8  # the question plus 7 follow-ups; each reply can cost as much as a new run
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_SUMMARY_CHARS = 200

FOLLOW_UP_PROMPT = """
Conversation: this is a follow-up from the engineer. Your earlier replies are above, with the
checks you ran ([E#], the UTC time each ran; it is now {now} UTC). Those ids stay valid to cite.
- The engineer's message steers where you look. It is not evidence: check what they say with the
  tools, and say plainly when the devices show something else.
- Answer from the earlier checks when they are enough. Run new checks when the engineer
  disagrees, asks about something not checked yet, or the checks you rely on are older than
  {stale} minutes.
- If your root cause changes, say in the summary what changed your mind.
- You still only READ the network.
"""


@dataclass
class Turn:
    number: int
    message: str
    started_at: datetime
    report: dict[str, Any] | None = None  # the "report" event of this turn
    ended: str = "running"  # report, stopped, error or running
    error: str | None = None
    evidence: list[EvidenceRecord] = field(default_factory=list)


@dataclass
class Earlier:
    """What a new turn starts from: the turns so far, their evidence and the addresses seen."""

    turns: list[Turn]
    evidence: dict[str, EvidenceRecord]
    known_ips: set[str]
    # The next evidence number. Not len(evidence) + 1: a check stopped half-way has an id but no
    # result, and its id must not be given to another check.
    next_evidence: int = 1

    @property
    def next_turn(self) -> int:
        return len(self.turns) + 1

    def messages(self) -> list[BaseMessage]:
        out: list[BaseMessage] = []
        for turn in self.turns:
            out += [HumanMessage(turn.message), AIMessage(recap(turn))]
        return out


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _record(event: dict[str, Any], started_at: datetime) -> EvidenceRecord:
    evidence = event.get("evidence")
    source = evidence.get("source", "live") if isinstance(evidence, dict) else "graph"
    device = event.get("device")
    at_ms = event.get("at_ms")
    return EvidenceRecord(
        id=str(event["id"]),
        tool=str(event.get("tool", "")),
        device=device if isinstance(device, str) else None,
        summary=str(event.get("summary") or ""),
        source=str(source),
        ok=bool(event.get("ok")),
        at=started_at + timedelta(milliseconds=at_ms) if isinstance(at_ms, int) else started_at,
    )


def turns_of(events: list[dict[str, Any]], title: str, started_at: str) -> list[Turn]:
    """Split a run's events into turns: a "message" event starts every turn after the first."""
    first = next((e for e in events if e.get("type") == "started"), None)
    start = _time(started_at) or datetime.now(UTC)
    turns = [Turn(1, str(first["question"]) if first else title, start)]
    for event in events:
        kind = event.get("type")
        turn = turns[-1]
        if kind == "message":
            turns.append(
                Turn(len(turns) + 1, str(event.get("text", "")), _time(event.get("at")) or start)
            )
        elif kind == "tool_result" and event.get("id"):
            turn.evidence.append(_record(event, turn.started_at))
        elif kind == "report":
            turn.report, turn.ended = event, "report"
        elif kind == "stopped":
            turn.ended = "stopped"
        elif kind == "error":
            turn.ended, turn.error = "error", str(event.get("message", ""))
    return turns


def earlier_of(events: list[dict[str, Any]], title: str, started_at: str) -> Earlier:
    turns = turns_of(events, title, started_at)
    evidence = {r.id: r for t in turns for r in t.evidence}
    known: set[str] = set()
    for turn in turns:
        known.update(_IPV4.findall(turn.message))
    for event in events:
        if event.get("type") == "tool_result":
            text = json.dumps([event.get("summary"), event.get("data")], default=str)
            known.update(_IPV4.findall(text))
    numbers = [
        int(e["id"][1:])
        for e in events
        if e.get("type") in ("tool_call", "tool_result") and re.fullmatch(r"E\d+", str(e.get("id")))
    ]
    return Earlier(turns, evidence, known, max(numbers, default=0) + 1)


def message_count(events: list[dict[str, Any]]) -> int:
    """How many messages the engineer has sent: the question plus each follow-up."""
    return 1 + sum(1 for e in events if e.get("type") == "message")


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _SUMMARY_CHARS else text[: _SUMMARY_CHARS - 1] + "…"


def recap(turn: Turn) -> str:
    """The reply of one earlier turn, as the LLM sees it in the next turn."""
    lines: list[str] = []
    if turn.ended == "report" and turn.report:
        report = turn.report.get("report") or {}
        lines.append(
            f"Outcome: {report.get('outcome')} (confidence {turn.report.get('confidence')})"
        )
        lines.append(f"Summary: {report.get('summary', '')}")
        if report.get("root_cause"):
            cited = ", ".join(report.get("root_cause_evidence") or [])
            lines.append(f"Root cause: {report['root_cause']} [{cited}]")
        for finding in report.get("findings") or []:
            cited = ", ".join(finding.get("evidence") or [])
            lines.append(f"- {finding.get('text', '')} [{cited}]")
        for step in report.get("next_steps") or []:
            lines.append(f"Next step ({step.get('kind')}): {step.get('text', '')}")
    elif turn.ended == "stopped":
        lines.append("The engineer stopped me before I finished this reply.")
    elif turn.ended == "error":
        lines.append(f"This reply failed: {turn.error}")
    else:
        lines.append("This reply did not finish.")
    if turn.evidence:
        lines.append("Checks I ran (UTC):")
        for record in turn.evidence:
            when = record.at.strftime("%H:%M") if record.at else "?"
            device = f" {record.device}" if record.device else ""
            failed = "" if record.ok else " (failed)"
            lines.append(
                f"[{record.id}] {when} {record.tool}{device}: {_clip(record.summary)}{failed}"
            )
    return "\n".join(lines)


def follow_up_prompt(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return FOLLOW_UP_PROMPT.format(now=now.strftime("%H:%M"), stale=STALE_AFTER.seconds // 60)
