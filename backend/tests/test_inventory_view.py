"""The Inventory page: device status from the last discovery, and what is known per device.

The inventory is the real lab file; the graph is shaped like GraphStore.snapshot(); the case and
the investigation are the samples recorded on the live lab.
"""

import json
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_cases import FAULT, MemoryCases

from ainops.cases import Case
from ainops.config import REPO_ROOT
from ainops.inventory import load_inventory
from ainops.inventory_view import device_detail, device_status, inventory_rows

INVENTORY = load_inventory(REPO_ROOT / "lab" / "inventory.yaml")
CASE = Case.model_validate_json(
    (REPO_ROOT / "fixtures" / "cases" / "samples" / "fault1-corrected.json").read_text("utf-8")
)
AT = "2026-10-07T09:50:00+00:00"


def iface(name: str, status: str, ipv4: list[str], stale: str | None = None) -> dict[str, Any]:
    return {"name": name, "status": status, "ipv4": ipv4, "stale_since": stale}


# The graph after a discovery where FWL-MAA did not answer (its last state is kept) and ISP-MAA-1
# was never reached: a little of everything the page must show.
SNAPSHOT: dict[str, Any] = {
    "devices": [
        {
            "name": d.name,
            "site": d.site,
            "role": d.role,
            "platform": d.platform,
            "description": d.description,
            "interfaces": [iface("Fa0/0", "up", ["10.0.0.1/24"])],
        }
        for d in INVENTORY.devices
        if d.name not in ("IPLC-RTR-MAA", "FWL-MAA", "ISP-MAA-1")
    ]
    + [
        {
            "name": "IPLC-RTR-MAA",
            "site": "MAA",
            "role": "wan-router",
            "platform": "cisco_ios",
            "description": "",
            "interfaces": [
                iface("Fa0/0", "up", ["10.10.5.1/24"]),
                iface("Fa2/0", "administratively down", ["10.10.4.2/24"]),
                iface("Fa1/0", "down", []),
            ],
        },
        {
            "name": "FWL-MAA",
            "site": "MAA",
            "role": "firewall",
            "platform": "juniper_junos",
            "description": "",
            "interfaces": [
                iface("ge-0/0/0", "up", ["10.10.6.2/24"], stale="2026-10-06T08:00:00+00:00")
            ],
        },
    ],
    "links": [
        {
            "key": "k1",
            "a": "IPLC-RTR-TRV",
            "a_interface": "Fa2/0",
            "b": "IPLC-RTR-MAA",
            "b_interface": "Fa2/0",
            "subnet": "10.10.4.0/24",
            "sources": ["cdp"],
        },
        {
            "key": "k2",
            "a": "CORE-SW-TRV",
            "a_interface": "Fa2/0",
            "b": "IPLC-RTR-TRV",
            "b_interface": "Fa0/0",
            "subnet": "10.10.3.0/24",
            "sources": ["cdp"],
        },
    ],
    "ospf_peers": [
        {
            "device": "IPLC-RTR-MAA",
            "peer": "IPLC-RTR-TRV",
            "interface": "Fa2/0",
            "address": "10.10.4.1",
            "neighbor_id": "1.1.1.1",
        },
        {
            "device": "IPLC-RTR-TRV",
            "peer": "IPLC-RTR-MAA",
            "interface": "Fa2/0",
            "address": "10.10.4.2",
            "neighbor_id": "2.2.2.2",
        },
    ],
    "discovery": {
        "at": AT,
        "source": "live",
        "devices_ok": [d.name for d in INVENTORY.devices if d.name not in ("FWL-MAA", "ISP-MAA-1")],
        "devices_failed": [
            "FWL-MAA: NetmikoAuthenticationException: login failed",
            "ISP-MAA-1: TimeoutError",
        ],
    },
}


def rows() -> dict[str, dict[str, Any]]:
    return {r["name"]: r for r in inventory_rows(INVENTORY, SNAPSHOT, [CASE])}


# ---------- status ----------


def test_a_device_that_answered_the_last_discovery_is_reached() -> None:
    status = rows()["IPLC-RTR-TRV"]["status"]
    assert status == {"state": "reached", "at": AT, "last_seen": AT, "error": None}


def test_a_device_that_did_not_answer_says_since_when_and_why() -> None:
    status = rows()["FWL-MAA"]["status"]
    assert status == {
        "state": "not_reached",
        "at": AT,
        "last_seen": "2026-10-06T08:00:00+00:00",
        "error": "NetmikoAuthenticationException: login failed",
    }


def test_a_device_no_discovery_reached_yet_is_not_discovered() -> None:
    assert rows()["ISP-MAA-1"]["status"]["state"] == "not_discovered"
    assert device_status("X", {"interfaces": []}, None)["state"] == "not_discovered"


def test_every_inventory_device_is_listed_even_without_the_graph() -> None:
    listed = inventory_rows(INVENTORY, None, None)
    assert [r["name"] for r in listed] == [d.name for d in INVENTORY.devices]
    assert {r["status"]["state"] for r in listed} == {"not_discovered"}
    assert {str(r["cases"]) for r in listed} == {"None"}  # unknown, not zero


