"""The simulated network's behaviour: what each fault changes, and the model's own checks."""

import ipaddress
import time
from pathlib import Path
from typing import Any

import pytest

from ainops.config import REPO_ROOT
from ainops.network import health, parsers
from labsim import cisco, cli, junos, network
from labsim.model import INVENTORY_FILE, LAB_FILE, LabError, apply_faults, load_lab
from labsim.network import ArpCache
from labsim.state import Simulator, View, read_faults, write_faults

LAB = load_lab()
IP = ipaddress.IPv4Address


def view(*faults: str) -> View:
    lab = apply_faults(LAB, list(faults))
    now = time.time()
    return View(lab, ArpCache.seeded(lab, now), now - 600, now - 60, now)


def ask(state: View, device: str, command: str) -> str:
    target = state.lab.devices[device]
    if target.platform == "juniper_junos":
        return junos.answer(state, target, command)[0]
    return cisco.answer(state, target, command, privileged=False)[0]


def route_to(state: View, device: str, address: str) -> list[dict[str, str]]:
    rows = parsers.routes("cisco_ios", ask(state, device, "show ip route"))
    return parsers.matching_routes(rows, address)


def ping(state: View, device: str, address: str) -> dict[str, Any]:
    return parsers.ping("cisco_ios", ask(state, device, f"ping {address}"))


def neighbours(state: View, device: str) -> set[str]:
    rows = parsers.ospf_neighbors("cisco_ios", ask(state, device, "show ip ospf neighbor"))
    return {r["neighbor_id"] for r in rows if r["state"] == "FULL"}


# ---------- the healthy lab ----------


def test_healthy_lab_reaches_across_the_leased_line_with_the_real_costs() -> None:
    state = view()
    best = route_to(state, "CORE-SW-TRV", "192.168.200.10")[0]
    assert (best["prefix"], best["next_hop"], best["distance_metric"]) == (
        "192.168.200.0/24", "10.10.3.2", "110/13"
    )  # fmt: skip
    assert neighbours(state, "IPLC-RTR-TRV") == {"10.10.5.1", "192.168.100.1"}
    assert ping(state, "CORE-SW-TRV", "192.168.200.1")["received"] == 5


def test_first_ping_to_a_pc_loses_one_packet_for_arp_then_none() -> None:
    state = view()
    first = ping(state, "CORE-SW-TRV", "192.168.200.10")
    again = ping(state, "CORE-SW-TRV", "192.168.200.10")
    assert first["replies"] == ".!!!!" and health.first_lost_only(first)
    assert first["success_percent"] == 80
    assert again["replies"] == "!!!!!"


def test_the_vsrx_drop_everything_while_their_interfaces_are_in_no_zone() -> None:
    state = view()
    assert ping(state, "CORE-SW-MAA", "10.10.6.1")["received"] == 0
    zones = parsers.firewall_zones(ask(state, "FWL-MAA", "show security zones | display json"))
    interfaces = parsers.interfaces(
        "juniper_junos", ask(state, "FWL-MAA", "show interfaces terse | display json")
    )
    verdict = health.firewall_zones(zones, interfaces)
    assert verdict.status == "problem"
    assert {i.interface for i in verdict.issues} == {"ge-0/0/0", "ge-0/0/1"}


def test_a_vsrx_interface_in_a_zone_passes_traffic() -> None:
    lab = apply_faults(LAB, [])
    zones = lab.devices["FWL-MAA"].zones
    assert zones is not None
    zones["trust"].append("ge-0/0/1.0")
    state = View(lab, ArpCache.seeded(lab), 0, 0, time.time())
    assert ping(state, "CORE-SW-MAA", "10.10.6.1")["received"] == 5
    zones_now = parsers.firewall_zones(ask(state, "FWL-MAA", "show security zones | display json"))
    assert {"zone": "trust", "interfaces": ["ge-0/0/1.0"]} in zones_now
    interfaces = parsers.interfaces(
        "juniper_junos", ask(state, "FWL-MAA", "show interfaces terse | display json")
    )
    flagged = health.firewall_zones(zones_now, interfaces).issues
    assert [i.interface for i in flagged] == ["ge-0/0/0"]


