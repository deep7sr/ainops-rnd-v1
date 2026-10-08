"""How often each skill was used, from the saved investigations (Skills page)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ainops.api.runs import Run
from ainops.skill_usage import RECENT, skill_usage


def opened(name: object) -> dict[str, Any]:
    return {"type": "skill", "name": name, "steps": [], "at_ms": 5}


def run(
    run_id: str, day: int, *events: dict[str, Any], outcome: str | None = "diagnosed"
) -> dict[str, Any]:
    return {
        "id": run_id,
        "title": f"question {run_id}",
        "started_at": f"2026-10-{day:02d}T09:00:00+00:00",
        "events": [{"type": "started"}, *events],
        "outcome": outcome,
    }


def test_each_run_counts_once_per_skill_latest_first() -> None:
    usage = skill_usage(
        [
            run("inv-a", 5, opened("link-check")),
            run("inv-b", 7, opened("link-check"), opened("link-check"), opened("ospf-down")),
            run("inv-c", 6, {"type": "tool_call", "tool": "ping"}),
        ]
    )
    assert set(usage) == {"link-check", "ospf-down"}
    link = usage["link-check"]
    assert link.count == 2  # inv-b opened it twice (two replies): still one run
    assert link.last_at == "2026-10-07T09:00:00+00:00"
    assert [r.id for r in link.recent] == ["inv-b", "inv-a"]
    assert link.recent[0].title == "question inv-b"
    assert link.recent[0].outcome == "diagnosed"


def test_only_the_latest_runs_are_listed_but_all_are_counted() -> None:
    usage = skill_usage(run(f"inv-{day}", day, opened("x")) for day in range(1, 10))
    assert usage["x"].count == 9
    assert [r.id for r in usage["x"].recent] == [f"inv-{d}" for d in range(9, 9 - RECENT, -1)]


def test_a_malformed_skill_event_is_ignored() -> None:
    assert skill_usage([run("inv-a", 5, opened(42), {"type": "skill"})]) == {}


def test_the_skills_api_adds_the_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ainops.api import app as api

    folder = tmp_path / "link-check"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: link-check\ndescription: Use when a link looks down.\n---\n1. `ping` it.\n",
        encoding="utf-8",
    )
    (tmp_path / "never-used").mkdir()
    (tmp_path / "never-used" / "SKILL.md").write_text(
        "---\nname: never-used\ndescription: Use never.\n---\n1. `ping` it.\n", encoding="utf-8"
    )

    async def tools(url: str) -> list[dict[str, Any]]:
        return [{"name": "ping"}]

    used = Run("inv-1", "investigation", "Is the link up?", "2026-10-08T10:00:00+00:00")
    used.events = [{"type": "started"}, opened("link-check")]
    discovery = Run("disc-1", "discovery", "Discovery", "2026-10-08T11:00:00+00:00")
    discovery.events = [opened("link-check")]  # not an investigation: never counted
    monkeypatch.setattr(api.settings, "skills_dir", tmp_path)
    monkeypatch.setattr(api, "_list_tools", tools)
    monkeypatch.setattr(api.registry, "runs", {"inv-1": used, "disc-1": discovery})

    body = TestClient(api.app).get("/api/skills").json()
    by_name = {s["name"]: s["usage"] for s in body["skills"]}
    assert by_name["link-check"]["count"] == 1
    assert by_name["link-check"]["recent"] == [
        {
            "id": "inv-1",
            "title": "Is the link up?",
            "started_at": "2026-10-08T10:00:00+00:00",
            "outcome": None,  # still running: no report yet
        }
    ]
    assert by_name["never-used"] == {"count": 0, "last_at": None, "recent": []}
