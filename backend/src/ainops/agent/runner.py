"""One investigation: the agent loop over the MCP tools, with AINOPS checks around every tool call.

    question -> [LLM picks a tool] -> AINOPS check -> MCP server -> device -> result [E#] -> LLM ...
             -> Report (structured) -> verify (code: citations, confidence) -> engineer

The loop itself is LangChain's `create_agent` (a LangGraph graph). Our middleware wraps every tool
call to:
- refuse calls that break a rule, in code, before they reach an MCP server (tool budget, IP
  addresses that did not come from the question or earlier evidence);
- label each result with an evidence id ([E1], [E2] ...) that the report must cite;
- shrink results to compact JSON (fewer tokens for the LLM);
- stream every step (what the agent thought, which tool, what came back) to the UI.
"""

import copy
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langgraph.types import Command

from ainops.agent.conversation import Earlier, follow_up_prompt
from ainops.agent.prompts import RECHECK, SYSTEM_PROMPT
from ainops.agent.report import EvidenceRecord, Report, not_shown, verify
from ainops.agent.skills import Skill, SkillLibrary, instructions, load_skills, step_tools
from ainops.config import Settings
from ainops.similar import Hints, hints_prompt

Event = dict[str, Any]
Emit = Callable[[Event], Awaitable[None]]

MAX_TOOL_CALLS = 16
MAX_SKILL_LOADS = 2  # opening a skill is not a network check and does not use the tool budget
USE_SKILL = "use_skill"
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IP_ARGS = ("destination", "source", "query")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


@dataclass
class Investigation:
    question: str
    emit: Emit
    tool_servers: dict[str, str]
    evidence: dict[str, EvidenceRecord] = field(default_factory=dict)
    known_ips: set[str] = field(default_factory=set)
    tool_calls: int = 0
    started: float = field(default_factory=time.monotonic)
    skills: SkillLibrary = field(default_factory=SkillLibrary)
    active_skill: Skill | None = None
    skills_used: list[str] = field(default_factory=list)
    skill_loads: int = 0
    current_step: int = 1  # the skill step the agent is on (for steps it does not tag)
    next_evidence: int = 1  # continues across the turns of a conversation (see conversation.py)
    tokens_in: int = 0  # what the LLM read and wrote for this reply (all its steps)
    tokens_out: int = 0

    def __post_init__(self) -> None:
        self.known_ips.update(_IPV4.findall(self.question))

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

    def step_of(self, value: Any, tool: str) -> int | None:
        """The skill step a tool call carries out: None without an open skill, 0 beyond it.

        Models often leave the optional skill_step out (or send 0), so code works it out from the
        tool: the first step from the current one on that names this tool, else the latest earlier
        one (a re-check). A number the model gives is used when that step names this tool (or
        names no tool at all). A tool no step names goes beyond the skill.
        """
        if self.active_skill is None:
            return None
        tools = step_tools(self.active_skill)
        given = None
        if not isinstance(value, bool) and isinstance(value, int | str):
            try:
                given = int(value)
            except ValueError:
                given = None
        named = tools[given - 1] if given is not None and 1 <= given <= len(tools) else None
        if given is not None and named is not None and (tool in named or not named):
            step = given
        else:
            candidates = [n for n, names in enumerate(tools, start=1) if tool in names]
            later = [n for n in candidates if n >= self.current_step]
            earlier = [n for n in candidates if n < self.current_step]
            step = later[0] if later else earlier[-1] if earlier else 0
        if step:
            self.current_step = step
        return step

    def check(self, tool: str, args: dict[str, Any]) -> str | None:
        """AINOPS safety check before a tool call reaches an MCP server. None means allowed."""
        if tool not in self.tool_servers:
            return f"'{tool}' is not an AINOPS tool"
        if self.tool_calls >= MAX_TOOL_CALLS:
            return f"the tool budget ({MAX_TOOL_CALLS} calls) is used up: write the report now"
        for name in _IP_ARGS:
            value = args.get(name)
            is_ip = isinstance(value, str) and _IPV4.fullmatch(value.strip())
            if is_ip and str(value).strip() not in self.known_ips:
                return (
                    f"{name} {value} did not come from the question or earlier evidence; "
                    "use only addresses you have seen"
                )
        return None


