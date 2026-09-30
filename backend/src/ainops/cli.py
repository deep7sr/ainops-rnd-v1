"""`uv run ainops <command>`: start the pieces of AINOPS."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="ainops", description="AINOPS agentic platform")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("mcp-network", help="start the network MCP server (port 8101)")
    args = parser.parse_args()

    if args.command == "mcp-network":
        from ainops.network.server import main as run_network

        run_network()
