"""labsim: the simulated lab.

uv run python -m labsim                  start the 8 consoles (127.0.0.1, inventory ports)
uv run python -m labsim faults           list the faults, and which are on
uv run python -m labsim fault fault-1    apply a fault (the running simulator picks it up)
uv run python -m labsim heal [name]      remove one fault, or all
"""

import argparse
import asyncio
import contextlib
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from labsim.console import start
from labsim.model import REPO_ROOT, LabError, load_lab
from labsim.state import STATE_FILE, Simulator, read_faults, write_faults


def _run(host: str, speed: float) -> int:
    load_dotenv(REPO_ROOT / ".env")  # the Junos logins, as AINOPS reads them
    simulator = Simulator(load_lab(), state_file=STATE_FILE)

    async def serve() -> None:
        servers = await start(simulator, host=host, speed=speed, log=_log)
        lines = ["labsim: the simulated lab is running (close this window to stop it)"]
        lines += [
            f"  {d.name:<13} {d.platform:<14} telnet {host} {d.port}"
            for d in simulator.base.consoles()
        ]
        lines.append(f"  faults on: {', '.join(simulator.faults) or 'none (healthy)'}")
        lines.append("  change them in another window: uv run python -m labsim faults")
        print("\n".join(lines), flush=True)
        try:
            await asyncio.gather(*(s.serve_forever() for s in servers))
        finally:
            for server in servers:
                server.close()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve())
    return 0


def _log(message: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {message}", flush=True)


def _faults(state: Path) -> int:
    lab = load_lab()
    on, _ = read_faults(state)
    for name, fault in lab.faults.items():
        print(f"{'[on] ' if name in on else '     '}{name:<26} {fault.description}")
    if not on:
        print("No fault is on: the lab is healthy.")
    return 0


def _fault(name: str, state: Path) -> int:
    lab = load_lab()
    if name not in lab.faults:
        print(f"No fault named {name!r}. Known: {', '.join(lab.faults)}", file=sys.stderr)
        return 1
    on, _ = read_faults(state)
    if name not in on:
        write_faults([*on, name], state)
    print(f"Fault {name} is on: {lab.faults[name].description}")
    return 0


def _heal(name: str | None, state: Path) -> int:
    on, _ = read_faults(state)
    if name is not None and name not in on:
        print(f"Fault {name} is not on (on: {', '.join(on) or 'none'})", file=sys.stderr)
        return 1
    write_faults([] if name is None else [n for n in on if n != name], state)
    print("Healed: no fault is on." if name is None else f"Fault {name} removed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="labsim", description="The simulated TRV/MAA lab.")
    commands = parser.add_subparsers(dest="command")
    run = commands.add_parser("run", help="start the consoles (the default)")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--speed", type=float, default=1.0, help="1: like the real lab, 0: instant")
    commands.add_parser("faults", help="list the faults")
    fault = commands.add_parser("fault", help="apply a fault")
    fault.add_argument("name")
    heal = commands.add_parser("heal", help="remove one fault, or all")
    heal.add_argument("name", nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.command == "faults":
            return _faults(STATE_FILE)
        if args.command == "fault":
            return _fault(args.name, STATE_FILE)
        if args.command == "heal":
            return _heal(args.name, STATE_FILE)
        return _run(getattr(args, "host", "127.0.0.1"), getattr(args, "speed", 1.0))
    except LabError as error:
        print(f"labsim: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"labsim: {error} (state file: {STATE_FILE})", file=sys.stderr)
        return 2