class AinopsMiddleware(AgentMiddleware):
    def __init__(self, run: Investigation) -> None:
        super().__init__()
        self.run = run

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        message = state["messages"][-1]
        if not isinstance(message, AIMessage):
            return None
        if message.usage_metadata:  # what this step cost, as the LLM reports it
            self.run.tokens_in += message.usage_metadata["input_tokens"]
            self.run.tokens_out += message.usage_metadata["output_tokens"]
        thought = _text(message.content).strip()
        reasoning = message.additional_kwargs.get("reasoning_content") or ""
        calls = [c["name"] for c in message.tool_calls if c["name"] != "Report"]
        if thought or calls:
            await self.run.emit(
                {
                    "type": "thought",
                    "text": thought
                    or (reasoning.strip().split("\n")[0][:300] if reasoning else ""),
                    "tools": calls,
                    "at_ms": self.run.elapsed_ms(),
                }
            )
        return None

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        run = self.run
        call = request.tool_call
        name, args, call_id = call["name"], dict(call.get("args") or {}), call["id"]
        server = run.tool_servers.get(name, "?")
        # "reason" exists only on the agent side (see with_reason): shown, never sent to MCP.
        reason = str(args.pop("reason", "") or "").strip()
        # So is "skill_step": which step of the open skill this call carries out.
        skill_step = run.step_of(args.pop("skill_step", None), name)
        if name == USE_SKILL:
            return await self._use_skill(str(call_id), args, reason)
        request = request.override(tool_call={**call, "args": args})

        refusal = run.check(name, args)
        if refusal:
            await run.emit(
                {
                    "type": "refused",
                    "tool": name,
                    "args": args,
                    "reason": refusal,
                    "why": reason,
                    "skill_step": skill_step,
                    "at_ms": run.elapsed_ms(),
                }  # fmt: skip
            )
            return ToolMessage(
                content=f"REFUSED by the AINOPS safety check: {refusal}",
                tool_call_id=call_id,
                name=name,
                status="error",
            )

        run.tool_calls += 1
        evidence_id = f"E{run.next_evidence}"
        run.next_evidence += 1
        await run.emit(
            {
                "type": "tool_call",
                "id": evidence_id,
                "tool": name,
                "server": server,
                "args": args,
                "why": reason,
                "skill_step": skill_step,
                "at_ms": run.elapsed_ms(),
            }  # fmt: skip
        )
        started = time.monotonic()
        result = await handler(request)
        duration_ms = int((time.monotonic() - started) * 1000)
        if not isinstance(result, ToolMessage):
            return result

        text = _text(result.content)
        run.known_ips.update(_IPV4.findall(text))
        payload: Any
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        failed = result.status == "error" or payload is None
        device = payload.get("device") if isinstance(payload, dict) else args.get("device")
        # Only a device NAME goes on: find_device returns a whole device record under "device".
        device = device if isinstance(device, str) else None
        summary = (
            payload.get("summary", "")
            if isinstance(payload, dict) and "summary" in payload
            else (text[:200] if failed else "")
        )
        source = "graph"
        if isinstance(payload, dict) and isinstance(payload.get("evidence"), dict):
            source = payload["evidence"].get("source", "live")
        run.evidence[evidence_id] = EvidenceRecord(
            id=evidence_id,
            tool=name,
            device=device if isinstance(device, str) else None,
            summary=summary,
            source=source,
            ok=not failed,
            at=datetime.now(UTC),
        )
        await run.emit(
            {
                "type": "tool_result",
                "id": evidence_id,
                "tool": name,
                "server": server,
                "device": device,
                "ok": not failed,
                "summary": summary or ("done" if not failed else text[:200]),
                "data": payload.get("data")
                if isinstance(payload, dict) and "data" in payload
                else payload,  # fmt: skip
                "evidence": payload.get("evidence") if isinstance(payload, dict) else None,
                "health": payload.get("health") if isinstance(payload, dict) else None,
                "duration_ms": duration_ms,
                "at_ms": run.elapsed_ms(),
            }
        )
        compact = _compact(payload) if payload is not None else text[:1500]
        return result.model_copy(update={"content": f"[{evidence_id}] {compact}"})

    async def _use_skill(self, call_id: str, args: dict[str, Any], reason: str) -> ToolMessage:
        """Open a skill: never reaches an MCP server; the UI shows which skill and its steps."""
        run = self.run
        wanted = str(args.get("skill") or "")
        skill = run.skills.get(wanted)
        refusal = None
        if run.skill_loads >= MAX_SKILL_LOADS:
            refusal = f"at most {MAX_SKILL_LOADS} skills per investigation: continue with the tools"
        elif skill is None:
            names = ", ".join(run.skills.skills) or "none"
            refusal = f"there is no skill '{wanted}' (skills: {names})"
        if refusal or skill is None:
            await run.emit(
                {
                    "type": "refused",
                    "tool": USE_SKILL,
                    "args": args,
                    "reason": refusal,
                    "why": reason,
                    "skill_step": None,
                    "at_ms": run.elapsed_ms(),
                }  # fmt: skip
            )
            return ToolMessage(
                content=f"REFUSED: {refusal}", tool_call_id=call_id, name=USE_SKILL, status="error"
            )
        run.skill_loads += 1
        run.active_skill = skill
        run.current_step = 1
        if skill.name not in run.skills_used:
            run.skills_used.append(skill.name)
        await run.emit(
            {
                "type": "skill",
                "name": skill.name,
                "description": skill.description,
                "steps": skill.steps,
                "author": skill.author,
                "reviewed_by": skill.reviewed_by,
                "status": skill.status,
                "why": reason,
                "at_ms": run.elapsed_ms(),
            }  # fmt: skip
        )
        return ToolMessage(content=instructions(skill), tool_call_id=call_id, name=USE_SKILL)


