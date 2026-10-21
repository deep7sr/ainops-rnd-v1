"""Run the evaluation cases on the simulated lab and score each answer.

Safety first: it runs only when the stack says it is on the simulated lab and a simulated console
answers, and it puts the simulator's faults back the way it found them, whatever happens.
"""

import argparse
import asyncio
import json
import socket
import sys
import time
import urllib.request
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ainops.agent.runner import investigate
from ainops.config import Settings, get_settings
from ainops.inventory import load_inventory
from evals.cases import Case, load_cases
from evals.score import VERDICTS, Score, score
from labsim.model import load_lab
from labsim.state import STATE_FILE, read_faults, write_faults

Investigate = Callable[..., Awaitable[dict[str, Any]]]
API = "http://127.0.0.1:8000"  # ainops api (cli.py)
CONSOLE = ("127.0.0.1", 32769)  # the first simulated console (lab/inventory.yaml)


class NotSimulated(RuntimeError):
    """The stack is not on the simulated lab: evaluations would score the wrong network."""


def check_simulated(api: str, console: tuple[str, int] = CONSOLE) -> None:
    """Raise NotSimulated unless AINOPS reports the simulated lab and a simulated console
    answers."""
    try:
        with urllib.request.urlopen(f"{api}/api/health", timeout=10) as response:
            health = json.load(response)
    except OSError as error:
        raise NotSimulated(
            f"the AINOPS API does not answer at {api} ({error}): start the stack with "
            r"scripts\start-all.ps1 -Sim"
        ) from error
    if health.get("lab_simulated") is not True:
        raise NotSimulated(
            "AINOPS is working on the live lab: evaluations switch simulator faults and only "
            r"run on the simulated lab (scripts\start-all.ps1 -Sim)"
        )
    try:
        socket.create_connection(console, timeout=5).close()
    except OSError as error:
        raise NotSimulated(
            f"no simulated console answers at {console[0]}:{console[1]}: start the lab simulator"
        ) from error


@dataclass
class Result:
    case: str
    attempt: int
    score: Score
    seconds: float
    final: dict[str, Any] | None
    error: str | None = None
    rechecked: bool = False
    events: list[str] = field(default_factory=list)

    def record(self) -> dict[str, Any]:
        report = (self.final or {}).get("report") or {}
        evidence = (self.final or {}).get("evidence") or {}
        return {
            "case": self.case,
            "attempt": self.attempt,
            "verdict": self.score.verdict,
            "confidently_wrong": self.score.confidently_wrong,
            "reasons": self.score.reasons,
            "outcome": report.get("outcome"),
            "confidence": self.score.confidence,
            "confidence_reasons": (self.final or {}).get("confidence_reasons"),
            "affected": report.get("affected"),
            "root_cause": report.get("root_cause"),
            "summary": report.get("summary"),
            "next_steps": report.get("next_steps"),
            "checks": (self.final or {}).get("tool_calls"),
            "tokens": (self.final or {}).get("tokens"),
            "seconds": round(self.seconds, 1),
            "rechecked": self.rechecked,
            "error": self.error,
            "evidence": [
                f"{e['id']} {e['tool']}({e.get('device') or ''}): {e.get('summary', '')}"
                for e in evidence.values()
            ],
        }


async def run_case(
    case: Case,
    attempt: int,
    settings: Settings,
    state_file: Path,
    run: Investigate = investigate,
) -> Result:
    write_faults(list(case.faults), state_file)
    seen: list[str] = []

    async def collect(event: dict[str, Any]) -> None:
        seen.append(str(event.get("type")))

    started = time.monotonic()
    final, error = None, None
    try:
        final = await run(case.question, collect, settings, trying=case.try_skill)
    except Exception as failure:  # noqa: BLE001 - any failure is a "failed" result, and the next case runs
        error = f"{type(failure).__name__}: {failure}"[:600]
    return Result(
        case=case.name,
        attempt=attempt,
        score=score(case, final, error),
        seconds=time.monotonic() - started,
        final=final,
        error=error,
        rechecked="recheck" in seen,
        events=seen,
    )


async def run_all(
    cases: list[Case],
    settings: Settings,
    *,
    repeat: int = 1,
    pause: float = 0,
    state_file: Path = STATE_FILE,
    run: Investigate = investigate,
    show: Callable[[Result], None] = lambda result: None,
) -> list[Result]:
    """Every case `repeat` times. The faults that were on are put back at the end, always."""
    before, _ = read_faults(state_file)
    results: list[Result] = []
    try:
        for attempt in range(1, repeat + 1):
            for case in cases:
                if results and pause:
                    await asyncio.sleep(pause)
                results.append(await run_case(case, attempt, settings, state_file, run))
                show(results[-1])
    finally:
        write_faults(before, state_file)
    return results


def line(result: Result) -> str:
    final = result.final or {}
    tokens = final.get("tokens") or {}
    used = (tokens.get("input") or 0) + (tokens.get("output") or 0)
    flag = "  << WRONG WITH HIGH CONFIDENCE" if result.score.confidently_wrong else ""
    report = final.get("report") or {}
    return (
        f"{result.case:<28} #{result.attempt}  {result.score.verdict.upper():<7} "
        f"{report.get('outcome') or '-'}/{result.score.confidence or '-':<7} "
        f"{final.get('tool_calls', '-'):>2} checks {used:>7} tokens {result.seconds:6.0f} s"
        f"{'  (sent back once)' if result.rechecked else ''}{flag}\n"
        f"{'':32}{'; '.join(result.score.reasons)}"
    )


def totals(results: list[Result]) -> str:
    counts = Counter(r.score.verdict for r in results)
    text = ", ".join(f"{v} {counts[v]}" for v in VERDICTS if counts[v])
    worst = sum(r.score.confidently_wrong for r in results)
    return f"{len(results)} runs: {text}" + (
        f" ({worst} wrong with high confidence)" if worst else ""
    )


def save(results: list[Result], folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"eval-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(
        json.dumps(
            {"totals": totals(results), "runs": [r.record() for r in results]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    parser.add_argument("--case", action="append", help="run only this case (repeatable)")
    parser.add_argument("--repeat", type=int, default=1, help="run each case N times")
    parser.add_argument("--pause", type=float, default=0, help="seconds to wait between runs")
    parser.add_argument("--list", action="store_true", help="list the cases and stop")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    settings = get_settings()
    devices = {d.name for d in load_inventory(settings.lab_inventory).devices}
    cases = load_cases(devices, set(load_lab().faults))
    if args.list:
        for case in cases:
            print(f"{case.name:<28} {', '.join(case.faults) or 'healthy':<26} {case.question}")
        return 0
    if args.case:
        unknown = set(args.case) - {c.name for c in cases}
        if unknown:
            print(f"no case named {', '.join(sorted(unknown))} (see --list)")
            return 2
        cases = [c for c in cases if c.name in args.case]

    try:
        check_simulated(API)
    except NotSimulated as refusal:
        print(f"Not run: {refusal}")
        return 2
    print(
        f"{len(cases)} case(s) x {args.repeat} on the simulated lab, model {settings.llm_model}\n"
    )
    results = asyncio.run(
        run_all(
            cases,
            settings,
            repeat=args.repeat,
            pause=args.pause,
            show=lambda r: print(line(r), flush=True),
        )
    )
    print(f"\n{totals(results)}")
    print(f"Saved: {save(results, settings.logs_dir / 'evals')}")
    return 0 if all(r.score.verdict == "right" for r in results) else 1
