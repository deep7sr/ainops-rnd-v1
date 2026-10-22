"""`uv run python -m ainops <command>`: start the pieces of AINOPS."""

import argparse
import asyncio
import json
import sys
from typing import Any


def _discover() -> None:
    from ainops.config import get_settings
    from ainops.inventory import load_inventory
    from ainops.topology.discovery import discover
    from ainops.topology.graph import GraphStore

    settings = get_settings()
    inventory = load_inventory(settings.lab_inventory)
    store = GraphStore(
        settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password.get_secret_value()
    )

    async def show(event: dict[str, Any]) -> None:
        if event["type"] == "device_done":
            state = (
                f"{event['interfaces']} interfaces, {event['neighbors']} neighbours"
                if event["ok"]
                else f"FAILED: {event['error']}"
            )
            print(f"  {event['device']:<14} {state}")

    url = f"http://127.0.0.1:{settings.mcp_network_port}/mcp"
    print(f"Discovering through the network MCP server at {url} ...")
    try:
        result = asyncio.run(discover(url, inventory, store, show))
    finally:
        store.close()
    if not result.graph_updated:
        print("\nNo device answered: the knowledge graph was NOT changed.")
    print(f"\n{len(result.links)} links ({result.source} data):")
    for link in result.links:
        sources = "+".join(link.sources)
        stale = f"  (not refreshed since {link.stale_since})" if link.stale_since else ""
        print(f"  {link.a} {link.a_interface} <-> {link.b} {link.b_interface}  [{sources}]{stale}")
    print("\nFindings:" if result.findings else "\nNo findings.")
    for finding in result.findings:
        print(f"  - {finding}")


def _capture(name: str) -> None:
    from ainops.config import get_settings
    from ainops.inventory import load_inventory
    from ainops.network.audit import AuditLog
    from ainops.network.capture import CAPTURES, CapturingExecutor, tools_for
    from ainops.network.executor import LiveExecutor
    from ainops.network.service import NetworkService, ToolFailure, load_commands

    settings = get_settings()
    if not settings.lab_eve_host:
        raise SystemExit("LAB_EVE_HOST is not set in the repo-root .env")
    folder = CAPTURES / name
    executor = CapturingExecutor(LiveExecutor(settings.lab_eve_host), folder)
    service = NetworkService(
        inventory=load_inventory(settings.lab_inventory),
        executor=executor,
        audit=AuditLog(settings.logs_dir / "network-audit.jsonl"),
        commands=load_commands(),
    )
    print(f"Capturing the live lab into {folder} ...")
    try:
        for device in service.inventory.devices:
            for tool in tools_for(device.platform):
                try:
                    result = getattr(service, tool)(device.name)
                    print(f"  {device.name:<14} {tool:<24} {result.summary[:60]}")
                except ToolFailure as error:
                    print(f"  {device.name:<14} {tool:<24} FAILED: {str(error)[:60]}")
    finally:
        executor.close()


def _ask(question: str) -> None:
    from ainops.agent.runner import investigate
    from ainops.config import get_settings

    async def show(event: dict[str, Any]) -> None:
        kind = event["type"]
        seconds = f"{event.get('at_ms', 0) / 1000:5.1f}s"
        if kind == "thought" and event["text"]:
            print(f"{seconds}  thinks: {event['text']}")
        elif kind == "tool_call":
            if event.get("why"):
                print(f"{seconds}  why: {event['why']}")
            print(f"{seconds}  [{event['id']}] {event['server']}.{event['tool']} {event['args']}")
        elif kind == "tool_result":
            mark = "ok " if event["ok"] else "ERR"
            print(f"{seconds}        {mark} {event['summary']}")
        elif kind == "refused":
            print(f"{seconds}  REFUSED {event['tool']} {event['args']}: {event['reason']}")
        elif kind == "report":
            report = event["report"]
            print(f"\n{seconds}  {report['outcome'].upper()}  (confidence {event['confidence']})")
            print(f"  {report['summary']}")
            if report.get("root_cause"):
                print(f"  Root cause: {report['root_cause']} {report['root_cause_evidence']}")
            for step in report.get("next_steps", []):
                print(f"  - [{step['kind']}] {step['text']}")
            print(f"  Why this confidence: {'; '.join(event['confidence_reasons'])}")

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    settings = get_settings()
    final = asyncio.run(investigate(question, show, settings))
    path = settings.logs_dir / "last-investigation.json"
    path.write_text(json.dumps(final, indent=2), encoding="utf-8")
    print(f"\n(full result saved to {path})")


