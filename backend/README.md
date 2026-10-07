# AINOPS backend (agentic design)

Python package `ainops`: the MCP servers that give an AI agent read-only access to the lab, the
knowledge graph, and the agent service. Everything runs with [uv](https://docs.astral.sh/uv/) from
this folder.

On the lab laptop, always start commands as `uv run python -m ainops ...`: Smart App Control blocks
the freshly built `ainops.exe` launcher but allows the python.org Python.

## Network MCP server

Read-only, vendor-neutral tools for the lab routers (Cisco IOS) and firewalls (Juniper vSRX).

```
uv run python -m ainops mcp-network        # http://127.0.0.1:8101/mcp
```

It always works on the live lab: `LAB_EVE_HOST=<EVE-NG address>` in the repo-root `.env`. There is
no mode that answers from saved outputs, and nothing is recorded while it works.

Test data (real device outputs the tests replay) is captured on purpose, never by normal use:

```
uv run python -m ainops capture healthy-2026-10-08   # -> fixtures/captures/healthy-2026-10-08/
```

Try the tools by hand, without any LLM, in the official MCP Inspector:

```
npx @modelcontextprotocol/inspector
```

Choose transport "Streamable HTTP", URL `http://127.0.0.1:8101/mcp`, Connect, then open Tools.

Where things live:

| File | What it is |
|---|---|
| `src/ainops/network/server.py` | Tool definitions (name, description, inputs): what the LLM sees |
| `src/ainops/network/commands.yaml` | The only commands the tools can send, per platform (SME-reviewed) |
| `src/ainops/network/guard.py` | Last check before a command is sent: read-only prefixes, pipes, forbidden words |
| `src/ainops/network/service.py` | Tool logic: inventory lookup, input validation, parsing, audit |
| `src/ainops/network/parsers.py` | Cisco text and Junos JSON -> one shared JSON shape |
| `lab/inventory.yaml` (repo root) | The lab devices and how to reach them (no secrets) |
| `logs/network-audit.jsonl` (repo root) | One line per tool call: who, what, which command, outcome |

## Checks

```
uv run pytest
uv run mypy src tests
uv run ruff check src tests && uv run ruff format --check src tests
```
