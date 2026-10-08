"""Adding and removing devices on the Inventory page.

Added devices go to lab/inventory.local.yaml (inventory.local_path), never to the hand-written
lab/inventory.yaml, whose comments a program would lose. Only devices added here can be removed
here; the hand-written ones are changed in their file.

A device never carries a secret: it names a login profile (credential_ref), and the username and
password stay in .env (AINOPS_CRED_<PROFILE>_USERNAME / _PASSWORD). The page can only pick one of
the profiles .env already has. After a device is added, AINOPS can log in to it, read-only.

Every add and remove is written to the audit log with the name the engineer typed.
"""

import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from ainops.inventory import PLATFORMS, Device, Platform, load_inventory, local_path

_NAME = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$"
_SITE = r"^[A-Z0-9]{2,10}$"
_CRED = re.compile(r"^AINOPS_CRED_([A-Z0-9_]+)_USERNAME$")
_LOCK = threading.Lock()  # one change at a time: two adds at once must not lose one


class InventoryError(Exception):
    """A change the inventory cannot take; the message says why (shown to the engineer)."""


class NewDevice(BaseModel):
    name: str = Field(pattern=_NAME)
    site: str = Field(pattern=_SITE)
    site_name: str | None = Field(default=None, max_length=60)  # needed for a new site
    role: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,30}$")
    platform: Platform
    port: int = Field(ge=1, le=65535)  # the EVE-NG console port (lab); production: an address
    aliases: list[str] = Field(default_factory=list, max_length=5)
    description: str = Field(default="", max_length=200)
    credential_ref: str | None = Field(default=None, max_length=40)
    added_by: str = Field(max_length=80)

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, value: list[str]) -> list[str]:
        cleaned = [a.strip() for a in value if a.strip()]
        for alias in cleaned:
            if not re.fullmatch(_NAME, alias):
                raise ValueError(f"'{alias}' is not a valid alias (letters, digits, . _ -)")
        return cleaned

    @field_validator("site", mode="before")
    @classmethod
    def _site(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


def credential_profiles(environ: dict[str, str] | None = None) -> list[str]:
    """The login profiles .env has (names only, never values), as an inventory names them."""
    environ = dict(os.environ) if environ is None else environ
    found = []
    for key, value in environ.items():
        match = _CRED.match(key)
        if match and value:
            found.append(match.group(1).lower().replace("_", "-"))
    return sorted(found)


def _write_atomically(path: Path, data: dict[str, Any]) -> None:
    """Write the whole file or nothing (a crash never leaves half a file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "# Devices added on the AINOPS Inventory page. Written by AINOPS: do not edit by hand.\n"
        "# No secret is ever stored here (credential_ref names a login profile in .env).\n"
        + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    )
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".inventory-", suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    os.replace(temp, path)


def _local(base: Path) -> dict[str, Any]:
    path = local_path(base)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    return {
        "sites": dict((data or {}).get("sites") or {}),
        "devices": list((data or {}).get("devices") or []),
    }


def add_device(base: Path, new: NewDevice, profiles: list[str], now: str | None = None) -> Device:
    """Check the rules, then add the device to the local inventory file."""
    with _LOCK:
        return _add(base, new, profiles, now)


def _add(base: Path, new: NewDevice, profiles: list[str], now: str | None) -> Device:
    added_by = " ".join(new.added_by.split())
    if not added_by:
        raise InventoryError("type your name: every change says who made it")
    inventory = load_inventory(base)
    taken = {n.upper(): d.name for d in inventory.devices for n in (d.name, *d.aliases)}
    for name in (new.name, *new.aliases):
        if name.upper() in taken:
            raise InventoryError(f"'{name}' is already used by {taken[name.upper()]}")
    if len({a.upper() for a in (new.name, *new.aliases)}) != 1 + len(new.aliases):
        raise InventoryError("the name and aliases must all be different")
    if new.site not in inventory.sites and not (new.site_name or "").strip():
        raise InventoryError(f"{new.site} is a new site: give its name too")
    used = next((d for d in inventory.devices if d.port == new.port), None)
    if used is not None:
        raise InventoryError(f"console port {new.port} is already {used.name}'s")
    if new.credential_ref is not None and new.credential_ref not in profiles:
        known = ", ".join(profiles) or "none"
        raise InventoryError(
            f"there is no login profile '{new.credential_ref}' in .env (profiles: {known})"
        )
    if new.platform not in PLATFORMS:  # also checked by the model; kept for clarity
        raise InventoryError(f"AINOPS cannot talk to {new.platform} devices yet")

    local = _local(base)
    if new.site not in inventory.sites:
        local["sites"][new.site] = " ".join((new.site_name or "").split())
    entry: dict[str, Any] = {
        "name": new.name,
        "site": new.site,
        "role": new.role,
        "platform": new.platform,
        "port": new.port,
    }
    if new.aliases:
        entry["aliases"] = new.aliases
    if new.credential_ref:
        entry["credential_ref"] = new.credential_ref
    if new.description.strip():
        entry["description"] = " ".join(new.description.split())
    entry["added_by"] = added_by
    entry["added_at"] = now or datetime.now(UTC).isoformat(timespec="seconds")
    local["devices"].append(entry)
    _write_atomically(local_path(base), local)
    return load_inventory(base).get(new.name)


def remove_device(base: Path, name: str, removed_by: str) -> Device:
    """Remove a device that was added on the Inventory page (never a hand-written one)."""
    with _LOCK:
        return _remove(base, name, removed_by)


def _remove(base: Path, name: str, removed_by: str) -> Device:
    if not " ".join(removed_by.split()):
        raise InventoryError("type your name: every change says who made it")
    device = load_inventory(base).get(name)  # UnknownDeviceError for an unknown name
    local = _local(base)
    kept = [e for e in local["devices"] if e.get("name") != device.name]
    if len(kept) == len(local["devices"]):
        raise InventoryError(
            f"{device.name} is in the hand-written inventory file: change it there, not here"
        )
    local["devices"] = kept
    # A site added on the page goes when its last added device goes.
    used = {e.get("site") for e in kept}
    local["sites"] = {code: n for code, n in local["sites"].items() if code in used}
    _write_atomically(local_path(base), local)
    return device