def _databases() -> list[tuple[str, str]]:
    """The databases AINOPS uses, as (setting, URL): the real lab's and the simulated lab's."""
    from ainops.config import get_settings

    settings = get_settings()
    found = [
        ("DATABASE_URL", settings.database_url.get_secret_value()),
        ("SIM_DATABASE_URL", settings.sim_database_url.get_secret_value()),
    ]
    return [(name, url) for name, url in found if url]


def _db(action: str) -> None:
    from ainops import db
    from ainops.config import get_settings

    settings = get_settings()
    databases = _databases()
    if not databases:
        raise SystemExit("No DATABASE_URL or SIM_DATABASE_URL in the repo-root .env")
    if action == "setup":
        admin = settings.postgres_admin_password.get_secret_value()
        if not admin:
            raise SystemExit("POSTGRES_ADMIN_PASSWORD is not set in the repo-root .env")
        test = settings.test_database_url.get_secret_value()
        urls = [url for _, url in databases] + ([test] if test else [])
        for line in db.setup(admin, urls):
            print(f"  {line}")
    if action in ("setup", "upgrade"):
        for name, url in databases:
            print(f"Upgrading {db.database_name(url)} ({name}) ...")
            db.upgrade(url)
    newest = db.newest_version()
    for name, url in databases:
        database = db.Database(url, max_size=1)
        try:
            version = database.schema_version()
        finally:
            database.close()
        state = "up to date" if version == newest else f"needs `ainops db upgrade` (code: {newest})"
        print(f"  {db.database_name(url):<14} ({name}) schema {version or 'none'}: {state}")


def _copy_cases(to: str) -> None:
    """Neo4j's cases into the real lab's or the simulated lab's database (named on purpose:
    the Neo4j cases do not say which lab they came from)."""
    from ainops import db
    from ainops.case_store import Neo4jCases, PostgresCases, copy_cases
    from ainops.config import get_settings
    from ainops.topology.graph import GraphStore

    settings = get_settings()
    secret = settings.sim_database_url if to == "sim" else settings.database_url
    url = secret.get_secret_value()
    if not url:
        raise SystemExit(f"{'SIM_DATABASE_URL' if to == 'sim' else 'DATABASE_URL'} is not set")
    store = GraphStore(
        settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password.get_secret_value()
    )
    database = db.Database(url, max_size=1)
    try:
        done = copy_cases(Neo4jCases(store.driver), PostgresCases(database))
    finally:
        database.close()
        store.close()
    print(f"Neo4j -> {db.database_name(url)}:")
    for kind, ids in done.items():
        print(f"  {kind:<10} {len(ids):>3}  {', '.join(ids)}")
    if done["different"]:
        print("  'different': already in Postgres but not the same; left as they are there.")
    print("Nothing was deleted from Neo4j.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ainops", description="AINOPS agentic platform")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("mcp-network", help="start the network MCP server (port 8101)")
    commands.add_parser("mcp-topology", help="start the topology MCP server (port 8102)")
    commands.add_parser("discover", help="rebuild the knowledge graph (needs mcp-network + Neo4j)")
    api = commands.add_parser("api", help="start the API for the web UI (port 8000)")
    api.add_argument("--reload", action="store_true", help="restart when code changes")
    capture = commands.add_parser(
        "capture", help="save the live lab's outputs as test data (fixtures/captures/<name>)"
    )
    capture.add_argument("name", help="e.g. healthy-2026-10-08 or fault1")
    ask = commands.add_parser("ask", help="investigate a question (needs both MCP servers)")
    ask.add_argument("question")
    database = commands.add_parser("db", help="the Postgres databases (see backend/README.md)")
    database.add_argument(
        "action",
        choices=["setup", "upgrade", "status", "copy-cases"],
        help="setup: make the roles and databases in .env, then upgrade; "
        "upgrade: bring each database to the newest schema; status: show each one's schema; "
        "copy-cases: copy Neo4j's cases into Postgres (needs --to)",
    )
    database.add_argument(
        "--to",
        choices=["real", "sim"],
        help="copy-cases: into the real lab's database or the simulated lab's",
    )
    args = parser.parse_args()

    if args.command == "mcp-network":
        from ainops.network.server import main as run_network

        run_network()
    elif args.command == "mcp-topology":
        from ainops.topology.server import main as run_topology

        run_topology()
    elif args.command == "discover":
        _discover()
    elif args.command == "api":
        import uvicorn

        uvicorn.run("ainops.api.app:app", host="127.0.0.1", port=8000, reload=args.reload)
    elif args.command == "capture":
        _capture(args.name)
    elif args.command == "ask":
        _ask(args.question)
    elif args.command == "db" and args.action == "copy-cases":
        if not args.to:
            parser.error("copy-cases needs --to real or --to sim")
        _copy_cases(args.to)
    elif args.command == "db":
        _db(args.action)
