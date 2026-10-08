"""Talking to AINOPS about an investigation: follow-up messages, Stop, and what each reply sees.

Turn 1 in these tests is a real investigation recorded on the live lab (fault 1, 5 Oct 2026).
"""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage

from ainops.agent import runner
from ainops.agent.conversation import (
    MAX_MESSAGES,
    earlier_of,
    message_count,
    recap,
    turns_of,
)
from ainops.agent.report import EvidenceRecord, Report, verify
from ainops.agent.runner import AinopsMiddleware, Investigation
from ainops.api.runs import Refused, Run, RunRegistry
from ainops.config import REPO_ROOT, Settings

RECORDED = json.loads(
    (REPO_ROOT / "fixtures" / "runs" / "fault1-leased-line-shut-run1.json").read_text("utf-8")
)
QUESTION = "Users at TRV (192.168.100.0/24) cannot reach 192.168.200.10 at MAA. Why?"
STARTED = "2026-10-05T15:29:13+00:00"


def _turn_one() -> list[dict[str, Any]]:
    return [dict(e) for e in RECORDED["events"]]


def _follow_up(text: str, turn: int = 2, at: str = "2026-10-05T15:40:00+00:00") -> dict[str, Any]:
    return {"type": "message", "turn": turn, "text": text, "at": at}


# ---------- rebuilding the conversation from the saved events ----------


def test_a_single_investigation_is_a_conversation_of_one_turn() -> None:
    turns = turns_of(_turn_one(), "title", STARTED)
    assert len(turns) == 1
    assert turns[0].message == QUESTION
    assert turns[0].ended == "report"
    assert [r.id for r in turns[0].evidence] == ["E1", "E2", "E3", "E4", "E5", "E6"]
    # Each check keeps the time it ran: the turn's start plus its offset (E6 at 54.6 s).
    assert turns[0].evidence[5].at == datetime(2026, 10, 5, 15, 30, 7, 594000, tzinfo=UTC)


def test_each_message_starts_a_turn_and_keeps_its_own_ending() -> None:
    events = [
        *_turn_one(),
        _follow_up("Fa2/0 is up, I checked. Look at OSPF."),
        {"type": "stopped", "message": "Stopped by the engineer."},
        _follow_up("Check OSPF on IPLC-RTR-TRV", turn=3, at="2026-10-05T15:45:00+00:00"),
        {"type": "error", "message": "APIStatusError: 413"},
    ]
    turns = turns_of(events, "title", STARTED)
    assert [(t.number, t.ended) for t in turns] == [(1, "report"), (2, "stopped"), (3, "error")]
    assert turns[1].message == "Fa2/0 is up, I checked. Look at OSPF."
    assert turns[2].error == "APIStatusError: 413"
    assert message_count(events) == 3


def test_the_recap_holds_the_report_and_the_checks_but_not_the_raw_output() -> None:
    text = recap(turns_of(_turn_one(), "title", STARTED)[0])
    assert "Outcome: diagnosed (confidence medium)" in text
    assert "Root cause: The leased" in text and "[E6]" in text
    assert (
        "[E6] 15:30 get_interfaces IPLC-RTR-MAA: 3 interfaces; with an address but not up" in text
    )
    # The raw device data (interface tables) is not sent again: only the one-line summaries.
    raw = next(e for e in RECORDED["events"] if e["type"] == "tool_result" and e["id"] == "E6")
    assert json.dumps(raw["data"])[:60] not in text
    assert len(text) < 3000


def test_a_stopped_or_failed_turn_says_so_in_the_recap() -> None:
    events = [*_turn_one(), _follow_up("Look at OSPF"), {"type": "stopped", "message": "x"}]
    assert "stopped me before I finished" in recap(turns_of(events, "t", STARTED)[1])


def test_the_llm_gets_each_message_with_the_reply_in_order() -> None:
    events = [*_turn_one(), _follow_up("Why Fa2/0?"), {"type": "stopped", "message": "x"}]
    messages = earlier_of(events, "t", STARTED).messages()
    assert [type(m) for m in messages] == [HumanMessage, AIMessage, HumanMessage, AIMessage]
    assert messages[0].content == QUESTION
    assert messages[2].content == "Why Fa2/0?"


def test_evidence_and_seen_addresses_carry_over() -> None:
    events = [*_turn_one(), _follow_up("Is 10.10.4.2 the far end?")]
    earlier = earlier_of(events, "t", STARTED)
    assert sorted(earlier.evidence) == ["E1", "E2", "E3", "E4", "E5", "E6"]
    assert earlier.next_evidence == 7
    assert earlier.next_turn == 3
    assert {"192.168.200.10", "10.10.4.2"} <= earlier.known_ips  # question, results, messages
    assert "172.16.99.1" not in earlier.known_ips


