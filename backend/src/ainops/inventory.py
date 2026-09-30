"""The device inventory (lab/inventory.yaml): which devices exist and how to reach them."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

Platform = Literal["cisco_ios", "juniper_junos"]
PLATFORMS: tuple[Platform, ...] = ("cisco_ios", "juniper_junos")


class UnknownDeviceError(LookupError):
    """The name is not a device or alias in the inventory. The message lists the valid names."""


@dataclass(frozen=True)
class Device:
    name: str
    site: str
    role: str
    platform: Platform
    port: int
    description: str = ""
    aliases: tuple[str, ...] = ()
    credential_ref: str | None = None


@dataclass(frozen=True)
class Inventory:
    sites: dict[str, str]
    devices: list[Device] = field(default_factory=list)

    def get(self, name: str) -> Device:
        """Find a device by name or alias, ignoring case and surrounding spaces."""
        wanted = name.strip().upper()
        for device in self.devices:
            if wanted == device.name.upper() or wanted in (a.upper() for a in device.aliases):
                return device
        names = ", ".join(d.name for d in self.devices)
        raise UnknownDeviceError(f"'{name}' is not in the inventory. Known devices: {names}")


def load_inventory(path: Path) -> Inventory:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    devices = []
    for entry in raw["devices"]:
        if entry["platform"] not in PLATFORMS:
            raise ValueError(f"{entry['name']}: unknown platform {entry['platform']!r}")
        devices.append(
            Device(
                name=entry["name"],
                site=entry["site"],
                role=entry["role"],
                platform=entry["platform"],
                port=int(entry["port"]),
                description=entry.get("description", ""),
                aliases=tuple(entry.get("aliases", [])),
                credential_ref=entry.get("credential_ref"),
            )
        )
    return Inventory(sites=dict(raw.get("sites", {})), devices=devices)
