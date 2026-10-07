"""Expert skills: loading and checking SKILL.md files, and the agent opening and following one."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import ToolCall, ToolMessage
from langchain_core.tools import StructuredTool

from ainops.agent import skills
from ainops.agent.runner import (
    MAX_SKILL_LOADS,
    USE_SKILL,
    AinopsMiddleware,
    Investigation,
    skill_tool,
    with_reason,
)
from ainops.agent.skills import instructions, load_skills, parse_skill
from ainops.config import REPO_ROOT

TOOLS = {"trace_route", "get_interfaces", "get_ospf_neighbors", "ping"}

GOOD = """---
name: link-check
description: Use when one link looks down.
metadata:
  author: Praveen
  reviewed_by: Praveen
---
Check the link from both sides.

1. `get_interfaces` on the router, and look at
   the interface towards the other end.
   - Admin down means shut.
2. `ping` the other end, then `get_interfaces` again.
"""


def _parse(text: str, folder: str = "link-check", tools: set[str] | None = TOOLS) -> Any:
    return parse_skill(folder, text, tools)


# ---------- reading a skill ----------


def test_a_good_skill_is_read_into_steps_and_tools() -> None:
    skill, problems = _parse(GOOD)
    assert problems == []
    assert skill.name == "link-check"
    assert skill.intro == "Check the link from both sides."
    assert skill.steps == [
        # a wrapped line goes on with the sentence; "- " starts a sub-point on its own line
        "`get_interfaces` on the router, and look at the interface towards the other end."
        "\n- Admin down means shut.",
        "`ping` the other end, then `get_interfaces` again.",
    ]
    assert skill.tools == ["get_interfaces", "ping"]
    assert (skill.author, skill.reviewed_by) == ("Praveen", "Praveen")


def test_a_skill_without_a_reviewer_is_a_draft() -> None:
    skill, _ = _parse(GOOD.replace("  reviewed_by: Praveen\n", ""))
    assert skill.reviewed_by == ""


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda t: t.replace("---\nname", "name", 1), "must start with a --- block"),
        (lambda t: t.replace("---\nCheck", "Check"), "not closed"),
        (lambda t: t.replace("name: link-check", "name: [oops"), "not valid YAML"),
        (lambda t: t.replace("name: link-check", "name: Link_Check"), "lowercase letters"),
        (lambda t: t.replace("name: link-check", "name: other-name"), "same as its folder"),
        (lambda t: t.replace("description: Use when one link looks down.", ""), "missing"),
        (lambda t: t.replace("one link", "x" * 300), "longer than 300"),
        (lambda t: t.replace("1. ", "- ").replace("2. ", "- "), "no numbered steps"),
        (lambda t: t.replace("2. `ping`", "3. `ping`"), "should be numbered 2"),
        (lambda t: t + "Unindented note.\n", "indent it"),
        (lambda t: t.replace("`ping`", "`get_routes`"), "`get_routes` is not a tool"),
        (lambda t: t.replace("`ping`", "`show ip route`"), "`show ip route` is not a tool"),
    ],
)
def test_each_rule_is_explained_when_broken(change: Any, problem: str) -> None:
    skill, problems = _parse(change(GOOD))
    assert skill is None
    assert any(problem in p for p in problems), problems


def test_too_many_steps() -> None:
    steps = "".join(f"{n}. `ping` again.\n" for n in range(1, skills.MAX_STEPS + 2))
    skill, problems = _parse(GOOD.split("Check the link")[0] + steps)
    assert skill is None
    assert any("at most 12" in p for p in problems)


def test_without_the_tool_list_only_the_format_is_checked() -> None:
    unknown_tool = GOOD.replace("`ping`", "`get_routes`")
    assert _parse(unknown_tool, tools=None)[1] == []
    assert _parse(GOOD.replace("`ping`", "`show ip route`"), tools=None)[0] is None


# ---------- the skills folder ----------


def _write(root: Path, folder: str, text: str) -> None:
    (root / folder).mkdir(parents=True)
    (root / folder / "SKILL.md").write_text(text, encoding="utf-8")


def test_a_broken_skill_is_left_out_and_listed_the_others_still_load(tmp_path: Path) -> None:
    _write(tmp_path, "link-check", GOOD)
    _write(tmp_path, "broken", GOOD.replace("name: link-check", "name: broken").replace("1. ", ""))
    (tmp_path / "notes").mkdir()  # a folder without SKILL.md is not a skill
    library = load_skills(tmp_path, TOOLS)
    assert list(library.skills) == ["link-check"]
    assert [p.folder for p in library.problems] == ["broken"]


def test_no_skills_folder_means_no_skills(tmp_path: Path) -> None:
    library = load_skills(tmp_path / "missing", TOOLS)
    assert library.skills == {}
    assert library.prompt_section() == ""


def test_the_agent_sees_names_and_descriptions_never_the_steps(tmp_path: Path) -> None:
    _write(tmp_path, "link-check", GOOD)
    section = load_skills(tmp_path, TOOLS).prompt_section()
    assert "- link-check: Use when one link looks down." in section
    assert "use_skill" in section
    assert "Admin down means shut" not in section


def test_use_skill_gives_the_numbered_steps() -> None:
    skill, _ = _parse(GOOD)
    text = instructions(skill)
    assert "1. `get_interfaces` on the router, and look at the interface" in text
    assert "2. `ping` the other end" in text


def test_the_skills_in_the_repo_load_against_the_real_tools() -> None:
    from ainops.network import server as network
    from ainops.topology import server as topology

    tools = {t.name for t in asyncio.run(network.mcp.list_tools())}
    tools |= {t.name for t in asyncio.run(topology.mcp.list_tools())}
    library = load_skills(REPO_ROOT / "skills", tools)
    assert library.problems == []
    assert {"site-to-site-unreachable", "leased-line-health", "ospf-neighbour-down"} <= set(
        library.skills
    )
    assert library.skills["site-to-site-unreachable"].tools[0] == "trace_route"


# ---------- the agent opening and following a skill ----------


def _run(tmp_path: Path, events: list[dict[str, Any]]) -> Investigation:
    _write(tmp_path, "link-check", GOOD)

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    servers = {t: "network" for t in TOOLS} | {USE_SKILL: "agent"}
    return Investigation(
        question="Is the link up?",
        emit=collect,
        tool_servers=servers,
        skills=load_skills(tmp_path, TOOLS),
    )


def _call(run: Investigation, name: str, args: dict[str, Any], sent: list[Any]) -> Any:
    call = ToolCall(name=name, args={**args, "reason": "because"}, id=f"c{len(sent)}")
    request = ToolCallRequest(tool_call=call, tool=None, state={}, runtime=None)  # type: ignore[arg-type]

    async def handler(req: ToolCallRequest) -> ToolMessage:
        sent.append(req.tool_call["args"])
        payload = {"device": "R1", "summary": "ok", "data": [], "evidence": {"source": "replay"}}
        return ToolMessage(content=json.dumps(payload), tool_call_id=call["id"], name=name)

    return asyncio.run(AinopsMiddleware(run).awrap_tool_call(request, handler))


def test_opening_a_skill_shows_it_and_does_not_use_the_tool_budget(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    sent: list[Any] = []
    run = _run(tmp_path, events)
    message = _call(run, USE_SKILL, {"skill": "link-check"}, sent)
    assert sent == []  # handled by AINOPS, never sent to an MCP server
    assert "1. `get_interfaces` on the router, and" in message.content
    assert events[-1]["type"] == "skill"
    assert events[-1]["name"] == "link-check"
    assert events[-1]["steps"][1].startswith("`ping`")
    assert events[-1]["why"] == "because"
    assert run.tool_calls == 0
    assert run.skills_used == ["link-check"]

    _call(run, "get_interfaces", {"device": "R1", "skill_step": 1}, sent)
    assert events[-1]["id"] == "E1"  # the skill took no evidence id


def test_each_check_carries_its_skill_step_which_never_reaches_mcp(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    sent: list[Any] = []
    run = _run(tmp_path, events)
    _call(run, "get_interfaces", {"device": "R1", "skill_step": 1}, sent)
    assert events[0]["skill_step"] is None  # no skill open yet

    # link-check: step 1 names get_interfaces; step 2 names ping and get_interfaces.
    _call(run, USE_SKILL, {"skill": "link-check"}, sent)
    for tool, given, expected in [
        ("get_interfaces", None, 1),  # not tagged: the first step naming it
        ("ping", 0, 2),  # "0" is treated like no tag: ping is step 2
        ("get_interfaces", None, 2),  # from the current step on, step 2 names it too
        ("get_interfaces", 1, 1),  # a tag that fits the tool is used: back to step 1
        ("ping", "1", 2),  # a tag that does not fit the tool (step 1 has no ping) is not
        ("ping", 9, 2),  # no step 9
        ("ping", True, 2),
        ("ping", "x", 2),
        ("trace_route", None, 0),  # no step names it: beyond the skill
        ("trace_route", 2, 0),  # even when the model says step 2
    ]:
        args = {"device": "R1", "destination": "10.0.0.1", "skill_step": given}
        _call(run, tool, args, sent)
        call_event = [e for e in events if e["type"] in ("tool_call", "refused")][-1]
        assert call_event["skill_step"] == expected, (tool, given)
    assert all("skill_step" not in args for args in sent)
    assert all("reason" not in args for args in sent)


def test_a_step_named_only_earlier_is_a_re_check_of_that_step(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    run = _run(tmp_path, events)
    _call(run, USE_SKILL, {"skill": "link-check"}, [])
    run.current_step = 2
    skill = run.active_skill
    assert skill is not None
    run.active_skill = skill.model_copy(update={"steps": ["`ping` it.", "`get_interfaces`."]})
    assert run.step_of(None, "ping") == 1


def test_the_real_run_of_10_07_gets_its_steps_back() -> None:
    """inv-6d798971: the model tagged only its first check; the rest arrived without a step."""
    from ainops.network import server as network
    from ainops.topology import server as topology

    tools = {t.name for t in asyncio.run(network.mcp.list_tools())}
    tools |= {t.name for t in asyncio.run(topology.mcp.list_tools())}
    library = load_skills(REPO_ROOT / "skills", tools)
    run = Investigation(question="?", emit=lambda e: None, tool_servers={}, skills=library)  # type: ignore[arg-type, return-value]
    run.active_skill = library.get("leased-line-health")
    calls = [
        ("get_device_links", 1),
        ("get_interfaces", 0),
        ("get_interfaces", 0),
        ("get_interface_detail", 0),
        ("get_interface_detail", 0),
        ("get_ospf_neighbors", 0),
        ("get_ospf_neighbors", 0),
        ("ping", 0),
    ]
    assert [run.step_of(given, tool) for tool, given in calls] == [1, 2, 2, 3, 3, 4, 4, 5]


def test_an_unknown_skill_is_refused_and_named(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    run = _run(tmp_path, events)
    message = _call(run, USE_SKILL, {"skill": "no-such-skill"}, [])
    assert message.status == "error"
    assert "no skill 'no-such-skill' (skills: link-check)" in message.content
    assert events[-1]["type"] == "refused"
    assert run.active_skill is None


def test_skills_can_be_opened_only_a_few_times(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    run = _run(tmp_path, events)
    for _ in range(MAX_SKILL_LOADS):
        assert _call(run, USE_SKILL, {"skill": "link-check"}, []).status != "error"
    message = _call(run, USE_SKILL, {"skill": "link-check"}, [])
    assert message.status == "error"
    assert f"at most {MAX_SKILL_LOADS} skills" in message.content


def test_skill_step_is_offered_only_when_there_are_skills() -> None:
    schema = {"type": "object", "properties": {"device": {"type": "string"}}, "required": []}
    tool = StructuredTool(name="get_interfaces", description="d", args_schema=schema)
    with_step = with_reason(tool, skill_step=True).args_schema
    without = with_reason(tool).args_schema
    assert isinstance(with_step, dict) and isinstance(without, dict)
    assert with_step["properties"]["skill_step"]["type"] == "integer"
    assert "skill_step" not in with_step["required"]
    assert "skill_step" not in without["properties"]


def test_the_use_skill_tool_asks_only_for_a_name(tmp_path: Path) -> None:
    _write(tmp_path, "link-check", GOOD)
    tool = skill_tool(load_skills(tmp_path, TOOLS))
    assert tool.name == USE_SKILL
    assert isinstance(tool.args_schema, dict)
    assert tool.args_schema["required"] == ["skill"]


# ---------- the Skills page API ----------


def test_the_skills_api_checks_tools_when_the_mcp_servers_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ainops.api import app as api

    _write(tmp_path, "link-check", GOOD)
    missing_tool = GOOD.replace("link-check", "uses-a-missing-tool")
    missing_tool = missing_tool.replace("`ping`", "`get_routes`")
    _write(tmp_path, "uses-a-missing-tool", missing_tool)

    async def tools(url: str) -> list[dict[str, Any]]:
        return [{"name": name} for name in TOOLS]

    monkeypatch.setattr(api.settings, "skills_dir", tmp_path)
    monkeypatch.setattr(api, "_list_tools", tools)
    body = TestClient(api.app).get("/api/skills").json()
    assert [s["name"] for s in body["skills"]] == ["link-check"]
    assert body["problems"][0]["folder"] == "uses-a-missing-tool"
    assert body["tools_checked"] is True


def test_the_skills_api_says_when_tools_could_not_be_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ainops.api import app as api

    _write(tmp_path, "link-check", GOOD)

    async def down(url: str) -> list[dict[str, Any]]:
        raise ConnectionError("MCP server not running")

    monkeypatch.setattr(api.settings, "skills_dir", tmp_path)
    monkeypatch.setattr(api, "_list_tools", down)
    body = TestClient(api.app).get("/api/skills").json()
    assert [s["name"] for s in body["skills"]] == ["link-check"]
    assert body["tools_checked"] is False


def test_a_tool_named_twice_is_reported_once() -> None:
    skill, problems = _parse(GOOD.replace("`get_interfaces`", "`get_routez`"))
    assert skill is None
    assert problems == [
        "`get_routez` is not a tool: backticks are only for tool names (see the MCP tools page)"
    ]


def test_opening_a_skill_starts_at_its_first_step(tmp_path: Path) -> None:
    run = _run(tmp_path, [])
    _call(run, USE_SKILL, {"skill": "link-check"}, [])
    run.current_step = 2
    _call(run, USE_SKILL, {"skill": "link-check"}, [])
    assert run.step_of(None, "get_interfaces") == 1