def test_a_check_stopped_half_way_keeps_its_id() -> None:
    events = [
        *_turn_one(),
        _follow_up("Look at OSPF"),
        {"type": "tool_call", "id": "E7", "tool": "get_ospf_neighbors", "args": {}, "at_ms": 10},
        {"type": "stopped", "message": "Stopped by the engineer."},
    ]
    # E7 has no result, so it is not evidence, but the next check must be E8, not a second E7.
    earlier = earlier_of(events, "t", STARTED)
    assert "E7" not in earlier.evidence
    assert earlier.next_evidence == 8


def test_old_runs_without_a_started_event_use_the_title() -> None:
    assert turns_of([], "Is the line up?", STARTED)[0].message == "Is the line up?"


# ---------- confidence when the evidence is old ----------

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _evidence(minutes_ago: int) -> dict[str, EvidenceRecord]:
    at = NOW - timedelta(minutes=minutes_ago)
    return {
        "E1": EvidenceRecord("E1", "get_interfaces", "IPLC-RTR-MAA", "", "live", True, at),
        "E2": EvidenceRecord("E2", "get_ospf_neighbors", "IPLC-RTR-TRV", "", "live", True, at),
    }


def _diagnosis() -> Report:
    return Report(
        outcome="diagnosed", summary="x", root_cause="y", root_cause_evidence=["E1", "E2"]
    )


def test_fresh_evidence_keeps_its_confidence() -> None:
    verdict = verify(_diagnosis(), _evidence(minutes_ago=5), now=NOW)
    assert verdict.confidence == "high"
    assert not any("re-check" in r for r in verdict.reasons)


def test_a_root_cause_on_old_checks_is_one_level_lower_and_says_why() -> None:
    verdict = verify(_diagnosis(), _evidence(minutes_ago=20), now=NOW)
    assert verdict.confidence == "medium"
    assert "E1, E2 taken more than 15 minutes ago: re-check suggested" in verdict.reasons


def test_old_checks_do_not_count_for_no_fault_found() -> None:
    report = Report(outcome="no_fault_found", summary="x")
    assert verify(report, _evidence(minutes_ago=5), now=NOW).confidence == "medium"
    old = verify(report, _evidence(minutes_ago=20), now=NOW)
    assert old.confidence == "low"
    assert any("re-check suggested" in r for r in old.reasons)


# ---------- a reply: what the agent gets and how evidence ids go on ----------


def test_evidence_ids_continue_from_the_earlier_turns() -> None:
    async def ignore(event: dict[str, Any]) -> None:
        return None

    run = Investigation(question="Why?", emit=ignore, tool_servers={"get_interfaces": "network"})
    run.next_evidence = 7
    call = ToolCall(name="get_interfaces", args={"device": "R1", "reason": "x"}, id="c1")
    request = ToolCallRequest(tool_call=call, tool=None, state={}, runtime=None)  # type: ignore[arg-type]

    async def handler(req: ToolCallRequest) -> ToolMessage:
        payload = {"device": "R1", "summary": "ok", "data": [], "evidence": {"source": "live"}}
        return ToolMessage(content=json.dumps(payload), tool_call_id="c1", name="get_interfaces")

    message = asyncio.run(AinopsMiddleware(run).awrap_tool_call(request, handler))
    assert isinstance(message, ToolMessage)
    assert str(message.content).startswith("[E7] ")
    assert run.evidence["E7"].at is not None  # the time it ran, for the old-evidence rule
    assert run.next_evidence == 8


def _fake_agent(monkeypatch: pytest.MonkeyPatch, report: Report) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    class Client:
        async def get_tools(self, server_name: str) -> list[Any]:
            return []

    class Agent:
        async def ainvoke(self, state: dict[str, Any], config: Any) -> dict[str, Any]:
            seen["messages"] = state["messages"]
            return {"structured_response": report, "messages": []}

    def create_agent(model: Any, tools: Any, **kwargs: Any) -> Agent:
        seen["prompt"] = kwargs["system_prompt"]
        seen["run"] = kwargs["middleware"][0].run  # the Investigation the checks run in
        return Agent()

    monkeypatch.setattr(runner, "mcp_client", lambda settings: Client())
    monkeypatch.setattr(runner, "build_model", lambda settings: None)
    monkeypatch.setattr(runner, "create_agent", create_agent)
    return seen


