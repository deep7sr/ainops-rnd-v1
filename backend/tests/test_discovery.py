"""Link building from device answers: the recorded Cisco outputs of the lab plus hand-written
firewall interfaces (the vSRX JSON outputs are not recorded yet; addresses from the earlier
`show interfaces terse` recording)."""

from pathlib import Path

import pytest

from ainops.config import REPO_ROOT
from ainops.inventory import load_inventory
from ainops.network.audit import AuditLog
from ainops.network.executor import ReplayExecutor
from ainops.network.service import NetworkService, load_commands
from ainops.topology.discovery import DeviceReport, build_links

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
