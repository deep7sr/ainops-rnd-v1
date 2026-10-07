"""Background runs (investigations, discoveries) whose steps are streamed to any number of viewers.

A run keeps every event it produced. A viewer that connects late (or reconnects) first gets all
earlier events, then the live ones, so the projector and a second laptop always show the same.
Every event is numbered (the SSE id), so a viewer that reconnects gets only what it missed.
Finished investigations are saved to logs/investigations/<id>.json and survive a restart.

An investigation is a conversation: after a reply the engineer can send a follow-up message, which
starts another turn of the same run (see agent/conversation.py). One turn at a time, and the
engineer can stop the one that is running.
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

from ainops.agent.conversation import MAX_MESSAGES, message_count


class Refused(Exception):
    """A request the run cannot take now; the message says why (shown to the engineer)."""


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

    async def stream(self, after: int = 0) -> AsyncIterator[str]:
        """Server-Sent Events: every event after the first `after`, then new ones until done."""
        sent = min(max(after, 0), len(self.events))
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
            for number, event in enumerate(new, start=sent - len(new) + 1):
                yield f"id: {number}\ndata: {json.dumps(event, default=str)}\n\n"
            if finished and sent == len(self.events):
                yield 'data: {"type": "end"}\n\n'
                return

    def summary(self) -> dict[str, Any]:
        """The run as listed in History: how its latest turn ended."""
        start = max((i for i, e in enumerate(self.events) if e.get("type") == "message"), default=0)
        latest = self.events[start:]
        report = next((e for e in reversed(latest) if e.get("type") == "report"), None)
        ended = next((e["type"] for e in latest if e.get("type") in ("error", "stopped")), None)
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "started_at": self.started_at,
            "done": self.done,
            "outcome": report["report"]["outcome"] if report else ended,
            "confidence": report["confidence"] if report else None,
            "duration_ms": report["at_ms"] if report else None,
            "messages": message_count(self.events),
        }


class RunRegistry:
    def __init__(self, history_dir: Path) -> None:
        self.history_dir = history_dir
        self.runs: dict[str, Run] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}  # the turn running now, per run
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
        self._launch(run, work)
        return run

    def _launch(self, run: Run, work: Callable[[Run], Awaitable[None]]) -> None:
        async def main() -> None:
            try:
                await work(run)
            except asyncio.CancelledError:  # the engineer pressed Stop
                current = asyncio.current_task()
                if current is not None:
                    current.uncancel()
                await run.emit({"type": "stopped", "message": "Stopped by the engineer."})
            except Exception as error:  # noqa: BLE001 - shown to the user, never swallowed
                await run.emit({"type": "error", "message": f"{type(error).__name__}: {error}"})
            finally:
                self._tasks.pop(run.id, None)
                await run.finish()
                if run.kind == "investigation":
                    self._save(run)

        self._tasks[run.id] = asyncio.create_task(main())

    def _conversation(self, run_id: str) -> Run:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.kind != "investigation":
            raise Refused("only an investigation can take messages or be stopped")
        return run

    async def follow_up(
        self, run_id: str, text: str, work: Callable[[Run], Awaitable[None]]
    ) -> int:
        """Start the next turn of a conversation. Returns its number (2 for the first follow-up).

        Raises KeyError for an unknown run and Refused when it cannot take a message now.
        """
        run = self._conversation(run_id)
        if not run.done:
            raise Refused("AINOPS is still working on the last message: wait for it or stop it")
        count = message_count(run.events)
        if count >= MAX_MESSAGES:
            raise Refused(
                f"this conversation has reached {MAX_MESSAGES} messages: "
                "start a new investigation to go on"
            )
        # No await before this line: two messages sent at once cannot both pass the check above.
        run.done = False
        at = datetime.now(UTC).isoformat(timespec="seconds")
        await run.emit({"type": "message", "turn": count + 1, "text": text, "at": at})
        self._launch(run, work)
        return count + 1

    def stop(self, run_id: str) -> None:
        """Stop the turn that is running. Raises KeyError or Refused like follow_up."""
        run = self._conversation(run_id)
        task = self._tasks.get(run.id)
        if task is None or run.done:
            raise Refused("nothing is running in this conversation")
        task.cancel()

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