def test_a_follow_up_reply_gets_the_conversation_and_may_cite_earlier_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = Report(
        outcome="diagnosed", summary="Still Fa2/0.", root_cause="Fa2/0", root_cause_evidence=["E6"]
    )
    seen = _fake_agent(monkeypatch, report)
    events: list[dict[str, Any]] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    earlier = earlier_of(_turn_one(), "t", STARTED)
    final = asyncio.run(
        runner.investigate("Why Fa2/0?", collect, Settings(skills_dir=tmp_path), earlier)
    )
    assert events[0]["type"] == "started" and events[0]["turn"] == 2
    assert [m.content for m in seen["messages"]][::2] == [QUESTION, "Why Fa2/0?"]
    assert "Conversation: this is a follow-up" in seen["prompt"]
    run: Investigation = seen["run"]
    assert run.next_evidence == 7  # the next check of this reply is E7
    assert "192.168.200.10" in run.known_ips  # seen in turn 1: may be pinged now
    assert "only READ the network" in seen["prompt"]  # the safety rules are still there
    # E6 is from turn 1 (two days old here): valid to cite, so it stays, but it is old.
    assert final["report"]["root_cause_evidence"] == ["E6"]
    assert final["confidence"] == "low"
    assert any("re-check suggested" in r for r in final["confidence_reasons"])


