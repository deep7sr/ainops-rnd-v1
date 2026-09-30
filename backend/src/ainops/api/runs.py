"""Background runs (investigations, discoveries) whose steps are streamed to any number of viewers.

A run keeps every event it produced. A viewer that connects late (or reconnects) first gets all
earlier events, then the live ones, so the projector and a second laptop always show the same.
Finished investigations are saved to logs/investigations/<id>.json and survive a restart.
"""

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class Run:
    id: str
    kind: str  # "investigation" or "discovery"
    title: str
    started_at: str
    events: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def emit(self, event: dict[str, Any]) -> None:
        async with self.changed:
            self.events.append(event)
            self.changed.notify_all()

    async def finish(self) -> None:
        async with self.changed:
            self.done = True
            self.changed.notify_all()

    async def stream(self) -> AsyncIterator[str]:
        """Server-Sent Events: every event so far, then new ones until the run is done."""
        sent = 0
        while True:

            def ready(seen: int = sent) -> bool:
                return len(self.events) > seen or self.done

            async with self.changed:
                with contextlib.suppress(TimeoutError):  # every 15 s: a keep-alive line
                    await asyncio.wait_for(self.changed.wait_for(ready), timeout=15)
                new = self.events[sent:]
                sent = len(self.events)
                finished = self.done
            if not new and not finished:
                yield ": keep-alive\n\n"
            for event in new:
                yield f"data: {json.dumps(event, default=str)}\n\n"
            if finished and sent == len(self.events):
                yield 'data: {"type": "end"}\n\n'
                return

    def summary(self) -> dict[str, Any]:
        report = next((e for e in reversed(self.events) if e.get("type") == "report"), None)
        error = next((e for e in reversed(self.events) if e.get("type") == "error"), None)
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "started_at": self.started_at,
            "done": self.done,
            "outcome": report["report"]["outcome"] if report else ("error" if error else None),
            "confidence": report["confidence"] if report else None,
            "duration_ms": report["at_ms"] if report else None,
        }


class RunRegistry:
    def __init__(self, history_dir: Path) -> None:
        self.history_dir = history_dir
        self.runs: dict[str, Run] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._load_history()

    def _load_history(self) -> None:
        if not self.history_dir.is_dir():
            return
        for path in sorted(self.history_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            run = Run(raw["id"], raw["kind"], raw["title"], raw["started_at"], raw["events"], True)
            self.runs[run.id] = run

    def start(self, kind: str, title: str, work: Callable[[Run], Awaitable[None]]) -> Run:
        run = Run(
            id=f"{kind[:3]}-{uuid.uuid4().hex[:8]}",
            kind=kind,
            title=title,
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self.runs[run.id] = run

        async def main() -> None:
            try:
                await work(run)
            except Exception as error:  # noqa: BLE001 - shown to the user, never swallowed
                await run.emit({"type": "error", "message": f"{type(error).__name__}: {error}"})
            finally:
                await run.finish()
                if kind == "investigation":
                    self._save(run)

        task = asyncio.create_task(main())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run

    def _save(self, run: Run) -> None:
        self.history_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "id": run.id,
            "kind": run.kind,
            "title": run.title,
            "started_at": run.started_at,
            "events": run.events,
        }
        path = self.history_dir / f"{run.id}.json"
        path.write_text(json.dumps(record, default=str), encoding="utf-8")

    def recent(self, kind: str, limit: int = 30) -> list[dict[str, Any]]:
        runs = [r for r in self.runs.values() if r.kind == kind]
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return [r.summary() for r in runs[:limit]]