def test_a_packet_stops_where_nobody_answers_arp_for_the_next_hop() -> None:
    wrong = apply_faults(LAB, ["leased-line-wrong-ip"])
    stopped = network.walk(wrong, "IPLC-RTR-TRV", IP("10.10.4.2"))
    assert (stopped.status, stopped.at, stopped.links) == ("dropped", "IPLC-RTR-TRV", 0)
    shut = apply_faults(LAB, ["fault-1"])
    stopped = network.walk(shut, "IPLC-RTR-TRV", IP("10.10.4.2"))
    assert (stopped.status, stopped.at, stopped.links) == ("dropped", "IPLC-RTR-TRV", 0)


def test_a_ping_fails_when_only_the_reply_cannot_get_back() -> None:
    lab = apply_faults(LAB, [])
    lab.devices["MAA-PC"].gateway = IP("192.168.200.254")  # a PC with the wrong gateway
    state = View(lab, ArpCache.seeded(lab), 0, 0, time.time())
    assert network.walk(lab, "CORE-SW-TRV", IP("192.168.200.10")).status == "arrived"
    assert ping(state, "CORE-SW-TRV", "192.168.200.10")["received"] == 0
    assert ping(state, "CORE-SW-MAA", "192.168.200.10")["received"] >= 4  # its own LAN still works


def test_a_cable_does_not_take_the_far_end_down_like_in_eve() -> None:
    state = view("fault-1")
    rows = parsers.interfaces("cisco_ios", ask(state, "IPLC-RTR-TRV", "show ip interface"))
    assert next(r for r in rows if r["name"] == "Fa2/0")["status"] == "up"


# ---------- the faults ----------


def test_fault_1_shuts_the_leased_line_and_cuts_trv_from_maa() -> None:
    state = view("fault-1")
    rows = parsers.interfaces("cisco_ios", ask(state, "IPLC-RTR-MAA", "show ip interface"))
    assert next(r for r in rows if r["name"] == "Fa2/0")["status"] == "admin-down"
    assert neighbours(state, "IPLC-RTR-TRV") == {"192.168.100.1"}
    assert route_to(state, "CORE-SW-TRV", "192.168.200.10") == []
    assert route_to(state, "CORE-SW-MAA", "192.168.100.10") == []
    assert ping(state, "CORE-SW-TRV", "192.168.200.1")["received"] == 0


def test_wrong_address_keeps_the_link_up_but_loses_ospf() -> None:
    state = view("leased-line-wrong-ip")
    rows = parsers.interfaces("cisco_ios", ask(state, "IPLC-RTR-MAA", "show ip interface"))
    leased = next(r for r in rows if r["name"] == "Fa2/0")
    assert (leased["status"], leased["ipv4"]) == ("up", ["10.10.40.2/24"])
    assert neighbours(state, "IPLC-RTR-TRV") == {"192.168.100.1"}
    assert ping(state, "IPLC-RTR-TRV", "10.10.4.2")["received"] == 0


def test_passive_ospf_keeps_the_interface_up_and_the_neighbour_away() -> None:
    state = view("leased-line-ospf-passive")
    assert neighbours(state, "IPLC-RTR-TRV") == {"192.168.100.1"}
    assert neighbours(state, "IPLC-RTR-MAA") == {"192.168.200.1"}
    assert "Passive Interface(s):\n    FastEthernet2/0\n" in ask(
        state, "IPLC-RTR-TRV", "show ip protocols"
    )
    assert ping(state, "IPLC-RTR-TRV", "10.10.4.2")["received"] == 5  # the cable still works
    assert route_to(state, "CORE-SW-TRV", "192.168.200.10") == []


