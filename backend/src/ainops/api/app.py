"""The AINOPS API for the web UI (http://127.0.0.1:8000, local only).

It does not talk to devices itself: investigations run the agent (which uses the MCP servers) and
discovery calls the network MCP server. It streams their steps to the browser as Server-Sent
Events, serves the knowledge graph for the map, and shows the MCP tool definitions.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field

from ainops import skill_book
from ainops.agent.conversation import Earlier, earlier_of
from ainops.agent.runner import investigate
from ainops.agent.skills import Skill, load_skills, parse_skill
from ainops.api.runs import Refused, Run, RunRegistry
from ainops.case_store import CaseBook, Neo4jCases
from ainops.cases import (
    BY_HAND,
    Case,
    CaseError,
    ReviewRequest,
    case_id,
    draft_case,
    follow,
    review_case,
)
from ainops.config import get_settings
from ainops.inventory import PLATFORMS, UnknownDeviceError, load_inventory
from ainops.inventory_edit import (
    InventoryError,
    NewDevice,
    add_device,
    credential_profiles,
    remove_device,
)
from ainops.inventory_view import device_detail, inventory_rows
from ainops.network.audit import AuditLog
from ainops.similar import Hints, clues_of, similar_cases
from ainops.skill_book import SkillConflict, SkillError, SkillForm, SkillSave
from ainops.skill_usage import SkillUsage, skill_usage
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
        "lab_simulated": settings.lab_simulated,
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


async def _known_tools() -> set[str] | None:
    """The tool names of the running MCP servers; None when one is down (not checkable)."""
    known: set[str] = set()
    for url in MCP_SERVERS.values():
        try:
            known |= {t["name"] for t in await _list_tools(url)}
        except Exception:  # noqa: BLE001 - reported as tools_checked=false
            return None
    return known


def _version(name: str) -> str | None:
    found = skill_book.read(settings.skills_dir, name)
    return found[1] if found else None


@app.get("/api/skills")
async def skills() -> dict[str, Any]:
    """The skills the agent can use (with how often investigations used them), and the ones
    left out with their problems. `version` identifies the file an edit starts from.

    Tool names are checked against the running MCP servers; if one is down they cannot be checked
    (tools_checked is false) and only the format is.
    """
    library = load_skills(settings.skills_dir, await _known_tools())
    usage = skill_usage(
        {
            "id": run.id,
            "title": run.title,
            "started_at": run.started_at,
            "events": run.events,
            "outcome": run.summary()["outcome"],
        }
        for run in registry.runs.values()
        if run.kind == "investigation"
    )
    return {
        "skills": [
            {
                **s.model_dump(),
                "usage": usage.get(s.name, SkillUsage()).model_dump(),
                "version": _version(s.name),
            }
            for s in library.skills.values()
        ],
        "problems": [p.model_dump() for p in library.problems],
        "tools_checked": library.tools_checked,
    }


@app.post("/api/skills/check")
async def skill_check(form: SkillForm) -> dict[str, Any]:
    """The skill as the form would save it: its problems and its SKILL.md text (nothing saved)."""
    known = await _known_tools()
    skill, problems, text = skill_book.check(form, known)
    return {
        "skill": skill.model_dump() if skill else None,
        "problems": problems,
        "markdown": text,
        "tools_checked": known is not None,
    }


def _skill_audit(tool: str, name: str, summary: str) -> None:
    AuditLog(settings.logs_dir / "network-audit.jsonl").write(
        tool=tool,
        device=None,
        command=None,
        args={"skill": name},
        source="skills",
        outcome="ok",
        summary=summary,
        duration_ms=0,
    )


def _saved(request: SkillSave, skill: Skill, version: str, new: bool) -> dict[str, Any]:
    by = " ".join(request.by.split())
    _skill_audit(
        "create_skill" if new else "edit_skill",
        skill.name,
        f"skill {skill.name} {'created' if new else 'changed'} by {by}"
        + ("" if new else "; it needs a new review"),
    )
    return {**skill.model_dump(), "version": version}


@app.post("/api/skills", status_code=201)
async def skill_create(request: SkillSave) -> dict[str, Any]:
    """A new skill, saved as skills/<name>/SKILL.md; the agent can use it from its next reply."""
    if request.version is not None:
        raise HTTPException(422, "a new skill has no version")
    try:
        skill, version, new = skill_book.save(settings.skills_dir, request, await _known_tools())
    except SkillConflict as error:
        raise HTTPException(409, str(error)) from None
    except SkillError as error:
        raise HTTPException(422, str(error)) from None
    return _saved(request, skill, version, new)


@app.put("/api/skills/{name}")
async def skill_edit(name: str, request: SkillSave) -> dict[str, Any]:
    """An edit of the skill the engineer opened (`version`); the replaced file is kept."""
    if request.skill.name.strip().lower() != name:
        raise HTTPException(422, "a skill keeps its name: make a new skill to rename it")
    if request.version is None:
        raise HTTPException(422, "say which version you edited (version)")
    try:
        skill, version, new = skill_book.save(settings.skills_dir, request, await _known_tools())
    except SkillConflict as error:
        raise HTTPException(409, str(error)) from None
    except SkillError as error:
        raise HTTPException(422, str(error)) from None
    return _saved(request, skill, version, new)


class SkillReview(BaseModel):
    reviewer: str = Field(min_length=1, max_length=80)
    version: str = Field(max_length=64)


class SkillStatusChange(BaseModel):
    status: str = Field(max_length=10)
    by: str = Field(min_length=1, max_length=80)
    version: str = Field(max_length=64)


class SkillRestore(BaseModel):
    entry: str = Field(max_length=40)
    by: str = Field(min_length=1, max_length=80)
    version: str = Field(max_length=64)


async def _skill_change(
    tool: str, name: str, summary: str, work: Callable[[], tuple[Skill, str]]
) -> dict[str, Any]:
    try:
        skill, version = work()
    except SkillConflict as error:
        raise HTTPException(409, str(error)) from None
    except SkillError as error:
        raise HTTPException(422, str(error)) from None
    _skill_audit(tool, name, summary)
    return {**skill.model_dump(), "version": version}


@app.post("/api/skills/{name}/review")
async def skill_review(name: str, body: SkillReview) -> dict[str, Any]:
    """An engineer checked the procedure; a reviewed skill can go live."""
    by = " ".join(body.reviewer.split())
    return await _skill_change(
        "review_skill",
        name,
        f"skill {name} reviewed by {by}",
        lambda: skill_book.review(settings.skills_dir, name, body.reviewer, body.version),
    )


@app.post("/api/skills/{name}/status")
async def skill_status(name: str, body: SkillStatusChange) -> dict[str, Any]:
    """Live: AINOPS uses the skill. Draft or off: it does not (a draft can still be tried)."""
    by = " ".join(body.by.split())
    return await _skill_change(
        "skill_status",
        name,
        f"skill {name} set to {body.status} by {by}",
        lambda: skill_book.set_status(settings.skills_dir, name, body.status, body.version),
    )


@app.post("/api/skills/{name}/restore")
async def skill_restore(name: str, body: SkillRestore) -> dict[str, Any]:
    """Bring back an earlier version, saved like an edit (a draft that needs a new review)."""
    known = await _known_tools()
    by = " ".join(body.by.split())
    return await _skill_change(
        "restore_skill",
        name,
        f"skill {name} restored to the version replaced {body.entry} by {by}; "
        "it needs a new review",
        lambda: skill_book.restore(
            settings.skills_dir, name, body.entry, body.by, body.version, known
        ),
    )


@app.get("/api/skills/{name}/history")
async def skill_history(name: str) -> list[dict[str, Any]]:
    try:
        return [e.model_dump() for e in skill_book.history(settings.skills_dir, name)]
    except SkillError as error:
        raise HTTPException(404, str(error)) from None


@app.get("/api/skills/{name}/history/{entry}")
async def skill_old_version(name: str, entry: str) -> dict[str, Any]:
    """A replaced version, read as the loader would (tool names are not checked: it is old)."""
    try:
        text = skill_book.old_version(settings.skills_dir, name, entry)
    except SkillError as error:
        raise HTTPException(404, str(error)) from None
    skill, problems = parse_skill(name, text, None)
    return {"skill": skill.model_dump() if skill else None, "problems": problems, "markdown": text}


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
    # "Try this skill": offer this skill even if it is not live yet (the whole conversation).
    try_skill: str | None = Field(default=None, max_length=64)


def _tried_skill(events: list[dict[str, Any]]) -> str | None:
    """The skill a conversation was started to try (its first reply says so)."""
    first = next((e for e in events if e.get("type") == "started"), None)
    tried = first.get("trying") if first else None
    return tried if isinstance(tried, str) else None


@app.post("/api/investigations")
async def start_investigation(body: Question) -> dict[str, str]:
    question = body.question.strip()
    trying = body.try_skill.strip().lower() if body.try_skill else None
    if trying and load_skills(settings.skills_dir, None).get(trying) is None:
        raise HTTPException(422, f"there is no usable skill named '{trying}' to try")

    async def work(run: Run) -> None:
        hints = await asyncio.to_thread(_look_up_hints, run, question, None)
        await investigate(question, run.emit, settings, hints=hints, trying=trying)
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
    trying = _tried_skill(run.events)

    async def work(current: Run) -> None:
        hints = await asyncio.to_thread(_look_up_hints, current, text, earlier)
        await investigate(text, current.emit, settings, earlier, hints, trying)
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


def _look_up_hints(run: Run, message: str, earlier: Earlier | None) -> Hints:
    """Similar approved cases for this reply (similar.py). Never fails the reply: when the graph
    cannot be read, the reply goes on without hints and the page says why."""
    try:
        sites = {str(d["name"]): str(d.get("site") or "") for d in store().devices()}
        approved = cases().all("approved")
    except Exception as error:  # noqa: BLE001 - shown in the hints step
        return Hints(error=f"could not look up past cases: {type(error).__name__}")
    texts = [*(t.message for t in earlier.turns), message] if earlier else [message]
    checks = [(r.device, r.tool, r.summary) for r in earlier.evidence.values()] if earlier else []
    offered = {
        str(hint.get("case_id"))
        for event in run.events
        if event.get("type") == "hints"
        for hint in event.get("cases") or []
    }
    # Never this conversation's own case, nor one already offered earlier in it.
    exclude = offered | {case_id(run.id)}
    found = similar_cases(approved, clues_of(texts, checks, sites), sites, exclude)
    return Hints(cases=found, looked_at=len(approved))


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


# ---------- inventory (every device AINOPS knows, and its status) ----------


def _graph_and_cases() -> tuple[dict[str, Any] | None, list[Case] | None, str | None]:
    """The graph snapshot and all cases. The page still lists the devices when they fail."""
    try:
        snapshot = store().snapshot()
    except Exception as error:  # noqa: BLE001 - shown on the page
        return None, None, f"knowledge graph not reachable: {type(error).__name__}"
    try:
        found: list[Case] | None = cases().all()
    except Exception:  # noqa: BLE001 - the case counts are left out
        found = None
    return snapshot, found, None


@app.get("/api/inventory")
async def inventory_list() -> dict[str, Any]:
    inventory = load_inventory(settings.lab_inventory)
    snapshot, found, problem = await asyncio.to_thread(_graph_and_cases)
    return {
        "devices": inventory_rows(inventory, snapshot, found),
        "sites": inventory.sites,
        "discovery": (snapshot or {}).get("discovery"),
        "graph_error": problem,
    }


@app.get("/api/inventory/options")
async def inventory_options() -> dict[str, Any]:
    """What the "Add device" form can offer: sites, roles in use, platforms, login profiles
    (names only: the secrets stay in .env)."""
    inventory = load_inventory(settings.lab_inventory)
    return {
        "sites": inventory.sites,
        "roles": sorted({d.role for d in inventory.devices}),
        "platforms": list(PLATFORMS),
        "credential_profiles": credential_profiles(),
    }


def _audit(**entry: Any) -> None:
    AuditLog(settings.logs_dir / "network-audit.jsonl").write(
        command=None, source="inventory", duration_ms=0, **entry
    )


@app.post("/api/inventory")
async def inventory_add(body: NewDevice) -> dict[str, Any]:
    """Add a device. AINOPS can then log in to it (read-only) with the chosen login profile."""
    try:
        device = add_device(settings.lab_inventory, body, credential_profiles())
    except InventoryError as error:
        raise HTTPException(409, str(error)) from None
    _audit(
        tool="add_device",
        device=device.name,
        args={"site": device.site, "role": device.role, "platform": device.platform,
              "port": device.port, "credential_ref": device.credential_ref},
        outcome="ok",
        summary=f"added to the inventory by {device.added_by}",
    )  # fmt: skip
    inventory = load_inventory(settings.lab_inventory)
    return next(r for r in inventory_rows(inventory, None, None) if r["name"] == device.name)


class Removal(BaseModel):
    removed_by: str = Field(max_length=80)


@app.post("/api/inventory/{name}/remove")
async def inventory_remove(name: str, body: Removal) -> dict[str, str]:
    """Remove a device added on this page. It leaves the knowledge graph at the next discovery."""
    try:
        device = remove_device(settings.lab_inventory, name, body.removed_by)
    except UnknownDeviceError as error:
        raise HTTPException(404, str(error)) from None
    except InventoryError as error:
        raise HTTPException(409, str(error)) from None
    by = " ".join(body.removed_by.split())
    _audit(
        tool="remove_device",
        device=device.name,
        args={},
        outcome="ok",
        summary=f"removed from the inventory by {by}",
    )
    return {"removed": device.name}


@app.get("/api/inventory/{name}")
async def inventory_device(name: str) -> dict[str, Any]:
    inventory = load_inventory(settings.lab_inventory)
    try:
        device = inventory.get(name)
    except UnknownDeviceError as error:
        raise HTTPException(404, str(error)) from None
    snapshot, found, problem = await asyncio.to_thread(_graph_and_cases)
    runs = [
        {
            "id": run.id,
            "title": run.title,
            "started_at": run.started_at,
            "events": run.events,
            "summary": run.summary(),
        }
        for run in registry.runs.values()
        if run.kind == "investigation"
    ]
    return {**device_detail(inventory, device, snapshot, found, runs), "graph_error": problem}


# ---------- audit ----------


@app.get("/api/audit")
async def audit(limit: int = 100) -> list[dict[str, Any]]:
    entries = AuditLog(settings.logs_dir / "network-audit.jsonl").tail(min(max(limit, 1), 500))
    return list(reversed(entries))
