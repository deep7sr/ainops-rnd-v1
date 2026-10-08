"""Saving expert skills from the Skills page (skill_book.py and its API)."""

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from ainops.agent.skills import load_skills, parse_skill
from ainops.skill_book import (
    SkillConflict,
    SkillError,
    SkillForm,
    SkillSave,
    check,
    history,
    old_version,
    read,
    save,
    version_of,
)

TOOLS = {"get_interfaces", "ping", "get_logs", "get_ospf_neighbors"}
T1 = datetime(2026, 10, 9, 9, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 9, 10, 30, 0, 123456, tzinfo=UTC)


def form(**changes: Any) -> SkillForm:
    values: dict[str, Any] = {
        "name": "link-check",
        "description": "Use when one link\n  looks down.",
        "intro": "Check both sides.",
        "steps": [
            "`get_interfaces` on the router:\nthe interface must be up.\n- admin down = shut\n",
            "",  # an empty step is dropped
            "`ping` the other end.",
        ],
    }
    values.update(changes)
    return SkillForm(**values)


def create(base: Path, by: str = "Praveen", **changes: Any) -> tuple[str, str]:
    skill, version, new = save(base, SkillSave(skill=form(**changes), by=by), TOOLS, T1)
    assert new
    return skill.name, version


def meta(base: Path, name: str) -> dict[str, Any]:
    found = read(base, name)
    assert found is not None
    front = found[0].split("---\n")[1]
    loaded = yaml.safe_load(front)
    assert isinstance(loaded, dict)
    return loaded


# ---------- the file it writes ----------


def test_a_new_skill_is_a_skill_md_the_agent_loads(tmp_path: Path) -> None:
    create(tmp_path)
    library = load_skills(tmp_path, TOOLS)
    skill = library.get("link-check")
    assert skill is not None
    assert skill.description == "Use when one link looks down."
    assert skill.intro == "Check both sides."
    assert skill.steps == [
        "`get_interfaces` on the router: the interface must be up.\n- admin down = shut",
        "`ping` the other end.",
    ]
    assert skill.tools == ["get_interfaces", "ping"]
    assert library.problems == []


def test_a_new_skill_records_who_wrote_it_and_is_not_reviewed(tmp_path: Path) -> None:
    create(tmp_path, by="  Praveen   K ")
    assert meta(tmp_path, "link-check")["metadata"] == {
        "author": "Praveen K",
        "reviewed_by": "",
        "reviewed_at": "",
        "status": "draft",
        "updated_by": "Praveen K",
        "updated_at": "2026-10-09T09:00:00+00:00",
    }


def test_the_file_reads_like_one_written_by_hand(tmp_path: Path) -> None:
    create(tmp_path)
    text, _ = read(tmp_path, "link-check") or ("", "")
    assert text.endswith(
        "Check both sides.\n\n"
        "1. `get_interfaces` on the router: the interface must be up.\n"
        "   - admin down = shut\n"
        "2. `ping` the other end.\n"
    )


def test_odd_text_is_kept_exactly(tmp_path: Path) -> None:
    tricky = "Use when: a link is 'down' # or \"flapping\" --- see notes"
    create(tmp_path, description=tricky)
    skill = load_skills(tmp_path, TOOLS).get("link-check")
    assert skill is not None and skill.description == tricky


# ---------- what is never saved ----------


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"name": "Link Check"}, "lowercase letters, digits and hyphens"),
        ({"name": "../outside"}, "lowercase letters, digits and hyphens"),
        ({"description": " "}, "description is missing"),
        ({"description": "x" * 301}, "longer than 300 characters"),
        ({"steps": ["no tools here, just text"] * 13}, "at most 12"),
        ({"steps": ["`get_routez` on the router."]}, "`get_routez` is not a tool"),
        ({"steps": ["`show ip route` on it."]}, "is not a tool"),
        ({"steps": [" ", ""]}, "no numbered steps"),
        ({"intro": "1. starts like a step"}, "intro cannot start with a number"),
        ({"steps": ["x" * 2001]}, "longer than 2,000 characters"),
    ],
)
def test_a_skill_the_agent_could_not_use_is_never_saved(
    tmp_path: Path, changes: dict[str, Any], problem: str
) -> None:
    _, problems, _ = check(form(**changes), TOOLS)
    assert any(problem in p for p in problems), problems
    with pytest.raises(SkillError, match=problem.replace("(", r"\(")):
        save(tmp_path, SkillSave(skill=form(**changes), by="Praveen"), TOOLS, T1)
    assert list(tmp_path.rglob("*")) == []  # nothing written anywhere
    assert not (tmp_path.parent / "outside").exists()


def test_nothing_is_saved_while_tool_names_cannot_be_checked(tmp_path: Path) -> None:
    with pytest.raises(SkillError, match="MCP servers are not running"):
        save(tmp_path, SkillSave(skill=form(), by="Praveen"), None, T1)
    assert list(tmp_path.iterdir()) == []


