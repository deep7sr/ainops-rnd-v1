"""Draft, live, off: only live skills are offered to the agent; a draft can be tried on purpose.

Also reviewing a skill, and restoring an earlier version (skill_book.py and the API)."""

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ainops.agent.skills import load_skills, parse_skill
from ainops.api.runs import Run, RunRegistry
from ainops.skill_book import (
    SkillConflict,
    SkillError,
    SkillForm,
    SkillSave,
    history,
    read,
    restore,
    review,
    save,
    set_status,
)

TOOLS = {"get_interfaces", "ping", "get_logs"}
T1 = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
T3 = datetime(2026, 10, 9, 11, 0, tzinfo=UTC)


def skill_file(status: str | None, reviewed_by: str = "") -> str:
    lines = ["---", "name: link-check", "description: Use when one link looks down.", "metadata:"]
    lines.append(f"  reviewed_by: '{reviewed_by}'")
    if status is not None:
        lines.append(f"  status: {status}")
    return "\n".join([*lines, "---", "1. `ping` the other end.", ""])


def form(**changes: Any) -> SkillForm:
    values: dict[str, Any] = {
        "name": "link-check",
        "description": "Use when one link looks down.",
        "intro": "",
        "steps": ["`ping` the other end."],
    }
    return SkillForm(**{**values, **changes})


def version(base: Path, name: str = "link-check") -> str:
    found = read(base, name)
    assert found is not None
    return found[1]


def write(base: Path, name: str, text: str) -> None:
    (base / name).mkdir(parents=True, exist_ok=True)
    (base / name / "SKILL.md").write_text(text, encoding="utf-8", newline="\n")


# ---------- the status in the file ----------


@pytest.mark.parametrize(
    ("status", "reviewed_by", "expected"),
    [(None, "", "draft"), ("draft", "", "draft"), ("LIVE", "Sudhir", "live"), ("off", "", "off")],
)
def test_the_status_is_read_and_a_missing_one_is_draft(
    status: str | None, reviewed_by: str, expected: str
) -> None:
    skill, problems = parse_skill("link-check", skill_file(status, reviewed_by), TOOLS)
    assert problems == [] and skill is not None and skill.status == expected


@pytest.mark.parametrize(
    ("status", "reviewed_by", "problem"),
    [
        ("live", "", "status is live but nobody reviewed it"),
        ("live", "  ", "status is live but nobody reviewed it"),
        ("published", "", "status 'published' must be draft, live or off"),
        ("on", "", "status 'on' must be draft, live or off"),  # YAML reads it as true
        ("yes", "", "status 'on' must be draft, live or off"),
    ],
)
def test_a_live_skill_nobody_reviewed_is_left_out(
    status: str, reviewed_by: str, problem: str
) -> None:
    skill, problems = parse_skill("link-check", skill_file(status, reviewed_by), TOOLS)
    assert skill is None and any(problem in p for p in problems)


# ---------- what the agent is offered ----------


def library(base: Path) -> Any:
    write(base, "live-one", skill_file("live", "Sudhir").replace("link-check", "live-one"))
    write(base, "draft-one", skill_file("draft").replace("link-check", "draft-one"))
    write(base, "off-one", skill_file("off", "Sudhir").replace("link-check", "off-one"))
    return load_skills(base, TOOLS)


def test_the_agent_is_offered_only_live_skills(tmp_path: Path) -> None:
    offered = library(tmp_path).for_agent()
    assert sorted(offered.skills) == ["live-one"]
    assert offered.trying is None
    section = offered.prompt_section()
    assert "- live-one:" in section and "draft-one" not in section and "off-one" not in section
    assert "try the skill" not in section


@pytest.mark.parametrize("tried", ["draft-one", "off-one", " Draft-One "])
def test_a_skill_being_tried_is_offered_whatever_its_status(tmp_path: Path, tried: str) -> None:
    offered = library(tmp_path).for_agent(tried)
    name = tried.strip().lower()
    assert sorted(offered.skills) == sorted(["live-one", name])
    assert offered.trying == name
    assert f"started this investigation to try the skill {name}: open it" in (
        offered.prompt_section()
    )


