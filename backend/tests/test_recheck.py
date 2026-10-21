"""Check before answering: a root cause that none of its cited checks shows is sent back to the
agent once, by code, to be checked directly. What comes back is verified as usual."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from test_agent_checks import FAULT1_CHECKS

from ainops.agent import runner
from ainops.agent.prompts import RECHECK, SYSTEM_PROMPT
from ainops.agent.report import EvidenceRecord, Report
from ainops.config import Settings

# The 2026-10-21 run on the simulator: fault-1, but the AI blamed CORE-SW-TRV.
WRONG = Report(
    outcome="diagnosed",
    summary="CORE-SW-TRV does not run OSPF on the leased line.",
    root_cause="CORE-SW-TRV is not running OSPF on 10.10.4.0/24 (Fa2/0)",
    root_cause_evidence=["E6", "E10", "E13"],
    affected=["CORE-SW-TRV Fa2/0"],
)
RIGHT = Report(
    outcome="diagnosed",
    summary="The leased line is shut at MAA.",
    root_cause="IPLC-RTR-MAA Fa2/0 is administratively down",
    root_cause_evidence=["E16", "E10"],
    affected=["IPLC-RTR-MAA Fa2/0"],
)
FIRST = {k: v for k, v in FAULT1_CHECKS.items() if k != "E16"}  # before the direct check
RECHECKED = "the checks you cited for it"


class Agent:
    """Plays the LLM: each ainvoke gives the next (checks it made, report it wrote)."""

    def __init__(self, turns: list[tuple[dict[str, EvidenceRecord], Report | None]]) -> None:
        self.turns = turns
        self.inputs: list[list[BaseMessage]] = []
        self.run: runner.Investigation | None = None

    async def ainvoke(self, state: dict[str, Any], config: Any) -> dict[str, Any]:
        assert self.run is not None
        checks, report = self.turns[len(self.inputs)]
        self.inputs.append(list(state["messages"]))
        self.run.evidence.update(checks)
        self.run.tool_calls += len(checks)
        messages = [*state["messages"], AIMessage(f"reply {len(self.inputs)}")]
        return {"messages": messages, **({"structured_response": report} if report else {})}


def _investigate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    agent: Agent,
    calls_before: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    class Client:
        async def get_tools(self, server_name: str) -> list[Any]:
            return []

    def create_agent(model: Any, tools: Any, **kwargs: Any) -> Agent:
        agent.run = kwargs["middleware"][0].run
        agent.run.tool_calls = calls_before
        return agent

    monkeypatch.setattr(runner, "mcp_client", lambda settings: Client())
    monkeypatch.setattr(runner, "build_model", lambda settings: None)
    monkeypatch.setattr(runner, "create_agent", create_agent)
    events: list[dict[str, Any]] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    question = "Users at TRV cannot reach 192.168.200.10 at MAA. Why?"
    final = asyncio.run(runner.investigate(question, collect, Settings(skills_dir=tmp_path)))
    return events, final


def test_a_root_cause_no_check_shows_is_sent_back_once_and_the_checked_answer_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agent = Agent([(FIRST, WRONG), ({"E16": FAULT1_CHECKS["E16"]}, RIGHT)])
    events, final = _investigate(monkeypatch, tmp_path, agent)
    assert len(agent.inputs) == 2
    # The second turn goes on from the whole first one, with the AINOPS check as the last message.
    again = agent.inputs[1]
    assert isinstance(again[-2], AIMessage) and again[-2].content == "reply 1"
    assert isinstance(again[-1], HumanMessage)
    assert again[-1].content == RECHECK.format(blamed="CORE-SW-TRV Fa2/0")
    # Shown in the steps, between the first answer's checks and the report.
    assert [e["type"] for e in events] == ["started", "recheck", "report"]
    assert events[1]["blamed"] == ["CORE-SW-TRV Fa2/0"]
    assert final["report"]["affected"] == ["IPLC-RTR-MAA Fa2/0"]
    assert final["confidence"] == "high"
    assert "E16" in final["evidence"]  # the direct check is kept as evidence


def test_the_same_unshown_answer_again_is_not_sent_back_twice_and_is_low(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agent = Agent([(FIRST, WRONG), ({}, WRONG)])
    events, final = _investigate(monkeypatch, tmp_path, agent)
    assert len(agent.inputs) == 2
    assert [e["type"] for e in events].count("recheck") == 1
    assert final["confidence"] == "low"
    assert final["confidence_reasons"][-1].startswith("nothing cited for the root cause shows")


def test_a_shown_root_cause_is_answered_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agent = Agent([(FAULT1_CHECKS, RIGHT)])
    events, final = _investigate(monkeypatch, tmp_path, agent)
    assert len(agent.inputs) == 1
    assert "recheck" not in [e["type"] for e in events]
    assert final["confidence"] == "high"


def test_with_the_tool_budget_used_up_it_is_not_sent_back_but_low(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agent = Agent([(FIRST, WRONG)])
    _, final = _investigate(monkeypatch, tmp_path, agent, calls_before=runner.MAX_TOOL_CALLS)
    assert len(agent.inputs) == 1
    assert final["confidence"] == "low"


def test_no_report_after_the_check_keeps_the_first_one_at_low(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agent = Agent([(FIRST, WRONG), ({}, None)])
    _, final = _investigate(monkeypatch, tmp_path, agent)
    assert final["report"]["affected"] == ["CORE-SW-TRV Fa2/0"]
    assert final["confidence"] == "low"


@pytest.mark.parametrize(
    "report",
    [
        Report(
            outcome="inconclusive",
            summary="x",
            root_cause_evidence=["E6"],
            affected=["CORE-SW-TRV Fa2/0"],
        ),
        Report(outcome="diagnosed", summary="x", root_cause="y", root_cause_evidence=["E6"]),
    ],
    ids=["not a diagnosis", "blames nothing"],
)
def test_only_a_diagnosis_that_blames_something_is_sent_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, report: Report
) -> None:
    agent = Agent([(FIRST, report)])
    _investigate(monkeypatch, tmp_path, agent)
    assert len(agent.inputs) == 1


def test_the_agent_is_told_how_to_blame_and_not_to_guess_directions() -> None:
    assert "check of THAT device" in SYSTEM_PROMPT
    assert "get_device_links" in SYSTEM_PROMPT
    assert RECHECKED in RECHECK