# ---------- what a row shows ----------


def test_a_row_shows_how_the_device_is_reached_but_never_a_secret() -> None:
    row = rows()["FWL-TRV"]
    assert row["site_name"] == "Trivandrum"
    assert row["connection"] == "EVE-NG console, port 32771"
    assert row["credential_ref"] == "lab-srx-admin"
    assert not any("password" in key.lower() for key in row)
    assert "AINOPS_CRED" not in json.dumps(row)


def test_interfaces_with_an_address_but_down_are_counted() -> None:
    assert rows()["IPLC-RTR-MAA"]["interfaces"] == {"total": 3, "addressed": 2, "addressed_down": 1}


def test_cases_are_counted_per_device() -> None:
    assert rows()["IPLC-RTR-MAA"]["cases"] == {"total": 1, "pending": 0}
    assert rows()["CORE-SW-TRV"]["cases"] == {"total": 0, "pending": 0}


# ---------- one device ----------

RUNS = [
    {
        "id": "inv-fault1",
        "title": FAULT["title"],
        "started_at": FAULT["started_at"],
        "events": FAULT["events"],
        "summary": {"outcome": "diagnosed"},
    }
]


def test_the_detail_has_graph_facts_cases_and_the_investigations_that_checked_it() -> None:
    detail = device_detail(INVENTORY, INVENTORY.get("MAA-P2P"), SNAPSHOT, [CASE], RUNS)
    assert detail["row"]["name"] == "IPLC-RTR-MAA"
    assert detail["row"]["site_name"] == "Chennai"
    assert [i["name"] for i in detail["interfaces"]] == ["Fa0/0", "Fa2/0", "Fa1/0"]
    assert [link["key"] for link in detail["links"]] == ["k1"]
    assert [p["peer"] for p in detail["ospf_peers"]] == ["IPLC-RTR-TRV"]
    assert [c["id"] for c in detail["cases"]] == [CASE.id]
    assert detail["investigations"] == [
        {
            "id": "inv-fault1",
            "title": FAULT["title"],
            "started_at": FAULT["started_at"],
            "outcome": "diagnosed",
            "checks": 1,
        }
    ]


def test_a_device_never_checked_has_no_investigations() -> None:
    detail = device_detail(INVENTORY, INVENTORY.get("ISP-TRV-1"), SNAPSHOT, [CASE], RUNS)
    assert detail["investigations"] == []
    assert detail["cases"] == []


# ---------- the API ----------


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Any:
    from ainops.api import app as module

    book = MemoryCases()
    book.save(CASE)

    class Graph:
        def snapshot(self) -> dict[str, Any]:
            return SNAPSHOT

    monkeypatch.setattr(module, "store", lambda: Graph())
    monkeypatch.setattr(module, "cases", lambda: book)
    return module


def test_the_inventory_api(api: Any) -> None:
    body = TestClient(api.app).get("/api/inventory").json()
    assert len(body["devices"]) == len(INVENTORY.devices)
    assert body["sites"] == {"TRV": "Trivandrum", "MAA": "Chennai"}
    assert body["discovery"]["at"] == AT
    assert body["graph_error"] is None


def test_without_the_graph_the_inventory_still_lists_the_devices(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down() -> Any:
        raise ConnectionError("Neo4j is not running")

    monkeypatch.setattr(api, "store", down)
    body = TestClient(api.app).get("/api/inventory").json()
    assert len(body["devices"]) == len(INVENTORY.devices)
    assert body["graph_error"] == "knowledge graph not reachable: ConnectionError"


def test_one_device_by_name_or_alias_and_an_unknown_one(api: Any) -> None:
    client = TestClient(api.app)
    assert client.get("/api/inventory/maa-p2p").json()["row"]["name"] == "IPLC-RTR-MAA"
    missing = client.get("/api/inventory/ROUTER-X")
    assert missing.status_code == 404
    assert "Known devices:" in missing.json()["detail"]


# ---------- the samples the frontend tests read ----------


@pytest.mark.parametrize("name", ["inventory", "device"])
def test_the_samples_the_frontend_tests_read_match_the_code(name: str) -> None:
    """After changing what the page gets: AINOPS_WRITE_SAMPLES=1 pytest -k samples"""
    if name == "inventory":
        produced: Any = {
            "devices": inventory_rows(INVENTORY, SNAPSHOT, [CASE]),
            "sites": INVENTORY.sites,
            "discovery": SNAPSHOT["discovery"],
            "graph_error": None,
        }
    else:
        detail = device_detail(INVENTORY, INVENTORY.get("IPLC-RTR-MAA"), SNAPSHOT, [CASE], RUNS)
        produced = {**detail, "graph_error": None}
    path = REPO_ROOT / "fixtures" / "inventory" / "samples" / f"{name}.json"
    if os.environ.get("AINOPS_WRITE_SAMPLES"):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(produced, indent=2, ensure_ascii=False) + "\n")
    assert json.loads(path.read_text(encoding="utf-8")) == produced, "rewrite the samples"