def _compact(payload: Any) -> str:
    """Only what the LLM needs, as dense JSON."""
    if isinstance(payload, dict) and "evidence" in payload:
        slim = {k: v for k, v in payload.items() if k not in ("evidence", "platform")}
        slim["source"] = payload["evidence"].get("source")
        payload = slim
    return json.dumps(payload, separators=(",", ":"), default=str)[:6000]


def with_reason(tool: BaseTool, skill_step: bool = False) -> BaseTool:
    """Add a required `reason` argument to a tool's schema, for the agent only.

    The LLM must say in one sentence why it calls the tool; the UI shows it next to the step, so
    the engineer can follow the investigation. The middleware removes it before the MCP call.
    With `skill_step`, also an optional `skill_step`: which step of the open skill the call does.
    """
    schema = tool.args_schema
    if not isinstance(schema, dict):
        return tool
    schema = copy.deepcopy(schema)
    properties = {
        "reason": {
            "type": "string",
            "description": "One short sentence: what you are checking and why",
        },
        **schema.get("properties", {}),
    }
    if skill_step:
        properties["skill_step"] = {
            "type": "integer",
            "minimum": 0,
            "description": "The number of the open skill's step this call carries out",
        }
    schema["properties"] = properties
    schema["required"] = ["reason", *[r for r in schema.get("required", []) if r != "reason"]]
    return tool.model_copy(update={"args_schema": schema})


def skill_tool(library: SkillLibrary) -> BaseTool:
    """use_skill: opens one of the listed skills (handled by AinopsMiddleware, never MCP)."""

    async def use_skill(skill: str) -> str:
        found = library.get(skill)
        return instructions(found) if found else f"there is no skill '{skill}'"

    return StructuredTool(
        name=USE_SKILL,
        description=(
            "Open an expert skill: the step-by-step procedure the network engineers wrote for "
            "this kind of question. Use it first when one of the listed skills fits."
        ),
        args_schema={
            "type": "object",
            "properties": {"skill": {"type": "string", "description": "Name of the skill"}},
            "required": ["skill"],
        },
        coroutine=use_skill,
    )


def build_model(settings: Settings) -> BaseChatModel:
    if settings.llm_provider == "azure_openai":
        # GPT-5.x deployments are reasoning models: they accept only the default temperature.
        return AzureChatOpenAI(
            azure_endpoint=settings.azure_ai_endpoint,
            api_key=settings.azure_ai_api_key,
            api_version=settings.azure_api_version,
            azure_deployment=settings.azure_model,
            max_retries=4,
            timeout=120,
        )
    return ChatOpenAI(
        model=settings.llm_model_reasoning,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0,
        max_retries=4,
        timeout=90,
    )


