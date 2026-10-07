"""A missing OSPF neighbour: learned at discovery and reported by the OSPF check (fixtures/ospf:
live lab outputs of 2026-10-07)."""

from pathlib import Path
from typing import Any

from replay import ReplayExecutor

from ainops.config import REPO_ROOT
from ainops.inventory import load_inventory
from ainops.network import health, parsers
from ainops.network.audit import AuditLog
from ainops.network.service import NetworkService, load_commands
from ainops.topology.discovery import DeviceReport, ospf_peers
from ainops.topology.graph import InterfaceFact, LinkFact

OSPF = REPO_ROOT / "fixtures" / "ospf"

INTERFACES = [
    InterfaceFact("CORE-SW-TRV", "Fa2/0", "up", ["10.10.3.1/24"]),
    InterfaceFact("IPLC-RTR-TRV", "Fa0/0", "up", ["10.10.3.2/24"]),
    InterfaceFact("IPLC-RTR-TRV", "Fa2/0", "up", ["10.10.4.1/24"]),
    InterfaceFact("IPLC-RTR-MAA", "Fa2/0", "up", ["10.10.4.2/24"]),
    InterfaceFact("IPLC-RTR-MAA", "Fa0/0", "up", ["10.10.5.1/24"]),
    InterfaceFact("CORE-SW-MAA", "Fa2/0", "up", ["10.10.5.2/24"]),
]
LINKS = [
    LinkFact("CORE-SW-TRV", "Fa2/0", "IPLC-RTR-TRV", "Fa0/0", "10.10.3.0/24", ["cdp"]),
    LinkFact("IPLC-RTR-TRV", "Fa2/0", "IPLC-RTR-MAA", "Fa2/0", "10.10.4.0/24", ["cdp"]),
    LinkFact("IPLC-RTR-MAA", "Fa0/0", "CORE-SW-MAA", "Fa2/0", "10.10.5.0/24", ["cdp"]),
]


def _table(state: str, device: str) -> list[dict[str, Any]]:
    text = (OSPF / state / device / "show-ip-ospf-neighbor.txt").read_text(encoding="utf-8")
    return parsers.ospf_neighbors("cisco_ios", text)


def _learned(state: str = "healthy") -> list[dict[str, Any]]:
    """What discovery stores for the leased-line routers, as GraphStore.ospf_peers returns it."""
    reports = {d: DeviceReport(ospf=_table(state, d)) for d in ("IPLC-RTR-TRV", "IPLC-RTR-MAA")}
    return [vars(p) for p in ospf_peers(reports, INTERFACES, LINKS, previous=[])]


# ---------- discovery learns the normal neighbours ----------


def test_discovery_learns_each_full_neighbour_with_its_device() -> None:
    peers = {(p["device"], p["peer"], p["interface"], p["address"]) for p in _learned()}
    assert peers == {
        ("IPLC-RTR-TRV", "IPLC-RTR-MAA", "Fa2/0", "10.10.4.2"),
        ("IPLC-RTR-TRV", "CORE-SW-TRV", "Fa0/0", "10.10.3.1"),
        ("IPLC-RTR-MAA", "IPLC-RTR-TRV", "Fa2/0", "10.10.4.1"),
        ("IPLC-RTR-MAA", "CORE-SW-MAA", "Fa0/0", "10.10.5.2"),
    }


def test_a_neighbour_not_full_or_not_known_is_not_learned() -> None:
    rows = [
        {"neighbor_id": "9.9.9.9", "state": "INIT", "address": "10.10.4.2", "interface": "Fa2/0"},
        {"neighbor_id": "8.8.8.8", "state": "FULL", "address": "10.99.0.1", "interface": "Fa9/0"},
    ]
    assert ospf_peers({"IPLC-RTR-TRV": DeviceReport(ospf=rows)}, INTERFACES, LINKS, []) == []


def test_a_discovery_during_the_fault_keeps_the_missing_neighbour_expected() -> None:
    reports = {"IPLC-RTR-TRV": DeviceReport(ospf=_table("fault1", "IPLC-RTR-TRV"))}
    peers = ospf_peers(reports, INTERFACES, LINKS, previous=_learned())
    assert ("IPLC-RTR-TRV", "IPLC-RTR-MAA") in {(p.device, p.peer) for p in peers}


