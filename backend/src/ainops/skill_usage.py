"""How often each expert skill was used, read from the saved investigations (Skills page).

A run counts once per skill however many of its replies opened it. The latest runs come first.
"""

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

RECENT = 5


class SkillRun(BaseModel):
    id: str
    title: str
    started_at: str
    outcome: str | None


class SkillUsage(BaseModel):
    count: int = 0
    last_at: str | None = None
    recent: list[SkillRun] = []  # at most RECENT, latest first


def skill_usage(runs: Iterable[dict[str, Any]]) -> dict[str, SkillUsage]:
    """`runs`: {"id", "title", "started_at", "events", "outcome"} per investigation."""
    used: dict[str, list[SkillRun]] = {}
    for run in runs:
        names = {
            str(e["name"])
            for e in run["events"]
            if e.get("type") == "skill" and isinstance(e.get("name"), str)
        }
        for name in names:
            used.setdefault(name, []).append(
                SkillRun(
                    id=run["id"],
                    title=run["title"],
                    started_at=run["started_at"],
                    outcome=run.get("outcome"),
                )
            )
    usage = {}
    for name, found in used.items():
        found.sort(key=lambda r: r.started_at, reverse=True)
        usage[name] = SkillUsage(
            count=len(found), last_at=found[0].started_at, recent=found[:RECENT]
        )
    return usage
