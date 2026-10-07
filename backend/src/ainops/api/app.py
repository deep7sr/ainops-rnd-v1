"""The AINOPS API for the web UI (http://127.0.0.1:8000, local only).

It does not talk to devices itself: investigations run the agent (which uses the MCP servers) and
discovery calls the network MCP server. It streams their steps to the browser as Server-Sent
Events, serves the knowledge graph for the map, and shows the MCP tool definitions.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field

from ainops.agent.runner import investigate
from ainops.agent.skills import load_skills
from ainops.api.runs import Run, RunRegistry
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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    if _store is not None:
        _store.close()


app = FastAPI(title="AINOPS API", lifespan=lifespan, docs_url="/api/docs")


def _sse(run: Run) -> StreamingResponse:
    return StreamingResponse(
        run.stream(),
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
        "executor": settings.lab_executor,
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

    run = registry.start("investigation", question, work)
    return {"id": run.id}


@app.get("/api/investigations")
async def investigations() -> list[dict[str, Any]]:
    return registry.recent("investigation")


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: str) -> dict[str, Any]:
    run = registry.runs.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    return {**run.summary(), "events": run.events}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    run = registry.runs.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    return _sse(run)


# ---------- audit ----------


@app.get("/api/audit")
async def audit(limit: int = 100) -> list[dict[str, Any]]:
    entries = AuditLog(settings.logs_dir / "network-audit.jsonl").tail(min(max(limit, 1), 500))
    return list(reversed(entries))