def test_trying_a_skill_that_does_not_exist_offers_nothing_more(tmp_path: Path) -> None:
    offered = library(tmp_path).for_agent("no-such-skill")
    assert sorted(offered.skills) == ["live-one"] and offered.trying is None


# ---------- review and status on the Skills page ----------


def created(base: Path) -> str:
    save(base, SkillSave(skill=form(), by="Praveen"), TOOLS, T1)
    return version(base)


def test_a_review_keeps_the_skill_a_draft_and_keeps_no_extra_version(tmp_path: Path) -> None:
    opened = created(tmp_path)
    skill, new_version = review(tmp_path, "link-check", "  Sudhir  ", opened, T2)
    assert (skill.reviewed_by, skill.reviewed_at, skill.status) == (
        "Sudhir",
        "2026-10-09T10:00:00+00:00",
        "draft",
    )
    assert new_version == version(tmp_path) != opened
    assert history(tmp_path, "link-check") == []  # the procedure did not change
    assert skill.steps == ["`ping` the other end."] and skill.updated_by == "Praveen"


def test_only_a_reviewed_skill_goes_live_and_then_the_agent_uses_it(tmp_path: Path) -> None:
    opened = created(tmp_path)
    with pytest.raises(SkillError, match="has not been reviewed: review it before it goes live"):
        set_status(tmp_path, "link-check", "live", opened)
    assert load_skills(tmp_path, TOOLS).for_agent().skills == {}

    _, reviewed = review(tmp_path, "link-check", "Sudhir", opened, T2)
    skill, live = set_status(tmp_path, "link-check", "live", reviewed)
    assert skill.status == "live"
    assert list(load_skills(tmp_path, TOOLS).for_agent().skills) == ["link-check"]

    off, _ = set_status(tmp_path, "link-check", "off", live)
    assert off.status == "off" and off.reviewed_by == "Sudhir"
    assert load_skills(tmp_path, TOOLS).for_agent().skills == {}


def test_editing_a_live_skill_takes_it_out_of_use_until_reviewed_again(tmp_path: Path) -> None:
    opened = created(tmp_path)
    _, reviewed = review(tmp_path, "link-check", "Sudhir", opened, T2)
    _, live = set_status(tmp_path, "link-check", "live", reviewed)
    skill, _, _ = save(
        tmp_path, SkillSave(skill=form(intro="Changed."), by="Praveen", version=live), TOOLS, T3
    )
    assert (skill.status, skill.reviewed_by, skill.reviewed_at) == ("draft", "", "")
    assert load_skills(tmp_path, TOOLS).for_agent().skills == {}


def test_review_and_status_refuse_a_stale_version_or_a_bad_value(tmp_path: Path) -> None:
    opened = created(tmp_path)
    review(tmp_path, "link-check", "Sudhir", opened, T2)
    with pytest.raises(SkillConflict, match="changed by someone else"):
        review(tmp_path, "link-check", "Other", opened, T3)
    with pytest.raises(SkillConflict, match="changed by someone else"):
        set_status(tmp_path, "link-check", "off", opened)
    with pytest.raises(SkillError, match="must be draft, live or off"):
        set_status(tmp_path, "link-check", "published", version(tmp_path))
    with pytest.raises(SkillError, match="say who reviewed it"):
        review(tmp_path, "link-check", "   ", version(tmp_path), T3)
    with pytest.raises(SkillConflict, match="no skill named 'other' any more"):
        review(tmp_path, "other", "Sudhir", "abc", T3)


def test_a_skill_that_needs_fixing_cannot_be_reviewed_or_set_live(tmp_path: Path) -> None:
    write(tmp_path, "link-check", skill_file("published"))
    broken = version(tmp_path)
    with pytest.raises(SkillError, match="needs fixing in its file first"):
        review(tmp_path, "link-check", "Sudhir", broken, T2)
    with pytest.raises(SkillError, match="needs fixing in its file first"):
        set_status(tmp_path, "link-check", "off", broken)