def mcp_client(settings: Settings) -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            "topology": {
                "transport": "streamable_http",
                "url": f"http://127.0.0.1:{settings.mcp_topology_port}/mcp",
            },
            "network": {
                "transport": "streamable_http",
                "url": f"http://127.0.0.1:{settings.mcp_network_port}/mcp",
            },
        }
    )


async def investigate(
    question: str,
    emit: Emit,
    settings: Settings,
    earlier: Earlier | None = None,
    hints: Hints | None = None,
    trying: str | None = None,
) -> dict[str, Any]:
    """Answer one message: the question, or with `earlier`, a follow-up in a conversation.

    `hints`: similar approved past cases (similar.py). They go into the prompt as hints only: no
    evidence id, so they cannot be cited or raise the confidence, and their addresses are not
    added to the ones the checks may use.
    `trying`: a skill the engineer started this conversation to try ("Try this skill"); it is
    offered even when it is not live yet.
    """
    client = mcp_client(settings)
    topology_tools = await client.get_tools(server_name="topology")
    network_tools = await client.get_tools(server_name="network")
    servers = {t.name: "topology" for t in topology_tools}
    servers.update({t.name: "network" for t in network_tools})
    # Only live skills, and the one this investigation was started to try.
    library = load_skills(settings.skills_dir, servers).for_agent(trying)
    has_skills = bool(library.skills)
    tools = [with_reason(t, skill_step=has_skills) for t in [*topology_tools, *network_tools]]
    if has_skills:
        tools.append(with_reason(skill_tool(library)))
        servers[USE_SKILL] = "agent"
    run = Investigation(question=question, emit=emit, tool_servers=servers, skills=library)
    history: list[Any] = []
    prompt = SYSTEM_PROMPT + library.prompt_section()
    if earlier is not None:
        run.evidence.update(earlier.evidence)
        run.known_ips.update(earlier.known_ips)
        run.next_evidence = earlier.next_evidence
        history = earlier.messages()
        prompt += follow_up_prompt()
    await emit(
        {
            "type": "started",
            "question": question,
            "turn": earlier.next_turn if earlier else 1,
            "tools": sorted(servers),
            "skills": sorted(library.skills),
            "trying": library.trying,
            "at_ms": 0,
        }
    )
    if hints is not None:
        await emit(
            {
                "type": "hints",
                "cases": [h.as_event() for h in hints.cases],
                "looked_at": hints.looked_at,
                "error": hints.error,
                "at_ms": run.elapsed_ms(),
            }
        )
        prompt += hints_prompt(hints.cases)

    agent = create_agent(
        build_model(settings),
        tools,
        system_prompt=prompt,
        middleware=[AinopsMiddleware(run)],
        response_format=ToolStrategy(Report),
    )
    result = await agent.ainvoke(
        {"messages": [*history, HumanMessage(question)]}, config={"recursion_limit": 70}
    )
    report = result.get("structured_response")
    # Check before answering: a root cause none of its cited checks shows goes back once, to be
    # checked directly (while the tool budget lasts). What comes back is verified as usual.
    blamed = not_shown(report, run.evidence) if isinstance(report, Report) else []
    if blamed and run.tool_calls < MAX_TOOL_CALLS:
        await emit({"type": "recheck", "blamed": blamed, "at_ms": run.elapsed_ms()})
        note = HumanMessage(RECHECK.format(blamed=", ".join(blamed)))
        result = await agent.ainvoke(
            {"messages": [*result["messages"], note]}, config={"recursion_limit": 70}
        )
        again = result.get("structured_response")
        report = again if isinstance(again, Report) else report
    if not isinstance(report, Report):
        last = next((m for m in reversed(result["messages"]) if isinstance(m, AIMessage)), None)
        report = Report(
            outcome="inconclusive",
            summary=_text(last.content)[:800] if last else "The agent did not produce a report.",
            limitations=["the agent ended without the structured report"],
        )
    verdict = verify(report, run.evidence)
    final = {
        "type": "report",
        "report": report.model_dump(),
        "confidence": verdict.confidence,
        "confidence_reasons": verdict.reasons,
        "evidence": {k: vars(v) for k, v in run.evidence.items()},
        "tool_calls": run.tool_calls,
        "skills_used": run.skills_used,
        "tokens": {"input": run.tokens_in, "output": run.tokens_out},
        "at_ms": run.elapsed_ms(),
    }
    await emit(final)
    return final