def test_a_name_made_of_spaces_is_not_a_name(tmp_path: Path) -> None:
    with pytest.raises(SkillError, match="say who you are"):
        save(tmp_path, SkillSave(skill=form(), by="   "), TOOLS, T1)


def test_a_new_skill_cannot_replace_one_that_exists(tmp_path: Path) -> None:
    create(tmp_path, by="Praveen")
    with pytest.raises(SkillConflict, match="already a skill named 'link-check'"):
        save(tmp_path, SkillSave(skill=form(intro="Mine"), by="Someone"), TOOLS, T2)
    assert meta(tmp_path, "link-check")["metadata"]["author"] == "Praveen"
    # A folder without SKILL.md (a broken or half-made skill) is not overwritten either.
    (tmp_path / "half-made").mkdir()
    with pytest.raises(SkillConflict):
        save(tmp_path, SkillSave(skill=form(name="half-made"), by="X"), TOOLS, T2)


# ---------- edits ----------


def test_an_edit_keeps_the_author_needs_a_new_review_and_keeps_the_old_file(
    tmp_path: Path,
) -> None:
    _, version = create(tmp_path, by="Praveen")
    before, _ = read(tmp_path, "link-check") or ("", "")
    # Someone reviews it by hand in the file.
    reviewed = before.replace('reviewed_by: ""', "reviewed_by: Sudhir").replace(
        "reviewed_by: ''", "reviewed_by: Sudhir"
    )
    assert reviewed != before
    (tmp_path / "link-check" / "SKILL.md").write_text(reviewed, encoding="utf-8", newline="\n")
    version = version_of(reviewed)

    skill, new_version, new = save(
        tmp_path,
        SkillSave(skill=form(intro="Both ends."), by="Deependra", version=version),
        TOOLS,
        T2,
    )
    assert not new and skill.intro == "Both ends." and new_version != version
    assert meta(tmp_path, "link-check")["metadata"] == {
        "author": "Praveen",
        "reviewed_by": "",  # changed: needs a new review
        "reviewed_at": "",
        "status": "draft",  # and is not used until it is live again
        "updated_by": "Deependra",
        "updated_at": "2026-10-09T10:30:00+00:00",
    }
    assert [e.model_dump() for e in history(tmp_path, "link-check")] == [
        {
            "id": "20261009T103000123456Z",
            "replaced_at": "2026-10-09T10:30:00+00:00",
            "saved_by": "Praveen",
            "saved_at": "2026-10-09T09:00:00+00:00",
            "reviewed_by": "Sudhir",
        }
    ]
    assert old_version(tmp_path, "link-check", "20261009T103000123456Z") == reviewed


def test_an_edit_over_someone_elses_change_is_refused(tmp_path: Path) -> None:
    _, opened = create(tmp_path)
    save(tmp_path, SkillSave(skill=form(intro="First"), by="A", version=opened), TOOLS, T2)
    after_first = read(tmp_path, "link-check")
    with pytest.raises(SkillConflict, match="changed by someone else"):
        save(tmp_path, SkillSave(skill=form(intro="Second"), by="B", version=opened), TOOLS, T2)
    assert read(tmp_path, "link-check") == after_first
    assert len(history(tmp_path, "link-check")) == 1  # only the first edit made a version


def test_an_edit_of_a_skill_that_is_gone_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SkillConflict, match="no skill named 'link-check' any more"):
        save(tmp_path, SkillSave(skill=form(), by="A", version="abc"), TOOLS, T1)
    assert list(tmp_path.iterdir()) == []


