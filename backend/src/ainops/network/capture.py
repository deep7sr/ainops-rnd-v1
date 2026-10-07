"""Capture test data on purpose: `ainops capture <name>` runs the read-only tools once on every
device and saves each (redacted) output under fixtures/captures/<name>/<device>/<command>.txt.

This is the only way recorded outputs are made. AINOPS itself never answers from them: they are
test data (the tests replay them to check that the code reads real device output correctly). A
capture never overwrites an existing one, so test data cannot change by accident.
"""

import re
from collections.abc import Callable
from pathlib import Path

from ainops.inventory import Device
from ainops.network.executor import LiveExecutor, RawOutput

CAPTURES = Path(__file__).resolve().parents[4] / "fixtures" / "captures"


def fixture_path(root: Path, device: str, command: str) -> Path:
    """Where the output of `command` on `device` is stored under `root`."""
    slug = re.sub(r"[^a-z0-9]+", "-", command.lower()).strip("-")
    return root / device / f"{slug}.txt"


class CapturingExecutor:
    """The live executor, also saving every output under `folder`."""

    mode = "live"

    def __init__(self, inner: LiveExecutor, folder: Path) -> None:
        if folder.exists():
            raise FileExistsError(f"{folder} already exists: choose another name for the capture")
        self.inner = inner
        self.folder = folder

    def run(self, device: Device, command: str) -> RawOutput:
        raw = self.inner.run(device, command)
        path = fixture_path(self.folder, device.name, command)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw.text, encoding="utf-8", newline="\n")
        return raw

    def close(self) -> None:
        self.inner.close()


def tools_for(platform: str) -> list[str]:
    """The NetworkService tools a capture runs on a device of this platform."""
    common = [
        "get_device_facts",
        "get_interfaces",
        "get_routes",
        "get_ospf_neighbors",
        "get_neighbors",
        "get_arp_table",
    ]
    if platform == "juniper_junos":
        return [*common, "get_firewall_zones", "get_firewall_policies"]
    return [*common, "get_routing_protocols"]


Report = Callable[[str], None]