def test_an_expected_neighbour_is_forgotten_when_its_link_is_gone() -> None:
    no_leased_line = [link for link in LINKS if link.subnet != "10.10.4.0/24"]
    reports = {"IPLC-RTR-TRV": DeviceReport(ospf=_table("fault1", "IPLC-RTR-TRV"))}
    peers = ospf_peers(reports, INTERFACES, no_leased_line, previous=_learned())
    assert ("IPLC-RTR-TRV", "IPLC-RTR-MAA") not in {(p.device, p.peer) for p in peers}


# ---------- the OSPF check reports the missing one ----------


def _expected(device: str) -> list[dict[str, Any]]:
    return [p for p in _learned() if p["device"] == device]


def test_fault1_the_missing_leased_line_neighbour_is_a_problem() -> None:
    verdict = health.ospf_neighbors(_table("fault1", "IPLC-RTR-TRV"), _expected("IPLC-RTR-TRV"))
    assert verdict.status == "problem"
    assert [(i.text, i.interface) for i in verdict.issues] == [
        (
            "OSPF neighbour IPLC-RTR-MAA (10.10.4.2) on Fa2/0 is missing: it was FULL at discovery",
            "Fa2/0",
        )
    ]


def test_the_healthy_table_matches_what_is_expected() -> None:
    verdict = health.ospf_neighbors(_table("healthy", "IPLC-RTR-TRV"), _expected("IPLC-RTR-TRV"))
    assert verdict.status == "ok"


def test_a_neighbour_that_is_there_but_not_full_is_reported_once() -> None:
    rows = _table("healthy", "IPLC-RTR-TRV")
    rows[0] = {**rows[0], "state": "EXSTART"}
    verdict = health.ospf_neighbors(rows, _expected("IPLC-RTR-TRV"))
    assert len(verdict.issues) == 1
    assert "EXSTART, not FULL" in verdict.issues[0].text


def test_without_expected_neighbours_it_judges_only_what_is_there() -> None:
    assert health.ospf_neighbors(_table("fault1", "IPLC-RTR-TRV")).status == "ok"
    assert health.ospf_neighbors([]).issues[0].text == "no OSPF neighbours"


def _service(tmp_path: Path, expected: Any) -> NetworkService:
    return NetworkService(
        inventory=load_inventory(REPO_ROOT / "lab" / "inventory.yaml"),
        executor=ReplayExecutor(OSPF / "fault1", delay_s=0),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        commands=load_commands(),
        expected_ospf=expected,
    )


def test_the_tool_names_the_missing_neighbour_by_alias_too(tmp_path: Path) -> None:
    result = _service(tmp_path, _expected).get_ospf_neighbors("TRV-P2P")
    assert result.health.status == "problem"
    assert result.summary == (
        "1 OSPF neighbour(s), all FULL; MISSING (FULL at discovery): IPLC-RTR-MAA on Fa2/0"
    )


def test_when_the_graph_is_down_the_check_still_runs_and_says_so(tmp_path: Path) -> None:
    def down(device: str) -> list[dict[str, Any]]:
        raise ConnectionError("neo4j is not running")

    result = _service(tmp_path, down).get_ospf_neighbors("IPLC-RTR-TRV")
    assert result.health.status == "ok"
    assert result.summary.endswith(
        "(expected neighbours not checked: knowledge graph not reachable)"
    )


def test_a_discovery_run_stores_the_neighbours_it_learned() -> None:
    from ainops.topology.discovery import plan_update

    reports = {
        d: DeviceReport(
            interfaces=[
                {"name": i.name, "status": "up", "ipv4": i.ipv4}
                for i in INTERFACES
                if i.device == d
            ],
            ospf=_table("healthy", d) if d.startswith("IPLC") else None,
        )
        for d in ("CORE-SW-TRV", "IPLC-RTR-TRV", "IPLC-RTR-MAA", "CORE-SW-MAA")
    }
    previous: dict[str, Any] = {"devices": [], "links": [], "ospf_peers": [], "discovery": None}
    inventory = load_inventory(REPO_ROOT / "lab" / "inventory.yaml")
    result = plan_update(inventory, reports, previous, "live", "2026-10-07T09:00:00+00:00")
    assert len(result.ospf_peers) == 4
    assert result.summary()["ospf_peer_count"] == 4