def test_a_first_question_has_no_conversation_part(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _fake_agent(monkeypatch, Report(outcome="answered", summary="Hello."))

    async def ignore(event: dict[str, Any]) -> None:
        return None

    asyncio.run(runner.investigate("Hello", ignore, Settings(skills_dir=tmp_path)))
    assert "Conversation:" not in seen["prompt"]
    assert [m.content for m in seen["messages"]] == ["Hello"]


# ---------- the run registry: one turn at a time, a message limit, Stop ----------


def _saved_run(registry: RunRegistry, events: list[dict[str, Any]]) -> Run:
    run = Run("inv-test0001", "investigation", QUESTION, STARTED, events, True)
    registry.runs[run.id] = run
    return run


async def _until_done(run: Run) -> None:
    for _ in range(200):
        if run.done:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the turn never finished")


def test_a_follow_up_starts_the_next_turn_and_is_saved(tmp_path: Path) -> None:
    async def scenario() -> Run:
        registry = RunRegistry(tmp_path)
        run = _saved_run(registry, _turn_one())

        async def reply(current: Run) -> None:
            await current.emit(
                {
                    "type": "report",
                    "report": {"outcome": "answered"},
                    "confidence": "high",
                    "at_ms": 5,
                }
            )

        assert await registry.follow_up(run.id, "Why Fa2/0?", reply) == 2
        assert run.events[-1]["type"] == "message" and run.events[-1]["turn"] == 2
        await _until_done(run)
        return run

    run = asyncio.run(scenario())
    assert run.events[-1]["type"] == "report"
    saved = json.loads((tmp_path / f"{run.id}.json").read_text("utf-8"))
    assert [e["type"] for e in saved["events"]][-2:] == ["message", "report"]
    assert run.summary()["messages"] == 2


def test_no_message_while_ainops_is_still_working(tmp_path: Path) -> None:
    async def scenario() -> None:
        registry = RunRegistry(tmp_path)
        run = _saved_run(registry, _turn_one())
        release = asyncio.Event()

        async def slow(current: Run) -> None:
            await release.wait()

        await registry.follow_up(run.id, "first", slow)
        with pytest.raises(Refused, match="still working"):
            await registry.follow_up(run.id, "second", slow)
        assert message_count(run.events) == 2  # the second message was not added
        release.set()
        await _until_done(run)

    asyncio.run(scenario())


def test_a_conversation_has_a_message_limit(tmp_path: Path) -> None:
    async def scenario() -> None:
        registry = RunRegistry(tmp_path)
        events = _turn_one() + [_follow_up(f"m{n}", n) for n in range(2, MAX_MESSAGES + 1)]
        run = _saved_run(registry, events)

        async def reply(current: Run) -> None:
            return None

        with pytest.raises(Refused, match=f"reached {MAX_MESSAGES} messages"):
            await registry.follow_up(run.id, "one more", reply)

    asyncio.run(scenario())


def test_only_an_investigation_takes_messages(tmp_path: Path) -> None:
    async def scenario() -> None:
        registry = RunRegistry(tmp_path)
        registry.runs["dis-1"] = Run("dis-1", "discovery", "Discovery", STARTED, [], True)

        async def reply(current: Run) -> None:
            return None

        with pytest.raises(Refused):
            await registry.follow_up("dis-1", "hi", reply)
        with pytest.raises(Refused):
            registry.stop("dis-1")
        with pytest.raises(KeyError):
            await registry.follow_up("inv-unknown", "hi", reply)

    asyncio.run(scenario())


def test_stop_ends_the_turn_and_the_conversation_can_go_on(tmp_path: Path) -> None:
    async def scenario() -> Run:
        registry = RunRegistry(tmp_path)
        run = _saved_run(registry, _turn_one())
        started = asyncio.Event()

        async def endless(current: Run) -> None:
            started.set()
            await asyncio.Event().wait()

        await registry.follow_up(run.id, "Look at OSPF", endless)
        await started.wait()
        registry.stop(run.id)
        await _until_done(run)
        assert run.events[-1] == {"type": "stopped", "message": "Stopped by the engineer."}
        with pytest.raises(Refused, match="nothing is running"):
            registry.stop(run.id)

        async def reply(current: Run) -> None:
            return None

        assert await registry.follow_up(run.id, "Then check the interfaces", reply) == 3
        await _until_done(run)
        return run

    run = asyncio.run(scenario())
    assert run.summary()["messages"] == 3


def test_history_shows_how_the_latest_turn_ended(tmp_path: Path) -> None:
    run = Run("inv-1", "investigation", QUESTION, STARTED, _turn_one(), True)
    assert run.summary()["outcome"] == "diagnosed"
    run.events += [_follow_up("Look at OSPF"), {"type": "stopped", "message": "x"}]
    summary = run.summary()
    assert summary["outcome"] == "stopped"  # not turn 1's diagnosis
    assert summary["confidence"] is None
    assert summary["messages"] == 2


def test_a_viewer_that_reconnects_gets_only_what_it_missed() -> None:
    async def lines(after: int) -> list[str]:
        run = Run("inv-1", "investigation", "q", STARTED, _turn_one()[:3], True)
        return [chunk async for chunk in run.stream(after)]

    everything = asyncio.run(lines(0))
    assert everything[0].startswith("id: 1\ndata: ")
    assert asyncio.run(lines(2))[0].startswith("id: 3\ndata: ")
    assert asyncio.run(lines(3)) == ['data: {"type": "end"}\n\n']


# ---------- the API ----------


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from ainops.api import app as module

    monkeypatch.setattr(module, "registry", RunRegistry(tmp_path))
    return module


def test_the_api_passes_the_conversation_to_the_reply(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: dict[str, Any] = {}

    async def investigate(
        text: str,
        emit: Any,
        settings: Any,
        earlier: Any = None,
        hints: Any = None,
        trying: Any = None,
    ) -> None:
        received.update(text=text, earlier=earlier, hints=hints)

    monkeypatch.setattr(api, "investigate", investigate)
    run = _saved_run(api.registry, _turn_one())
    with TestClient(api.app) as client:
        answer = client.post("/api/runs/inv-test0001/messages", json={"text": " Why Fa2/0? "})
        assert answer.json() == {"id": "inv-test0001", "turn": 2}
        for _ in range(200):  # the reply runs on the test client's own event loop (a thread)
            if run.done:
                break
            time.sleep(0.01)
    assert received["text"] == "Why Fa2/0?"
    assert sorted(received["earlier"].evidence) == ["E1", "E2", "E3", "E4", "E5", "E6"]
    assert received["earlier"].next_turn == 2  # built before the new message was added
    # Tests never reach Neo4j: the reply goes on without hints, and says why.
    assert received["hints"].cases == []
    assert received["hints"].error == "could not look up past cases: ConnectionError"


def test_the_api_refuses_what_the_conversation_cannot_take(api: Any) -> None:
    run = _saved_run(api.registry, _turn_one())
    client = TestClient(api.app)
    assert client.post("/api/runs/inv-nope/messages", json={"text": "hi"}).status_code == 404
    assert client.post(f"/api/runs/{run.id}/messages", json={"text": "  "}).status_code == 422
    assert client.post(f"/api/runs/{run.id}/stop").status_code == 409
    run.done = False  # a turn is running
    busy = client.post(f"/api/runs/{run.id}/messages", json={"text": "hi"})
    assert busy.status_code == 409
    assert "still working" in busy.json()["detail"]


def test_the_api_stream_skips_the_events_the_viewer_has(api: Any) -> None:
    _saved_run(api.registry, _turn_one())
    client = TestClient(api.app)
    total = len(RECORDED["events"])
    body = client.get("/api/runs/inv-test0001/events", headers={"Last-Event-ID": "4"}).text
    assert body.startswith("id: 5\n")
    assert f"id: {total}\n" in body
    body = client.get(f"/api/runs/inv-test0001/events?after={total}").text
    assert body == 'data: {"type": "end"}\n\n'
