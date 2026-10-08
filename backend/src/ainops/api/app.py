"""The AINOPS API for the web UI (http://127.0.0.1:8000, local only).

It does not talk to devices itself: investigations run the agent (which uses the MCP servers) and
discovery calls the network MCP server. It streams their steps to the browser as Server-Sent
Events, serves the knowledge graph for the map, and shows the MCP tool definitions.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field

from ainops.agent.conversation import earlier_of
from ainops.agent.runner import investigate
from ainops.agent.skills import load_skills
from ainops.api.runs import Refused, Run, RunRegistry
from ainops.case_store import CaseBook, Neo4jCases
from ainops.cases import BY_HAND, Case, CaseError, ReviewRequest, draft_case, follow, review_case
from ainops.config import get_settings
from ainops.inventory import load_inventory
from ainops.network.audit import AuditLog
from ainops.topology.discovery import discover
from ainops.topology.graph import GraphStore

settings = get_settings()
MCP_SERVERS = {
    "network": f"http://127.0.0.1:{settings.mcp_network_port}/mcp",
    "topology": f"http://127.0.0.1:{settings.mcp_topology_port}/mcp",
}
registry = RunRegistry(settings.logs_dir / "investigations")
_store: GraphStore | None = None


def store() -> GraphStore:
    global _store
    if _store is None:
        _store = GraphStore(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password.get_secret_value()
        )
    return _store


def cases() -> CaseBook:
    return Neo4jCases(store().driver)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    if _store is not None:
        _store.close()


app = FastAPI(title="AINOPS API", lifespan=lifespan, docs_url="/api/docs")


def _sse(run: Run, after: int = 0) -> StreamingResponse:
    return StreamingResponse(
        run.stream(after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _list_tools(url: str) -> list[dict[str, Any]]:
    async with (
        streamablehttp_client(url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        return [tool.model_dump(exclude_none=True) for tool in result.tools]


# ---------- status ----------


@app.get("/api/health")
async def health() -> dict[str, Any]:
    status: dict[str, Any] = {
        "executor": "live",
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_configured": settings.llm_configured,
    }
    for name, url in MCP_SERVERS.items():
        try:
            tools = await _list_tools(url)
            status[f"mcp_{name}"] = {"ok": True, "tools": len(tools)}
        except Exception as error:  # noqa: BLE001 - reported as a status, not raised
            status[f"mcp_{name}"] = {"ok": False, "error": type(error).__name__}
    try:
        last = store().last_discovery()
        status["graph"] = {"ok": True, "last_discovery": last["at"] if last else None}
    except Exception as error:  # noqa: BLE001
        status["graph"] = {"ok": False, "error": type(error).__name__}
    return status


# ---------- MCP tools (definitions, and calling one by hand like the MCP Inspector) ----------


@app.get("/api/tools")
async def tools() -> dict[str, Any]:
    servers = {}
    for name, url in MCP_SERVERS.items():
        try:
            servers[name] = {"url": url, "ok": True, "tools": await _list_tools(url)}
        except Exception as error:  # noqa: BLE001
            servers[name] = {"url": url, "ok": False, "error": type(error).__name__, "tools": []}
    return {"servers": servers}


class ToolCall(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


@app.post("/api/tools/{server}/{tool}")
async def call_tool(server: str, tool: str, call: ToolCall) -> dict[str, Any]:
    url = MCP_SERVERS.get(server)
    if url is None:
        raise HTTPException(404, f"unknown MCP server '{server}'")
    async with (
        streamablehttp_client(url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, call.arguments)
    text = "\n".join(getattr(block, "text", "") for block in result.content)
    return {"is_error": result.isError, "structured": result.structuredContent, "text": text}


# ---------- expert skills ----------


@app.get("/api/skills")
async def skills() -> dict[str, Any]:
    """The skills the agent can use, and the ones left out with their problems.

    Tool names are checked against the running MCP servers; if one is down they cannot be checked
    (tools_checked is false) and only the format is.
    """
    known: set[str] | None = set()
    for url in MCP_SERVERS.values():
        try:
            known = (known or set()) | {t["name"] for t in await _list_tools(url)}
        except Exception:  # noqa: BLE001 - reported as tools_checked=false
            known = None
            break
    library = load_skills(settings.skills_dir, known)
    return {
        "skills": [s.model_dump() for s in library.skills.values()],
        "problems": [p.model_dump() for p in library.problems],
        "tools_checked": library.tools_checked,
    }


# ---------- knowledge graph ----------


@app.get("/api/topology")
async def topology() -> dict[str, Any]:
    return store().snapshot()


@app.post("/api/discovery")
async def start_discovery() -> dict[str, str]:
    inventory = load_inventory(settings.lab_inventory)

    async def work(run: Run) -> None:
        await run.emit({"type": "started", "devices": [d.name for d in inventory.devices]})
        result = await discover(MCP_SERVERS["network"], inventory, store(), run.emit)
        await run.emit({"type": "discovery_done", **result.summary()})

    run = registry.start("discovery", "Discovery", work)
    return {"id": run.id}


# ---------- investigations ----------


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/investigations")
async def start_investigation(body: Question) -> dict[str, str]:
    question = body.question.strip()

    async def work(run: Run) -> None:
        await investigate(question, run.emit, settings)
        await _record_case(run)

    run = registry.start("investigation", question, work)
    return {"id": run.id}


@app.get("/api/investigations")
async def investigations() -> list[dict[str, Any]]:
    runs = registry.recent("investigation")
    try:
        statuses = await asyncio.to_thread(cases().statuses, [r["id"] for r in runs])
    except Exception:  # noqa: BLE001 - Neo4j down: the list still shows, without case tags
        statuses = {}
    return [{**r, "case_status": statuses.get(r["id"])} for r in runs]


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: str) -> dict[str, Any]:
    run = registry.runs.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    return {**run.summary(), "events": run.events}


@app.get("/api/runs/{run_id}/events")
async def run_events(
    run_id: str, after: int = 0, last_event_id: str | None = Header(default=None)
) -> StreamingResponse:
    """The run's events. `after` (or the browser's Last-Event-ID when it reconnects by itself)
    skips the ones the viewer already has."""
    run = registry.runs.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    if last_event_id and last_event_id.isdigit():
        after = max(after, int(last_event_id))
    return _sse(run, after)


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@app.post("/api/runs/{run_id}/messages")
async def send_message(run_id: str, body: Message) -> dict[str, Any]:
    """A follow-up from the engineer: AINOPS replies in a new turn of the same conversation."""
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "the message is empty")
    run = registry.runs.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    # What the conversation holds before this message (the reply is built on it).
    earlier = earlier_of(run.events, run.title, run.started_at)

    async def work(current: Run) -> None:
        await investigate(text, current.emit, settings, earlier)
        await _record_case(current)

    try:
        turn = await registry.follow_up(run_id, text, work)
    except Refused as refused:
        raise HTTPException(409, str(refused)) from None
    return {"id": run_id, "turn": turn}


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str) -> dict[str, bool]:
    try:
        registry.stop(run_id)
    except KeyError:
        raise HTTPException(404, "unknown run") from None
    except Refused as refused:
        raise HTTPException(409, str(refused)) from None
    return {"stopping": True}


# ---------- cases (what an investigation found, reviewed by an engineer) ----------


def _device_names() -> list[str]:
    return [str(d["name"]) for d in store().devices()]


def _draft_and_save(run: Run) -> Case | None:
    draft = draft_case(run.id, run.title, run.started_at, run.events, _device_names())
    if draft is None:
        return None
    book = cases()
    existing = book.for_run(run.id)
    case = follow(existing, draft) if existing else draft
    if case is not existing:
        book.save(case, only_if="pending" if existing else None)
    return case


async def _record_case(run: Run) -> None:
    """After a reply that found a root cause: draft the conversation's case, or bring a pending
    one up to date. A case that cannot be saved never fails the investigation."""
    if run.summary()["outcome"] != "diagnosed":  # how this reply (the latest turn) ended
        return
    try:
        case = await asyncio.to_thread(_draft_and_save, run)
    except Exception as error:  # noqa: BLE001 - shown on the page, the diagnosis stands
        await run.emit({"type": "case", "error": f"case not saved: {type(error).__name__}"})
        return
    if case is not None:
        await run.emit({"type": "case", "id": case.id, "status": case.status})


def _case_or_404(case_id: str) -> Case:
    case = cases().get(case_id)
    if case is None:
        raise HTTPException(404, "unknown case")
    return case


@app.get("/api/cases")
async def case_list(status: str | None = None) -> dict[str, Any]:
    book = cases()
    found = await asyncio.to_thread(book.all, status)
    counts = await asyncio.to_thread(book.counts)
    return {"cases": [c.model_dump() for c in found], "counts": counts}


@app.get("/api/cases/{case_id}")
async def case_detail(case_id: str) -> dict[str, Any]:
    return (await asyncio.to_thread(_case_or_404, case_id)).model_dump()


@app.get("/api/runs/{run_id}/case")
async def run_case(run_id: str) -> dict[str, Any]:
    """The case of a conversation, and whether the engineer can make one by hand now."""
    run = registry.runs.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    case = await asyncio.to_thread(cases().for_run, run_id)
    latest = run.summary()["outcome"]
    return {
        "case": case.model_dump() if case else None,
        "can_make": case is None and run.done and latest in BY_HAND,
    }


@app.post("/api/runs/{run_id}/case")
async def make_case(run_id: str) -> dict[str, Any]:
    """The engineer asks for a case, e.g. for an inconclusive run whose real cause they know."""
    run = registry.runs.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    if not run.done:
        raise HTTPException(409, "wait for AINOPS to finish its reply")

    def make() -> Case:
        book = cases()
        if book.for_run(run_id) is not None:
            raise CaseError("this conversation already has a case")
        names = _device_names()
        case = draft_case(run.id, run.title, run.started_at, run.events, names, by_hand=True)
        if case is None:
            raise CaseError("no reply here to make a case of (only refusals or plain answers)")
        book.save(case)
        return case

    try:
        case = await asyncio.to_thread(make)
    except CaseError as error:
        raise HTTPException(409, str(error)) from None
    return case.model_dump()


@app.post("/api/cases/{case_id}/review")
async def review(case_id: str, body: ReviewRequest) -> dict[str, Any]:
    def apply() -> Case:
        case = _case_or_404(case_id)
        reviewed = review_case(case, body)
        if not cases().save(reviewed, only_if="pending"):
            raise CaseError("someone else reviewed this case a moment ago: reload it")
        return reviewed

    try:
        case = await asyncio.to_thread(apply)
    except CaseError as error:
        raise HTTPException(409, str(error)) from None
    return case.model_dump()


# ---------- audit ----------


@app.get("/api/audit")
async def audit(limit: int = 100) -> list[dict[str, Any]]:
    entries = AuditLog(settings.logs_dir / "network-audit.jsonl").tail(min(max(limit, 1), 500))
    return list(reversed(entries))
