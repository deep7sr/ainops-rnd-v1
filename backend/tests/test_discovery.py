"""Link building from device answers: the recorded Cisco outputs of the lab plus hand-written
firewall interfaces (the vSRX JSON outputs are not recorded yet; addresses from the earlier
`show interfaces terse` recording)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from replay import ReplayExecutor

from ainops.config import REPO_ROOT
from ainops.inventory import load_inventory
from ainops.network.audit import AuditLog
from ainops.network.service import NetworkService, load_commands
from ainops.topology import discovery
from ainops.topology.discovery import DeviceReport, build_links, plan_update

FIREWALLS = {
    "FWL-TRV": [
        {"name": "ge-0/0/0", "status": "up", "ipv4": ["10.10.1.2/24"]},
        {"name": "ge-0/0/1", "status": "up", "ipv4": ["10.10.2.1/24"]},
    ],
    "FWL-MAA": [
        {"name": "ge-0/0/0", "status": "up", "ipv4": ["10.10.7.2/24"]},
        {"name": "ge-0/0/1", "status": "up", "ipv4": ["10.10.6.1/24"]},
    ],
}


@pytest.fixture
def reports(tmp_path: Path) -> dict[str, DeviceReport]:
    inventory = load_inventory(REPO_ROOT / "lab" / "inventory.yaml")
    service = NetworkService(
        inventory=inventory,
        executor=ReplayExecutor(REPO_ROOT / "fixtures" / "lab", delay_s=0),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        commands=load_commands(),
    )
    result: dict[str, DeviceReport] = {}
    for device in inventory.devices:
        if device.name in FIREWALLS:
            result[device.name] = DeviceReport(interfaces=FIREWALLS[device.name])
        else:
            result[device.name] = DeviceReport(
                interfaces=service.get_interfaces(device.name).data,
                neighbors=service.get_neighbors(device.name).data,
            )
    return result


def test_links_of_the_lab(reports: dict[str, DeviceReport]) -> None:
    inventory = load_inventory(REPO_ROOT / "lab" / "inventory.yaml")
    _, links, findings = build_links(inventory, reports)
    found = {(link.a, link.a_interface, link.b, link.b_interface): link for link in links}
    by_pair = {frozenset((link.a, link.b)): link for link in links}

    leased = by_pair[frozenset(("IPLC-RTR-TRV", "IPLC-RTR-MAA"))]
    assert leased.subnet == "10.10.4.0/24"
    assert leased.sources == ["cdp", "subnet"]  # seen by CDP and by the shared subnet

    # The firewalls are found by subnet only (vSRX does not speak CDP).
    assert by_pair[frozenset(("FWL-MAA", "CORE-SW-MAA"))].sources == ["subnet"]
    assert by_pair[frozenset(("FWL-TRV", "ISP-TRV-1"))].subnet == "10.10.1.0/24"

    # FWL-MAA ge-0/0/0 (10.10.7.2/24) and ISP-MAA-1 Fa1/0 (10.10.8.1/24) do not share a subnet:
    # no link, and both show up as addressed interfaces without a peer.
    assert frozenset(("FWL-MAA", "ISP-MAA-1")) not in by_pair
    assert any(f.startswith("FWL-MAA ge-0/0/0 (10.10.7.2/24") for f in findings)
    assert any(f.startswith("ISP-MAA-1 Fa1/0 (10.10.8.1/24") for f in findings)
    assert len(found) == len(links)


def test_down_interface_and_unknown_neighbour_are_findings() -> None:
    inventory = load_inventory(REPO_ROOT / "lab" / "inventory.yaml")
    reports = {
        "IPLC-RTR-TRV": DeviceReport(
            interfaces=[{"name": "Fa2/0", "status": "up", "ipv4": ["10.10.4.1/24"]}],
            neighbors=[
                {
                    "local_interface": "Fa1/0",
                    "neighbor": "NEW-SW-1",
                    "neighbor_interface": "Gi0/1",
                    "protocol": "cdp",
                }
            ],
        ),
        "IPLC-RTR-MAA": DeviceReport(
            interfaces=[{"name": "Fa2/0", "status": "admin-down", "ipv4": ["10.10.4.2/24"]}]
        ),
    }
    _, links, findings = build_links(inventory, reports)
    assert len(links) == 1
    assert any("not up: IPLC-RTR-MAA Fa2/0 is admin-down" in f for f in findings)
    assert any("'NEW-SW-1'" in f and "not in the inventory" in f for f in findings)


def test_cdp_link_between_different_subnets_is_a_mismatch() -> None:
    inventory = load_inventory(REPO_ROOT / "lab" / "inventory.yaml")
    reports = {
        "ISP-MAA-1": DeviceReport(
            interfaces=[{"name": "Fa1/0", "status": "up", "ipv4": ["10.10.8.1/24"]}],
            neighbors=[
                {
                    "local_interface": "Fa1/0",
                    "neighbor": "CORE-SW-MAA",
                    "neighbor_interface": "Fa0/0",
                    "protocol": "cdp",
                }
            ],
        ),
        "CORE-SW-MAA": DeviceReport(
            interfaces=[{"name": "Fa0/0", "status": "up", "ipv4": ["10.10.7.1/24"]}]
        ),
    }
    _, links, findings = build_links(inventory, reports)
    assert links[0].subnet is None
    assert any(f.startswith("Address mismatch: ISP-MAA-1 Fa1/0") for f in findings)


# ---------- a device (or the whole lab) that does not answer ----------

PREVIOUS_AT = "2026-10-06T10:00:00+00:00"
NOW = "2026-10-07T05:00:00+00:00"


def _iface(name: str, cidr: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": "up", "ipv4": [cidr], **extra}


ANSWERS = {
    "CORE-SW-TRV": [_iface("Fa2/0", "10.10.3.1/24")],
    "IPLC-RTR-TRV": [_iface("Fa0/0", "10.10.3.2/24"), _iface("Fa2/0", "10.10.4.1/24")],
    "IPLC-RTR-MAA": [_iface("Fa2/0", "10.10.4.2/24"), _iface("Fa0/0", "10.10.5.1/24")],
}


def _previous(**stale: str) -> dict[str, Any]:
    """The graph before the run: what the devices answered last time."""
    return {
        "devices": [
            {
                "name": name,
                "interfaces": [{**i, "stale_since": stale.get(name)} for i in interfaces],
            }
            for name, interfaces in ANSWERS.items()
        ],
        "links": [
            {
                "key": "IPLC-RTR-MAA:Fa2/0|IPLC-RTR-TRV:Fa2/0",
                "a": "IPLC-RTR-TRV",
                "a_interface": "Fa2/0",
                "b": "IPLC-RTR-MAA",
                "b_interface": "Fa2/0",
                "subnet": "10.10.4.0/24",
                "sources": ["cdp", "subnet"],
            },
            {
                "key": "CORE-SW-MAA:Fa2/0|IPLC-RTR-MAA:Fa0/0",
                "a": "IPLC-RTR-MAA",
                "a_interface": "Fa0/0",
                "b": "CORE-SW-MAA",
                "b_interface": "Fa2/0",
                "subnet": None,
                "sources": ["cdp"],  # seen only by IPLC-RTR-MAA's CDP
            },
        ],
        "discovery": {"at": PREVIOUS_AT},
    }


def _reports(silent: set[str]) -> dict[str, DeviceReport]:
    return {
        name: DeviceReport(error="did not answer on the console (TimeoutError)")
        if name in silent
        else DeviceReport(interfaces=interfaces)
        for name, interfaces in ANSWERS.items()
    }


@pytest.fixture
def inventory() -> Any:
    return load_inventory(REPO_ROOT / "lab" / "inventory.yaml")


def test_when_no_device_answers_the_graph_is_left_alone(inventory: Any) -> None:
    result = plan_update(inventory, _reports(set(ANSWERS)), _previous(), "live", NOW)
    assert result.graph_updated is False
    assert result.links == [] and result.interfaces == []
    assert len(result.devices_failed) == 3
    assert result.findings == [
        "No device answered: the knowledge graph was not changed (it still shows the discovery "
        f"of {PREVIOUS_AT})"
    ]


def test_a_silent_device_keeps_its_last_known_interfaces_and_links(inventory: Any) -> None:
    result = plan_update(inventory, _reports({"IPLC-RTR-MAA"}), _previous(), "live", NOW)
    assert result.graph_updated is True
    assert result.devices_kept == ["IPLC-RTR-MAA"]
    stale = {i.key: i.stale_since for i in result.interfaces}
    assert stale["IPLC-RTR-MAA:Fa2/0"] == PREVIOUS_AT
    assert stale["IPLC-RTR-TRV:Fa2/0"] is None  # it answered: fresh
    links = {link.key: link for link in result.links}
    # still worked out from the kept addresses, but one end is not fresh
    assert links["IPLC-RTR-MAA:Fa2/0|IPLC-RTR-TRV:Fa2/0"].stale_since == PREVIOUS_AT
    # a CDP link that only the silent device reported is kept as it was
    assert links["CORE-SW-MAA:Fa2/0|IPLC-RTR-MAA:Fa0/0"].sources == ["cdp"]
    assert links["CORE-SW-MAA:Fa2/0|IPLC-RTR-MAA:Fa0/0"].stale_since == PREVIOUS_AT
    assert links["CORE-SW-TRV:Fa2/0|IPLC-RTR-TRV:Fa0/0"].stale_since is None
    assert result.removed_links == []  # nothing is "removed" because a device was silent
    assert result.findings[-1] == (
        f"IPLC-RTR-MAA did not answer: its interfaces and links as of {PREVIOUS_AT} are kept, "
        "marked not refreshed"
    )


def test_a_device_silent_twice_keeps_the_time_it_last_answered(inventory: Any) -> None:
    earlier = "2026-10-05T08:00:00+00:00"
    previous = _previous(**{"IPLC-RTR-MAA": earlier})
    result = plan_update(inventory, _reports({"IPLC-RTR-MAA"}), previous, "live", NOW)
    assert {i.stale_since for i in result.interfaces if i.device == "IPLC-RTR-MAA"} == {earlier}


def test_a_silent_device_never_seen_before_has_nothing_to_keep(inventory: Any) -> None:
    previous = _previous()
    previous["devices"] = [d for d in previous["devices"] if d["name"] != "IPLC-RTR-MAA"]
    previous["links"] = []
    result = plan_update(inventory, _reports({"IPLC-RTR-MAA"}), previous, "live", NOW)
    assert result.devices_kept == []
    assert all(i.device != "IPLC-RTR-MAA" for i in result.interfaces)


def test_when_everything_answers_nothing_is_stale(inventory: Any) -> None:
    result = plan_update(inventory, _reports(set()), _previous(), "live", NOW)
    assert result.devices_kept == []
    assert all(i.stale_since is None for i in result.interfaces)
    assert all(link.stale_since is None for link in result.links)
    # IPLC-RTR-MAA answered and no longer reports the CDP link: it is not kept. (It is not listed
    # as removed: CORE-SW-MAA, the other end, was not asked in this test.)
    assert "CORE-SW-MAA:Fa2/0|IPLC-RTR-MAA:Fa0/0" not in {link.key for link in result.links}
    assert result.removed_links == []


class FakeStore:
    def __init__(self, previous: dict[str, Any]) -> None:
        self.previous = previous
        self.written: list[tuple[Any, ...]] = []

    def snapshot(self) -> dict[str, Any]:
        return self.previous

    def replace_topology(self, *args: Any) -> None:
        self.written.append(args)


@pytest.mark.parametrize(("silent", "writes"), [(set(ANSWERS), 0), ({"IPLC-RTR-MAA"}, 1)])
def test_discover_writes_the_graph_only_when_someone_answered(
    inventory: Any, monkeypatch: pytest.MonkeyPatch, silent: set[str], writes: int
) -> None:
    async def fake_collect(*args: Any) -> tuple[dict[str, DeviceReport], str]:
        return _reports(silent), "live"

    monkeypatch.setattr(discovery, "collect", fake_collect)
    store = FakeStore(_previous())
    result = asyncio.run(discovery.discover("http://x", inventory, store, None))  # type: ignore[arg-type]
    assert len(store.written) == writes
    if writes:
        _, interfaces, _, summary, _ = store.written[0]
        assert summary["devices_kept"] == ["IPLC-RTR-MAA"]
        assert any(i.stale_since for i in interfaces)
    assert result.graph_updated is bool(writes)