# ---------- restoring an earlier version ----------


def test_restoring_brings_back_the_old_steps_as_a_draft_and_keeps_the_current_one(
    tmp_path: Path,
) -> None:
    opened = created(tmp_path)
    _, reviewed = review(tmp_path, "link-check", "Sudhir", opened, T2)
    _, live = set_status(tmp_path, "link-check", "live", reviewed)
    _, edited, _ = save(
        tmp_path,
        SkillSave(skill=form(steps=["`get_logs` instead."]), by="Praveen", version=live),
        TOOLS,
        T2,
    )
    first = history(tmp_path, "link-check")[0]
    skill, _ = restore(tmp_path, "link-check", first.id, "Deependra", edited, TOOLS, T3)
    assert skill.steps == ["`ping` the other end."]
    assert (skill.status, skill.reviewed_by, skill.updated_by) == ("draft", "", "Deependra")
    assert [e.saved_by for e in history(tmp_path, "link-check")] == ["Praveen", "Praveen"]


def test_a_version_that_names_a_tool_gone_since_cannot_be_restored(tmp_path: Path) -> None:
    opened = created(tmp_path)
    _, edited, _ = save(
        tmp_path, SkillSave(skill=form(steps=["`get_logs` it."]), by="A", version=opened), TOOLS, T2
    )
    entry = history(tmp_path, "link-check")[0].id
    with pytest.raises(SkillError, match="cannot be used any more: `ping` is not a tool"):
        restore(tmp_path, "link-check", entry, "B", edited, {"get_logs"}, T3)
    with pytest.raises(SkillError, match="is not a version"):
        restore(tmp_path, "link-check", "../SKILL", "B", edited, TOOLS, T3)


# ---------- the API ----------


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from ainops.api import app as module

    async def tools(url: str) -> list[dict[str, Any]]:
        return [{"name": name} for name in TOOLS]

    monkeypatch.setattr(module.settings, "skills_dir", tmp_path / "skills")
    monkeypatch.setattr(module.settings, "logs_dir", tmp_path / "logs")
    monkeypatch.setattr(module, "_list_tools", tools)
    monkeypatch.setattr(module, "registry", RunRegistry(tmp_path / "runs"))
    return module


def audit(api: Any) -> list[tuple[str, str]]:
    from ainops.network.audit import AuditLog

    entries = AuditLog(api.settings.logs_dir / "network-audit.jsonl").tail()
    return [(e["tool"], e["summary"]) for e in entries]


def test_review_status_and_restore_through_the_api_each_audited(api: Any) -> None:
    client = TestClient(api.app)
    v1 = client.post("/api/skills", json={"skill": form().model_dump(), "by": "Praveen"}).json()[
        "version"
    ]
    early = client.post(
        "/api/skills/link-check/status", json={"status": "live", "by": "Praveen", "version": v1}
    )
    assert early.status_code == 422 and "review it before it goes live" in early.json()["detail"]

    reviewed = client.post(
        "/api/skills/link-check/review", json={"reviewer": "Sudhir", "version": v1}
    ).json()
    assert reviewed["reviewed_by"] == "Sudhir" and reviewed["status"] == "draft"
    stale = client.post("/api/skills/link-check/review", json={"reviewer": "X", "version": v1})
    assert stale.status_code == 409

    live = client.post(
        "/api/skills/link-check/status",
        json={"status": "live", "by": "Sudhir", "version": reviewed["version"]},
    ).json()
    assert live["status"] == "live"
    assert [s["status"] for s in client.get("/api/skills").json()["skills"]] == ["live"]

    edited = client.put(
        "/api/skills/link-check",
        json={
            "skill": form(steps=["`get_logs` it."]).model_dump(),
            "by": "Praveen",
            "version": live["version"],
        },
    ).json()
    entry = client.get("/api/skills/link-check/history").json()[0]["id"]
    restored = client.post(
        "/api/skills/link-check/restore",
        json={"entry": entry, "by": "Deependra", "version": edited["version"]},
    ).json()
    assert restored["steps"] == ["`ping` the other end."] and restored["status"] == "draft"

    assert audit(api) == [
        ("create_skill", "skill link-check created by Praveen"),
        ("review_skill", "skill link-check reviewed by Sudhir"),
        ("skill_status", "skill link-check set to live by Sudhir"),
        ("edit_skill", "skill link-check changed by Praveen; it needs a new review"),
        (
            "restore_skill",
            f"skill link-check restored to the version replaced {entry} by Deependra; "
            "it needs a new review",
        ),
    ]


