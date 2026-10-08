"""The device inventory: which devices exist and how to reach them.

Two files, read together:
- lab/inventory.yaml: written and reviewed by people (comments explain each field);
- lab/inventory.local.yaml: devices engineers added on the Inventory page (inventory_edit.py
  writes it; never edited by hand, not in git).

A name or alias may appear only once across both. No secret is ever in either file: a device
names a login profile (credential_ref) whose username and password are in .env.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

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
    added_by: str | None = None  # set for devices added on the Inventory page
    added_at: str | None = None


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


def local_path(path: Path) -> Path:
    """The file of devices added on the Inventory page, next to the hand-written one."""
    return path.with_name(path.stem + ".local" + path.suffix)


def _device(entry: dict[str, Any]) -> Device:
    if entry["platform"] not in PLATFORMS:
        raise ValueError(f"{entry['name']}: unknown platform {entry['platform']!r}")
    return Device(
        name=entry["name"],
        site=entry["site"],
        role=entry["role"],
        platform=entry["platform"],
        port=int(entry["port"]),
        description=entry.get("description", ""),
        aliases=tuple(entry.get("aliases", [])),
        credential_ref=entry.get("credential_ref"),
        added_by=entry.get("added_by"),
        added_at=entry.get("added_at"),
    )


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_inventory(path: Path) -> Inventory:
    """Both inventory files together. Raises ValueError when a name or alias is used twice."""
    base, local = _read(path), _read(local_path(path))
    sites = {**dict(base.get("sites") or {}), **dict(local.get("sites") or {})}
    devices = []
    for entry in (base.get("devices") or []) + (local.get("devices") or []):
        try:
            devices.append(_device(entry))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"a device entry is not valid ({entry!r}): {error}") from None
    seen: dict[str, str] = {}
    for device in devices:
        for name in (device.name, *device.aliases):
            if name.upper() in seen:
                raise ValueError(f"'{name}' is used twice in the inventory ({seen[name.upper()]})")
            seen[name.upper()] = device.name
    return Inventory(sites=sites, devices=devices)
