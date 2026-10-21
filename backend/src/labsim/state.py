"""What the running simulator knows at a moment: the lab with its faults applied, the ARP tables,
and when it started (uptimes) and last changed (route ages).

Which faults are on is kept in a small JSON file (logs/labsim/state.json, not in git), so
`labsim fault <name>` in another window changes the running simulator: it reads the file again
whenever the file changes.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from labsim.model import REPO_ROOT, Lab, apply_faults
from labsim.network import ArpCache

STATE_FILE = Path(os.environ.get("LABSIM_STATE", REPO_ROOT / "logs" / "labsim" / "state.json"))


@dataclass
class View:
    """Everything a command's answer is worked out from."""

    lab: Lab
    cache: ArpCache
    started: float  # time.time() when the simulator started (device uptime)
    changed: float  # when the faults last changed (age of the routes)
    now: float


def read_faults(path: Path = STATE_FILE) -> tuple[list[str], float | None]:
    if not path.is_file():
        return [], None
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(n) for n in data.get("faults", [])], data.get("changed")


def write_faults(names: list[str], path: Path = STATE_FILE) -> None:
    """Atomically, so the running simulator never reads half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"faults": names, "changed": time.time()}, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


class Simulator:
    def __init__(self, base: Lab, state_file: Path = STATE_FILE) -> None:
        self.base = base
        self.state_file = state_file
        self.started = time.time()
        self.faults: list[str] = []
        self.lab = base
        self.changed = self.started
        self.cache = ArpCache.seeded(base, self.started)
        self._stamp: tuple[int, int] | None = None
        self.refresh()

    def refresh(self) -> None:
        """Pick up a change of faults made with `labsim fault` / `labsim heal`."""
        try:
            info = self.state_file.stat() if self.state_file.is_file() else None
        except OSError:
            return
        stamp = (info.st_mtime_ns, info.st_size) if info else None
        if stamp == self._stamp:
            return
        self._stamp = stamp
        names, changed = read_faults(self.state_file)
        names = [n for n in names if n in self.base.faults]  # an unknown name is ignored
        if names != self.faults:
            self.lab = apply_faults(self.base, names)
            self.faults = names
            self.changed = changed or time.time()

    def view(self) -> View:
        self.refresh()
        return View(self.lab, self.cache, self.started, self.changed, time.time())
