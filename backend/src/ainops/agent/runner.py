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
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.types import Command

from ainops.agent.prompts import SYSTEM_PROMPT
from ainops.agent.report import EvidenceRecord, Report, verify
from ainops.config import Settings

Event = dict[str, Any]
Emit = Callable[[Event], Awaitable[None]]

MAX_TOOL_CALLS = 16
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

    def __post_init__(self) -> None:
        self.known_ips.update(_IPV4.findall(self.question))

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

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
        evidence_id = f"E{len(run.evidence) + 1}"
        await run.emit(
            {
                "type": "tool_call",
                "id": evidence_id,
                "tool": name,
                "server": server,
                "args": args,
                "why": reason,
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
                "duration_ms": duration_ms,
                "at_ms": run.elapsed_ms(),
            }
        )
        compact = _compact(payload) if payload is not None else text[:1500]
        return result.model_copy(update={"content": f"[{evidence_id}] {compact}"})


def _compact(payload: Any) -> str:
    """Only what the LLM needs, as dense JSON."""
    if isinstance(payload, dict) and "evidence" in payload:
        slim = {k: v for k, v in payload.items() if k not in ("evidence", "platform")}
        slim["source"] = payload["evidence"].get("source")
        payload = slim
    return json.dumps(payload, separators=(",", ":"), default=str)[:6000]


def with_reason(tool: BaseTool) -> BaseTool:
    """Add a required `reason` argument to a tool's schema, for the agent only.

    The LLM must say in one sentence why it calls the tool; the UI shows it next to the step, so
    the engineer can follow the investigation. The middleware removes it before the MCP call.
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
    schema["properties"] = properties
    schema["required"] = ["reason", *[r for r in schema.get("required", []) if r != "reason"]]
    return tool.model_copy(update={"args_schema": schema})


def build_model(settings: Settings) -> ChatOpenAI:
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


async def investigate(question: str, emit: Emit, settings: Settings) -> dict[str, Any]:
    client = mcp_client(settings)
    topology_tools = await client.get_tools(server_name="topology")
    network_tools = await client.get_tools(server_name="network")
    servers = {t.name: "topology" for t in topology_tools}
    servers.update({t.name: "network" for t in network_tools})
    run = Investigation(question=question, emit=emit, tool_servers=servers)
    await emit({"type": "started", "question": question, "tools": sorted(servers), "at_ms": 0})

    agent = create_agent(
        build_model(settings),
        [with_reason(t) for t in [*topology_tools, *network_tools]],
        system_prompt=SYSTEM_PROMPT,
        middleware=[AinopsMiddleware(run)],
        response_format=ToolStrategy(Report),
    )
    result = await agent.ainvoke(
        {"messages": [HumanMessage(question)]}, config={"recursion_limit": 70}
    )
    report = result.get("structured_response")
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
        "at_ms": run.elapsed_ms(),
    }
    await emit(final)
    return final