def test_maa_lan_gateway_down_removes_the_lan_everywhere() -> None:
    state = view("maa-lan-gateway-down")
    assert route_to(state, "CORE-SW-TRV", "192.168.200.10") == []
    assert route_to(state, "CORE-SW-MAA", "192.168.200.10") == []
    assert ping(state, "IPLC-RTR-MAA", "192.168.200.10")["received"] == 0


def test_maa_lan_not_announced_is_only_missing_far_away() -> None:
    state = view("maa-lan-not-announced")
    assert route_to(state, "CORE-SW-MAA", "192.168.200.10")[0]["protocol"] == "connected"
    assert route_to(state, "CORE-SW-TRV", "192.168.200.10") == []
    networks = parsers.routing_protocols(ask(state, "CORE-SW-MAA", "show ip protocols"))
    assert "192.168.200.0" not in {n["network"] for n in networks["ospf_networks"]}


def test_isp_maa_1_shares_the_firewall_subnet_until_the_wrong_subnet_fault() -> None:
    healthy = view()
    assert route_to(healthy, "ISP-MAA-1", "10.10.7.2")[0]["protocol"] == "connected"
    broken = view("isp-maa-1-wrong-subnet")
    assert route_to(broken, "ISP-MAA-1", "10.10.7.2") == []
    rows = parsers.interfaces("cisco_ios", ask(broken, "ISP-MAA-1", "show ip interface"))
    assert next(r for r in rows if r["name"] == "Fa1/0")["ipv4"] == ["10.10.8.1/24"]


def test_faults_never_change_the_lab_they_are_applied_to() -> None:
    before = network.routes(LAB, "CORE-SW-TRV")
    apply_faults(LAB, list(LAB.faults))
    assert network.routes(LAB, "CORE-SW-TRV") == before


def test_every_fault_breaks_something_and_healing_brings_the_lab_back() -> None:
    healthy = {name: network.routes(LAB, name) for name in LAB.devices}
    for fault in LAB.faults:
        broken = apply_faults(LAB, [fault])
        assert {n: network.routes(broken, n) for n in LAB.devices} != healthy, fault
    healed = apply_faults(LAB, [])
    assert {n: network.routes(healed, n) for n in LAB.devices} == healthy


# ---------- the command line ----------


def test_show_logging_needs_enable_as_on_the_real_consoles() -> None:
    state = view()
    assert ask(state, "IPLC-RTR-MAA", "show logging") == cisco.INVALID


def test_a_command_the_simulator_does_not_know_says_so() -> None:
    state = view()
    assert "labsim does not simulate" in ask(state, "IPLC-RTR-MAA", "show running-config")
    assert "labsim does not simulate" in ask(state, "FWL-MAA", "show configuration")
    assert "display json" in ask(state, "FWL-MAA", "show route")  # text form is not simulated


def test_ios_output_modifiers_filter_lines() -> None:
    state = view()
    lines = ask(state, "IPLC-RTR-MAA", "show ip route | include via").splitlines()
    assert lines and all("via" in line for line in lines)
    assert ask(state, "IPLC-RTR-MAA", "show ip route | bogus x") == cisco.INVALID


def test_interface_names_can_be_abbreviated() -> None:
    state = view()
    text = ask(state, "IPLC-RTR-MAA", "show interfaces Fa2/0")
    assert parsers.interface_detail("cisco_ios", text)["name"] == "Fa2/0"
    assert ask(state, "IPLC-RTR-MAA", "show interfaces Fa9/9") == cisco.INVALID


def test_junos_session_setup_commands_answer_like_junos() -> None:
    state = view()
    assert ask(state, "FWL-MAA", "set cli screen-width 511") == "Screen width set to 511"
    assert ask(state, "FWL-MAA", "set cli screen-length 0") == "Screen length set to 0"
    assert ask(state, "FWL-MAA", "set cli complete-on-space off") == "Disabling complete-on-space"


