"""A firewall interface with an address but in no security zone: a Junos SRX drops its traffic.

The service reads the firewall's interfaces before its zones and judges the two together."""

import json
import shutil
from pathlib import Path

import pytest
from replay import ReplayExecutor

from ainops.config import REPO_ROOT
from ainops.network import health, parsers
from ainops.network.audit import AuditLog
from ainops.network.capture import fixture_path
from ainops.network.service import ZONE_NOTE, NetworkService, ToolFailure

NO_ZONES = REPO_ROOT / "fixtures" / "firewall" / "no-zones"
DROPS = "but is in no security zone: the firewall drops its traffic"


def port(name: str, *ipv4: str) -> dict[str, object]:
    return {"name": name, "status": "up", "ipv4": list(ipv4)}


def zone(name: str, *interfaces: str) -> dict[str, object]:
    return {"zone": name, "interfaces": list(interfaces)}


def test_addressed_port_in_no_zone_is_a_problem_naming_it() -> None:
    verdict = health.firewall_zones(
        [zone("trust", "ge-0/0/0.0")],
        [port("ge-0/0/0", "10.10.7.2/24"), port("ge-0/0/1", "10.10.6.1/24")],
    )
    assert verdict.status == "problem"
    assert [(i.text, i.interface) for i in verdict.issues] == [
        (f"ge-0/0/1 has an address (10.10.6.1/24) {DROPS}", "ge-0/0/1")
    ]


def test_ports_in_a_zone_are_ok() -> None:
    interfaces = [port("ge-0/0/0", "10.10.7.2/24"), port("reth0", "10.1.1.1/24")]
    zones = [zone("untrust", "ge-0/0/0.0"), zone("trust", "reth0")]  # a unit, or the port itself
    assert health.firewall_zones(zones, interfaces) == health.Health(status="ok")


@pytest.mark.parametrize(
    "interface",
    [
        port("fxp0", "172.20.10.50/24"),  # management: never in a zone
        port("em0", "128.0.0.1/2"),
        port("lo0", "10.255.0.1/32"),
        port("ge-0/0/2"),  # no address: carries no traffic
    ],
)
def test_management_loopback_and_unaddressed_ports_are_not_judged(
    interface: dict[str, object],
) -> None:
    assert health.firewall_zones([zone("trust")], [interface]).status == "ok"


@pytest.mark.parametrize("name", ["xe-0/0/1", "et-0/0/1", "ae0", "reth1", "irb", "vlan", "st0"])
def test_every_kind_of_traffic_port_is_judged(name: str) -> None:
    assert health.firewall_zones([], [port(name, "10.9.9.1/24")]).status == "problem"


def test_a_similar_name_in_a_zone_does_not_count() -> None:
    # ge-0/0/10.0 in a zone says nothing about ge-0/0/1.
    zones = [zone("trust", "ge-0/0/10.0")]
    assert health.firewall_zones(zones, [port("ge-0/0/1", "10.10.6.1/24")]).status == "problem"


def test_without_the_interfaces_the_zones_are_only_reported() -> None:
    assert health.firewall_zones([zone("trust")], None).status == "info"


def test_zones_parser() -> None:
    document = {
        "zones-information": [
            {
                "zones-security": [
                    {
                        "zones-security-zonename": [{"data": "trust"}],
                        "zones-security-interfaces": [
                            {
                                "zones-security-interface": [
                                    {"zones-security-interface-name": [{"data": "ge-0/0/1.0"}]}
                                ]
                            }
                        ],
                    },
                    {"zones-security-zonename": [{"data": "untrust"}]},
                ]
            }
        ]
    }
    text = json.dumps(document) + "\n\nroot@FWL-MAA> "
    assert parsers.firewall_zones(text) == [zone("trust", "ge-0/0/1.0"), zone("untrust")]


# ---------- the tool, against the lab firewall (replay) ----------


def lab_firewall(service: NetworkService, folder: Path) -> NetworkService:
    service.executor = ReplayExecutor(folder, delay_s=0)
    return service


def test_lab_firewall_with_no_zones_is_a_problem(service: NetworkService, audit: AuditLog) -> None:
    result = lab_firewall(service, NO_ZONES).get_firewall_zones("FWL-MAA")
    assert result.health.status == "problem"
    assert [i.interface for i in result.health.issues] == ["ge-0/0/0", "ge-0/0/1"]
    assert result.summary == (
        "trust: -; untrust: -; NOT IN ANY ZONE: ge-0/0/0 (10.10.7.2/24), ge-0/0/1 (10.10.6.1/24); "
        + ZONE_NOTE
    )
    # Both commands are audited: the interfaces read first, then the zones.
    commands = [entry.get("command") for entry in audit.tail()]
    assert commands == [
        "show interfaces terse | display json",
        "show security zones | display json",
    ]


