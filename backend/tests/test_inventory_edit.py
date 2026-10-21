"""Adding and removing devices on the Inventory page.

Every test works on a copy of the real lab inventory in a temporary folder: the real files are
never touched.
"""

import shutil
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ainops.config import REPO_ROOT
from ainops.inventory import UnknownDeviceError, load_inventory, local_path
from ainops.inventory_edit import (
    InventoryError,
    NewDevice,
    add_device,
    credential_profiles,
    remove_device,
)

PROFILES = ["lab-ios-admin", "lab-srx-admin"]


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "inventory.yaml"
    shutil.copy(REPO_ROOT / "lab" / "inventory.yaml", path)
    return path


def new(**changes: Any) -> NewDevice:
    fields: dict[str, Any] = {
        "name": "BRANCH-RTR-1",
        "site": "TRV",
        "role": "branch-router",
        "platform": "cisco_ios",
        "port": 32790,
        "aliases": ["BR1"],
        "description": "Test branch router",
        "credential_ref": "lab-ios-admin",
        "added_by": "Deependra",
    }
    return NewDevice(**{**fields, **changes})


# ---------- adding ----------


def test_an_added_device_goes_to_the_local_file_and_the_hand_written_one_is_untouched(
    base: Path,
) -> None:
    before = base.read_bytes()
    device = add_device(base, new(), PROFILES, now="2026-10-08T10:00:00+00:00")
    assert base.read_bytes() == before
    assert (device.name, device.aliases, device.added_by) == ("BRANCH-RTR-1", ("BR1",), "Deependra")
    assert load_inventory(base).get("br1").name == "BRANCH-RTR-1"
    text = local_path(base).read_text("utf-8")
    assert text.startswith("# Devices added on the AINOPS Inventory page.")
    entry = yaml.safe_load(text)["devices"][0]
    assert entry == {
        "name": "BRANCH-RTR-1",
        "site": "TRV",
        "role": "branch-router",
        "platform": "cisco_ios",
        "port": 32790,
        "aliases": ["BR1"],
        "credential_ref": "lab-ios-admin",
        "description": "Test branch router",
        "added_by": "Deependra",
        "added_at": "2026-10-08T10:00:00+00:00",
    }


