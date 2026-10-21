"""OSPF rules the real lab (a straight line) never exercises: equal-cost paths, subnet and area
checks, on small labs made for the test."""

import ipaddress
import time
from pathlib import Path

from ainops.network import parsers
from labsim import cisco
from labsim.model import Lab, OspfNetwork, load_lab
from labsim.network import ArpCache, adjacencies, routes
from labsim.state import View

INVENTORY = """\
devices:
  - {name: R1, site: X, role: core, platform: cisco_ios, port: 40001}
  - {name: R2, site: X, role: core, platform: cisco_ios, port: 40002}
  - {name: R3, site: X, role: core, platform: cisco_ios, port: 40003}
"""

TRIANGLE = """\
devices:
  R1:
    node: 1
    interfaces:
      FastEthernet0/0: {address: 10.0.12.1/24}
      FastEthernet1/0: {address: 10.0.13.1/24}
    ospf: {process: 1, router_id: 1.1.1.1, networks: [10.0.0.0 0.0.255.255 area 0]}
  R2:
    node: 2
    interfaces:
      FastEthernet0/0: {address: 10.0.12.2/24}
      FastEthernet1/0: {address: 10.0.23.2/24}
    ospf: {process: 1, router_id: 2.2.2.2, networks: [10.0.0.0 0.0.255.255 area 0]}
  R3:
    node: 3
    interfaces:
      FastEthernet0/0: {address: 10.0.13.3/24}
      FastEthernet1/0: {address: 10.0.23.3/24}
    ospf: {process: 1, router_id: 3.3.3.3, networks: [10.0.0.0 0.0.255.255 area 0]}
links:
  - [R1 FastEthernet0/0, R2 FastEthernet0/0]
  - [R1 FastEthernet1/0, R3 FastEthernet0/0]
  - [R2 FastEthernet1/0, R3 FastEthernet1/0]
"""


def triangle(tmp_path: Path) -> Lab:
    (tmp_path / "inventory.yaml").write_text(INVENTORY, encoding="utf-8")
    (tmp_path / "lab.yaml").write_text(TRIANGLE, encoding="utf-8")
    return load_lab(tmp_path / "lab.yaml", tmp_path / "inventory.yaml")


def test_two_equal_paths_are_both_used(tmp_path: Path) -> None:
    lab = triangle(tmp_path)
    far = next(r for r in routes(lab, "R1") if str(r.prefix) == "10.0.23.0/24")
    assert (far.metric, {str(h.address) for h in far.hops}) == (2, {"10.0.12.2", "10.0.13.3"})


def test_ainops_reads_both_paths_from_the_ios_table(tmp_path: Path) -> None:
    lab = triangle(tmp_path)
    now = time.time()
    view = View(lab, ArpCache.seeded(lab, now), now - 60, now - 60, now)
    text, _ = cisco.answer(view, lab.devices["R1"], "show ip route", privileged=False)
    assert "                     [110/2] via 10.0.13.3" in text  # the second path, IOS layout
    rows = parsers.matching_routes(parsers.routes("cisco_ios", text), "10.0.23.9")
    assert {r["next_hop"] for r in rows} == {"10.0.12.2", "10.0.13.3"}


def test_one_ospf_statement_over_two_subnets_still_needs_the_same_subnet(tmp_path: Path) -> None:
    lab = triangle(tmp_path)
    r2 = lab.devices["R2"].interfaces["FastEthernet0/0"]
    r2.address = ipaddress.IPv4Interface("10.0.99.2/24")  # still inside 10.0.0.0 0.0.255.255
    assert "R2" not in {a.peer for a in adjacencies(lab, "R1")}


def test_routers_in_different_areas_do_not_become_neighbours(tmp_path: Path) -> None:
    lab = triangle(tmp_path)
    ospf = lab.devices["R2"].ospf
    assert ospf is not None
    ospf.networks = [OspfNetwork.parse("10.0.0.0 0.0.255.255 area 1")]
    assert adjacencies(lab, "R2") == []
    assert {a.peer for a in adjacencies(lab, "R1")} == {"R3"}


SQUARE = """\
devices:
  R1:
    node: 1
    interfaces:
      FastEthernet0/0: {address: 10.0.12.1/24}
      FastEthernet1/0: {address: 10.0.13.1/24}
    ospf: {process: 1, router_id: 1.1.1.1, networks: [10.0.0.0 0.0.255.255 area 0]}
  R2:
    node: 2
    interfaces:
      FastEthernet0/0: {address: 10.0.12.2/24}
      FastEthernet1/0: {address: 10.0.24.2/24}
    ospf: {process: 1, router_id: 2.2.2.2, networks: [10.0.0.0 0.0.255.255 area 0]}
  R3:
    node: 3
    interfaces:
      FastEthernet0/0: {address: 10.0.13.3/24}
      FastEthernet1/0: {address: 10.0.34.3/24}
    ospf: {process: 1, router_id: 3.3.3.3, networks: [10.0.0.0 0.0.255.255 area 0]}
  R4:
    node: 4
    interfaces:
      FastEthernet0/0: {address: 10.0.24.4/24}
      FastEthernet1/0: {address: 10.0.34.4/24}
      FastEthernet2/0: {address: 10.0.40.4/24}
    ospf: {process: 1, router_id: 4.4.4.4, networks: [10.0.0.0 0.0.255.255 area 0]}
links:
  - [R1 FastEthernet0/0, R2 FastEthernet0/0]
  - [R1 FastEthernet1/0, R3 FastEthernet0/0]
  - [R2 FastEthernet1/0, R4 FastEthernet0/0]
  - [R3 FastEthernet1/0, R4 FastEthernet1/0]
"""


def test_two_equal_paths_to_a_far_router_are_both_used(tmp_path: Path) -> None:
    """R1 reaches R4's LAN through R2 and through R3 at the same cost (a diamond)."""
    (tmp_path / "inventory.yaml").write_text(
        INVENTORY + "  - {name: R4, site: X, role: core, platform: cisco_ios, port: 40004}\n",
        encoding="utf-8",
    )
    (tmp_path / "lab.yaml").write_text(SQUARE, encoding="utf-8")
    lab = load_lab(tmp_path / "lab.yaml", tmp_path / "inventory.yaml")
    lan = next(r for r in routes(lab, "R1") if str(r.prefix) == "10.0.40.0/24")
    assert (lan.metric, {str(h.address) for h in lan.hops}) == (3, {"10.0.12.2", "10.0.13.3"})