# FWL-MAA's cables in the knowledge graph (discovery on 10-07), as GraphStore.links returns them:
# the firewall is the "b" end of both.
MAA_CABLES = [
    {"a": "CORE-SW-MAA", "a_interface": "Fa0/0", "b": "FWL-MAA", "b_interface": "ge-0/0/1"},
    {"a": "ISP-MAA-1", "a_interface": "Fa1/0", "b": "FWL-MAA", "b_interface": "ge-0/0/0"},
]


def test_each_port_in_no_zone_says_which_device_its_cable_goes_to(
    service: NetworkService,
) -> None:
    """So a fix never guesses which side is inside (trust) and which is outside (untrust)."""
    asked: list[str] = []
    service.cabling = lambda name: asked.append(name) or MAA_CABLES  # type: ignore[func-returns-value]
    result = lab_firewall(service, NO_ZONES).get_firewall_zones("fwl-maa")
    assert asked == ["FWL-MAA"]  # the inventory name, whatever the spelling asked
    assert result.summary == (
        "trust: -; untrust: -; NOT IN ANY ZONE: "
        "ge-0/0/0 (10.10.7.2/24, cabled to ISP-MAA-1 Fa1/0, isp-router), "
        "ge-0/0/1 (10.10.6.1/24, cabled to CORE-SW-MAA Fa0/0, core); " + ZONE_NOTE
    )
    assert [i.text for i in result.health.issues] == [
        f"ge-0/0/0 has an address (10.10.7.2/24) {DROPS} (its cable goes to ISP-MAA-1 Fa1/0, "
        "isp-router)",
        f"ge-0/0/1 has an address (10.10.6.1/24) {DROPS} (its cable goes to CORE-SW-MAA Fa0/0, "
        "core)",
    ]


def test_the_firewall_as_the_a_end_of_a_cable_is_read_too(service: NetworkService) -> None:
    service.cabling = lambda name: [
        {"a": "FWL-MAA", "a_interface": "ge-0/0/1", "b": "NEW-SW", "b_interface": "Gi0/1"}
    ]
    result = lab_firewall(service, NO_ZONES).get_firewall_zones("FWL-MAA")
    assert "ge-0/0/1 (10.10.6.1/24, cabled to NEW-SW Gi0/1)" in result.summary  # not in inventory
    assert "ge-0/0/0 (10.10.7.2/24)," in result.summary  # no cable known: nothing invented


def test_without_the_graph_the_ports_are_still_judged_and_it_says_so(
    service: NetworkService,
) -> None:
    def down(name: str) -> list[dict[str, object]]:
        raise OSError("graph down")

    service.cabling = down
    result = lab_firewall(service, NO_ZONES).get_firewall_zones("FWL-MAA")
    assert result.health.status == "problem"
    assert "cabled to" not in result.summary
    assert result.summary.endswith(" (cabling not checked: knowledge graph not reachable)")


def test_interfaces_not_read_means_no_verdict(service: NetworkService, tmp_path: Path) -> None:
    zones_only = tmp_path / "FWL-MAA"
    zones_only.mkdir()
    shutil.copy(NO_ZONES / "FWL-MAA" / "show-security-zones-display-json.txt", zones_only)
    result = lab_firewall(service, tmp_path).get_firewall_zones("FWL-MAA")
    assert result.health.status == "info"  # no false problem
    assert result.summary.startswith("trust: -; untrust: - (interfaces not checked: ")
    assert "NOT IN ANY ZONE" not in result.summary


def test_unparsable_interfaces_mean_no_verdict(service: NetworkService, tmp_path: Path) -> None:
    shutil.copytree(NO_ZONES, tmp_path, dirs_exist_ok=True)
    fixture_path(tmp_path, "FWL-MAA", "show interfaces terse | display json").write_text(
        "garbage", encoding="utf-8"
    )
    result = lab_firewall(service, tmp_path).get_firewall_zones("FWL-MAA")
    assert result.health.status == "info"
    assert result.summary.endswith(" (interfaces not checked: their output could not be parsed)")


def test_router_is_refused_without_reading_its_interfaces(
    service: NetworkService, audit: AuditLog
) -> None:
    with pytest.raises(ToolFailure, match="not supported"):
        service.get_firewall_zones("IPLC-RTR-MAA")
    assert "show ip interface" not in [entry.get("command") for entry in audit.tail()]