def test_ios_route_table_keeps_the_trailing_space_of_the_real_header() -> None:
    text = ask(view(), "IPLC-RTR-MAA", "show ip route")
    assert "O - OSPF, IA - OSPF inter area \n" in text


# ---------- the model's checks ----------


def _write_lab(tmp_path: Path, old: str, new: str) -> Path:
    text = LAB_FILE.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "lab.yaml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def test_lab_and_inventory_must_name_the_same_devices(tmp_path: Path) -> None:
    path = _write_lab(tmp_path, "  ISP-TRV-1:\n", "  ISP-TRV-9:\n")
    with pytest.raises(LabError, match="same devices"):
        load_lab(path, INVENTORY_FILE)


def test_an_interface_can_have_only_one_cable(tmp_path: Path) -> None:
    path = _write_lab(
        tmp_path, "  - [ISP-MAA-1 FastEthernet0/0, hotspot]",
        "  - [ISP-MAA-1 FastEthernet1/0, hotspot]",
    )  # fmt: skip
    with pytest.raises(LabError, match="more than one cable"):
        load_lab(path, INVENTORY_FILE)


def test_a_fault_naming_a_missing_interface_fails_when_the_lab_loads(tmp_path: Path) -> None:
    path = _write_lab(
        tmp_path, "{device: CORE-SW-MAA, interface: Ethernet1/0, admin: down}",
        "{device: CORE-SW-MAA, interface: Ethernet9/0, admin: down}",
    )  # fmt: skip
    with pytest.raises(LabError, match="no interface"):
        load_lab(path, INVENTORY_FILE)


def test_unknown_fault_name_is_refused() -> None:
    with pytest.raises(LabError, match="no fault named"):
        apply_faults(LAB, ["no-such-fault"])


def test_macs_follow_eve_like_the_recordings() -> None:
    assert LAB.devices["CORE-SW-TRV"].interfaces["FastEthernet2/0"].mac == "ca01.3507.0038"
    assert LAB.devices["FWL-TRV"].interfaces["ge-0/0/1"].mac == "5000.0003.0002"


# ---------- the fault state ----------


def test_the_running_simulator_picks_up_a_fault_change(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    simulator = Simulator(LAB, state_file=state_file)
    assert simulator.faults == []
    write_faults(["fault-1", "not-a-fault"], state_file)
    simulator.refresh()
    assert simulator.faults == ["fault-1"]  # an unknown name is ignored
    assert not simulator.view().lab.devices["IPLC-RTR-MAA"].interfaces["FastEthernet2/0"].admin_up
    write_faults([], state_file)
    assert simulator.view().lab.devices["IPLC-RTR-MAA"].interfaces["FastEthernet2/0"].admin_up
    assert read_faults(state_file)[0] == []


# ---------- the boundary ----------


def test_ainops_never_imports_the_simulator() -> None:
    sources = (REPO_ROOT / "backend" / "src" / "ainops").rglob("*.py")
    assert [p.name for p in sources if "labsim" in p.read_text(encoding="utf-8")] == []


# ---------- the labsim commands ----------


def test_fault_faults_and_heal_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("labsim.cli.STATE_FILE", state_file)
    assert cli.main(["fault", "fault-1"]) == 0
    assert cli.main(["fault", "maa-lan-gateway-down"]) == 0
    assert read_faults(state_file)[0] == ["fault-1", "maa-lan-gateway-down"]
    capsys.readouterr()
    assert cli.main(["faults"]) == 0
    listed = capsys.readouterr().out
    assert "[on] fault-1" in listed and "     leased-line-wrong-ip" in listed
    assert cli.main(["heal", "fault-1"]) == 0
    assert read_faults(state_file)[0] == ["maa-lan-gateway-down"]
    assert cli.main(["heal", "fault-1"]) == 1  # not on any more
    assert cli.main(["fault", "no-such-fault"]) == 1
    assert cli.main(["heal"]) == 0
    assert read_faults(state_file)[0] == []