def test_two_saves_at_once_never_lose_one(tmp_path: Path) -> None:
    _, opened = create(tmp_path)
    results: list[str] = []

    def edit(n: int) -> None:
        try:
            save(
                tmp_path,
                SkillSave(skill=form(intro=f"edit {n}"), by=f"E{n}", version=opened),
                TOOLS,
            )
            results.append("saved")
        except SkillConflict:
            results.append("refused")

    threads = [threading.Thread(target=edit, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["refused", "refused", "refused", "saved"]


@pytest.mark.parametrize("entry", ["../SKILL", "20261009T103000123456Z", "latest", ""])
def test_only_real_versions_can_be_read(tmp_path: Path, entry: str) -> None:
    create(tmp_path)
    with pytest.raises(SkillError, match="is not a version"):
        old_version(tmp_path, "link-check", entry)


def test_names_are_checked_before_any_path_is_used(tmp_path: Path) -> None:
    for bad in ["../x", "a/b", "..", "A"]:
        with pytest.raises(SkillError, match="must be lowercase letters"):
            read(tmp_path, bad)
        with pytest.raises(SkillError, match="must be lowercase letters"):
            history(tmp_path, bad)


def test_a_hand_written_skill_has_no_history_and_no_saver(tmp_path: Path) -> None:
    folder = tmp_path / "by-hand"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: by-hand\ndescription: Use by hand.\n---\n1. `ping` it.\n", encoding="utf-8"
    )
    assert history(tmp_path, "by-hand") == []
    skill, _ = parse_skill("by-hand", (folder / "SKILL.md").read_text(encoding="utf-8"), TOOLS)
    assert skill is not None and skill.updated_by == "" and skill.updated_at == ""


# ---------- the API ----------


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from ainops.api import app as module

    async def tools(url: str) -> list[dict[str, Any]]:
        return [{"name": name} for name in TOOLS]

    monkeypatch.setattr(module.settings, "skills_dir", tmp_path / "skills")
    monkeypatch.setattr(module.settings, "logs_dir", tmp_path / "logs")
    monkeypatch.setattr(module, "_list_tools", tools)
    return module


def body(by: str = "Praveen", version: str | None = None, **changes: Any) -> dict[str, Any]:
    return {"skill": form(**changes).model_dump(), "by": by, "version": version}


def audit(api: Any) -> list[dict[str, Any]]:
    from ainops.network.audit import AuditLog

    return AuditLog(api.settings.logs_dir / "network-audit.jsonl").tail()


def test_check_shows_the_skill_and_its_file_without_saving(api: Any) -> None:
    client = TestClient(api.app)
    good = client.post("/api/skills/check", json=form().model_dump()).json()
    assert good["problems"] == [] and good["skill"]["steps"][1] == "`ping` the other end."
    assert good["markdown"].startswith("---\nname: link-check\n")
    assert good["tools_checked"] is True
    bad = client.post("/api/skills/check", json=form(steps=["`nope` it"]).model_dump()).json()
    assert bad["skill"] is None and "`nope` is not a tool" in bad["problems"][0]
    assert not api.settings.skills_dir.exists()


def test_create_edit_and_history_through_the_api_each_audited(api: Any) -> None:
    client = TestClient(api.app)
    created = client.post("/api/skills", json=body())
    assert created.status_code == 201
    version = created.json()["version"]
    listed = client.get("/api/skills").json()["skills"]
    assert [(s["name"], s["version"], s["updated_by"]) for s in listed] == [
        ("link-check", version, "Praveen")
    ]

    edited = client.put("/api/skills/link-check", json=body("Deependra", version, intro="New"))
    assert edited.status_code == 200 and edited.json()["intro"] == "New"
    stale = client.put("/api/skills/link-check", json=body("Other", version, intro="Lost?"))
    assert stale.status_code == 409 and "changed by someone else" in stale.json()["detail"]

    entries = client.get("/api/skills/link-check/history").json()
    assert [e["saved_by"] for e in entries] == ["Praveen"]
    old = client.get(f"/api/skills/link-check/history/{entries[0]['id']}").json()
    assert old["skill"]["intro"] == "Check both sides." and old["problems"] == []

    assert [(e["tool"], e["source"], e["args"], e["summary"]) for e in audit(api)] == [
        ("create_skill", "skills", {"skill": "link-check"}, "skill link-check created by Praveen"),
        (
            "edit_skill",
            "skills",
            {"skill": "link-check"},
            "skill link-check changed by Deependra; it needs a new review",
        ),
    ]


def test_the_api_refuses_what_the_book_refuses(api: Any) -> None:
    client = TestClient(api.app)
    assert client.post("/api/skills", json=body(steps=["`nope` it"])).status_code == 422
    version = client.post("/api/skills", json=body()).json()["version"]
    assert client.post("/api/skills", json=body()).status_code == 409
    assert client.post("/api/skills", json=body(version=version)).status_code == 422
    renamed = client.put("/api/skills/link-check", json=body(version=version, name="other-name"))
    assert renamed.status_code == 422 and "keeps its name" in renamed.json()["detail"]
    assert client.put("/api/skills/link-check", json=body()).status_code == 422  # no version
    assert client.get("/api/skills/..%2Fx/history").status_code == 404
    assert client.get("/api/skills/link-check/history/..%2F..%2Fx").status_code == 404
    assert len(audit(api)) == 1  # only the one create


def test_nothing_is_saved_through_the_api_while_the_mcp_servers_are_down(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(url: str) -> list[dict[str, Any]]:
        raise ConnectionError("down")

    monkeypatch.setattr(api, "_list_tools", down)
    response = TestClient(api.app).post("/api/skills", json=body())
    assert response.status_code == 422 and "not running" in response.json()["detail"]
    assert (
        TestClient(api.app)
        .post("/api/skills/check", json=form().model_dump())
        .json()["tools_checked"]
        is False
    )


def test_a_file_that_would_not_read_back_as_written_is_never_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last guard: whatever the form held must come back from the file unchanged."""
    import ainops.skill_book as book

    real = book.render

    def loses_a_step(form: SkillForm, metadata: dict[str, str]) -> str:
        return real(form.model_copy(update={"steps": form.steps[:1]}), metadata)

    monkeypatch.setattr(book, "render", loses_a_step)
    _, problems, _ = check(form(), TOOLS)
    assert problems == ["the intro or a step would not read back as written: reword its start"]
    with pytest.raises(SkillError, match="would not read back"):
        save(tmp_path, SkillSave(skill=form(), by="Praveen"), TOOLS, T1)
    assert list(tmp_path.iterdir()) == []