def test_a_new_site_needs_its_name_and_is_added_with_the_device(base: Path) -> None:
    with pytest.raises(InventoryError, match="BLR is a new site: give its name too"):
        add_device(base, new(site="blr"), PROFILES)
    add_device(base, new(site="blr", site_name="Bengaluru"), PROFILES)
    assert load_inventory(base).sites["BLR"] == "Bengaluru"


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"name": "iplc-rtr-maa"}, "'iplc-rtr-maa' is already used by IPLC-RTR-MAA"),
        ({"aliases": ["MAA-P2P"]}, "'MAA-P2P' is already used by IPLC-RTR-MAA"),
        ({"aliases": ["branch-rtr-1"]}, "the name and aliases must all be different"),
        ({"port": 32776}, "console port 32776 is already IPLC-RTR-MAA's"),
        ({"credential_ref": "made-up"}, "there is no login profile 'made-up' in .env"),
        ({"added_by": "   "}, "type your name"),
    ],
)
def test_each_rule_is_explained(base: Path, changes: dict[str, Any], problem: str) -> None:
    with pytest.raises(InventoryError, match=problem):
        add_device(base, new(**changes), PROFILES)
    assert not local_path(base).exists()  # nothing written


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "has space"},
        {"name": ""},
        {"platform": "fortios"},
        {"port": 0},
        {"site": "Trivandrum!"},
        {"aliases": ["bad alias"]},
        {"aliases": ["a", "b", "c", "d", "e", "f"]},
        {"description": "x" * 201},
    ],
)
def test_bad_input_is_refused_before_anything_is_checked(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        new(**changes)


def test_a_device_without_a_login_profile_is_allowed(base: Path) -> None:
    device = add_device(base, new(credential_ref=None), PROFILES)
    assert device.credential_ref is None


def test_two_adds_at_the_same_moment_both_land(base: Path) -> None:
    def add(n: int) -> None:
        add_device(base, new(name=f"BR-{n}", aliases=[], port=33000 + n), PROFILES)

    threads = [threading.Thread(target=add, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    names = {d.name for d in load_inventory(base).devices}
    assert {f"BR-{n}" for n in range(8)} <= names


def test_a_name_in_both_files_is_an_error(base: Path) -> None:
    local_path(base).write_text(
        "devices:\n  - {name: CORE-SW-MAA, site: MAA, role: core, platform: cisco_ios, port: 1}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="'CORE-SW-MAA' is used twice"):
        load_inventory(base)


# ---------- login profiles ----------


def test_login_profiles_are_names_from_env_never_values() -> None:
    environ = {
        "AINOPS_CRED_LAB_SRX_ADMIN_USERNAME": "admin",
        "AINOPS_CRED_LAB_SRX_ADMIN_PASSWORD": "secret-value",
        "AINOPS_CRED_EMPTY_USERNAME": "",
        "OTHER_USERNAME": "x",
    }
    assert credential_profiles(environ) == ["lab-srx-admin"]


# ---------- removing ----------


def test_only_devices_added_on_the_page_can_be_removed(base: Path) -> None:
    add_device(base, new(site="BLR", site_name="Bengaluru"), PROFILES)
    with pytest.raises(InventoryError, match="hand-written inventory file"):
        remove_device(base, "IPLC-RTR-MAA", "Deependra")
    with pytest.raises(UnknownDeviceError):
        remove_device(base, "NOPE", "Deependra")
    with pytest.raises(InventoryError, match="type your name"):
        remove_device(base, "BR1", " ")
    assert remove_device(base, "BR1", "Deependra").name == "BRANCH-RTR-1"
    inventory = load_inventory(base)
    assert "BRANCH-RTR-1" not in {d.name for d in inventory.devices}
    assert "BLR" not in inventory.sites  # the site it brought goes with it
    assert len(inventory.devices) == 8


# ---------- the network MCP sees the change without a restart ----------


def test_the_network_server_reads_the_inventory_again_after_a_change(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ainops.network import server

    class Graph:
        def __init__(self, *args: object) -> None:
            pass

        def owner_of_ip(self, address: str) -> list[dict[str, Any]]:
            return []

        def ospf_peers(self, device: str | None = None) -> list[dict[str, Any]]:
            return []

        def links(self, device: str | None = None) -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr(server, "GraphStore", Graph)
    monkeypatch.setattr(server.settings, "lab_eve_host", "eve.test")
    monkeypatch.setattr(server.settings, "lab_inventory", base)
    monkeypatch.setattr(server, "_service", None)
    assert len(server.service().inventory.devices) == 8
    add_device(base, new(), PROFILES)
    assert server.service().inventory.get("BR1").name == "BRANCH-RTR-1"
    # A broken file never takes the devices away: the last good inventory stays.
    local_path(base).write_text("devices:\n  - {name: CORE-SW-MAA}\n", encoding="utf-8")
    assert len(server.service().inventory.devices) == 9


# ---------- the API ----------


@pytest.fixture
def api(base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from ainops.api import app as module

    monkeypatch.setattr(module.settings, "lab_inventory", base)
    monkeypatch.setattr(module.settings, "logs_dir", tmp_path / "logs")
    monkeypatch.setenv("AINOPS_CRED_LAB_IOS_ADMIN_USERNAME", "user-value-never-shown")
    return module


BODY = {
    "name": "BRANCH-RTR-1",
    "site": "TRV",
    "role": "branch-router",
    "platform": "cisco_ios",
    "port": 32790,
    "aliases": ["BR1"],
    "credential_ref": "lab-ios-admin",
    "added_by": "Deependra",
}


def test_the_form_options_name_the_login_profiles_only(api: Any) -> None:
    options = TestClient(api.app).get("/api/inventory/options").json()
    assert "lab-ios-admin" in options["credential_profiles"]
    assert options["platforms"] == ["cisco_ios", "juniper_junos"]
    assert "wan-router" in options["roles"]
    assert options["sites"] == {"TRV": "Trivandrum", "MAA": "Chennai"}
    assert "user-value-never-shown" not in str(options)


def test_add_and_remove_through_the_api_with_an_audit_entry_each(api: Any) -> None:
    client = TestClient(api.app)
    added = client.post("/api/inventory", json=BODY)
    assert added.status_code == 200
    assert added.json()["added"]["by"] == "Deependra"
    assert added.json()["status"]["state"] == "not_discovered"
    again = client.post("/api/inventory", json=BODY)
    assert (again.status_code, again.json()["detail"]) == (
        409,
        "'BRANCH-RTR-1' is already used by BRANCH-RTR-1",
    )
    assert client.post("/api/inventory", json={**BODY, "port": "x"}).status_code == 422

    assert (
        client.post("/api/inventory/IPLC-RTR-MAA/remove", json={"removed_by": "D"}).status_code
        == 409
    )
    assert client.post("/api/inventory/NOPE/remove", json={"removed_by": "D"}).status_code == 404
    gone = client.post("/api/inventory/BR1/remove", json={"removed_by": "Deependra"})
    assert gone.json() == {"removed": "BRANCH-RTR-1"}

    audit = api.AuditLog(api.settings.logs_dir / "network-audit.jsonl").tail()
    assert [(e["tool"], e["device"], e["summary"]) for e in audit] == [
        ("add_device", "BRANCH-RTR-1", "added to the inventory by Deependra"),
        ("remove_device", "BRANCH-RTR-1", "removed from the inventory by Deependra"),
    ]
    assert all(e["source"] == "inventory" and e["command"] is None for e in audit)