def wait(run: Run) -> None:
    for _ in range(300):  # the reply runs on the test client's own event loop (a thread)
        if run.done:
            return
        time.sleep(0.01)
    raise AssertionError("the reply never finished")


def test_an_investigation_can_be_started_to_try_a_skill_and_its_follow_ups_keep_it(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(api.settings.skills_dir, "link-check", skill_file("draft"))
    tried: list[Any] = []

    async def investigate(
        text: str,
        emit: Any,
        settings: Any,
        earlier: Any = None,
        hints: Any = None,
        trying: Any = None,
    ) -> None:
        tried.append(trying)
        await emit({"type": "started", "question": text, "trying": trying, "at_ms": 0})

    monkeypatch.setattr(api, "investigate", investigate)
    with TestClient(api.app) as client:
        unknown = client.post(
            "/api/investigations", json={"question": "Is the link up?", "try_skill": "nope"}
        )
        assert unknown.status_code == 422 and "no usable skill named 'nope'" in unknown.text
        started = client.post(
            "/api/investigations", json={"question": "Is the link up?", "try_skill": "Link-Check"}
        ).json()
        run = api.registry.runs[started["id"]]
        wait(run)
        client.post(f"/api/runs/{run.id}/messages", json={"text": "And now?"})
        wait(run)
        plain = client.post("/api/investigations", json={"question": "Is the link up?"}).json()
        wait(api.registry.runs[plain["id"]])
    assert tried == ["link-check", "link-check", None]


# ---------- a reply: the agent gets the live skills, and the one being tried ----------


def test_a_reply_offers_live_skills_and_the_one_being_tried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio

    from langchain_core.tools import StructuredTool

    from ainops.agent import runner
    from ainops.agent.report import Report
    from ainops.config import Settings

    library(tmp_path)
    seen: list[str] = []

    async def ping(device: str) -> str:
        return "ok"

    class Client:
        async def get_tools(self, server_name: str) -> list[Any]:
            if server_name != "network":
                return []
            return [StructuredTool.from_function(coroutine=ping, name="ping", description="d")]

    class Agent:
        async def ainvoke(self, state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {"structured_response": Report(outcome="answered", summary="x"), "messages": []}

    def create_agent(model: Any, tools: Any, **kwargs: Any) -> Agent:
        seen.append(kwargs["system_prompt"])
        return Agent()

    monkeypatch.setattr(runner, "mcp_client", lambda settings: Client())
    monkeypatch.setattr(runner, "build_model", lambda settings: None)
    monkeypatch.setattr(runner, "create_agent", create_agent)

    def started(trying: str | None) -> dict[str, Any]:
        events: list[dict[str, Any]] = []

        async def collect(event: dict[str, Any]) -> None:
            events.append(event)

        settings = Settings(skills_dir=tmp_path)
        asyncio.run(runner.investigate("Is the link up?", collect, settings, trying=trying))
        return next(e for e in events if e["type"] == "started")

    plain = started(None)
    assert plain["skills"] == ["live-one"] and plain["trying"] is None
    assert "draft-one" not in seen[-1]
    tried = started("draft-one")
    assert tried["skills"] == ["draft-one", "live-one"] and tried["trying"] == "draft-one"
    assert "to try the skill draft-one" in seen[-1]
