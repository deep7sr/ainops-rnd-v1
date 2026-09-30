"""Audit log: one JSON line per tool call (who asked for what, which command ran, the outcome).

Written to logs/network-audit.jsonl. Never contains device output or secrets: only names,
validated arguments, the command, timing and the outcome.
"""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, **entry: Any) -> None:
        record = {"at": datetime.now(UTC).isoformat(timespec="milliseconds"), **entry}
        line = json.dumps(record, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")

    def tail(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
