"""The simulated lab must read like the real one: for every live recording in fixtures/, the
simulator's answer for the same device, command and state goes through AINOPS's own parsers and
must give the same parsed result. (The text itself may differ: counters, timers, MACs.)

The state of each recording is in its folder: fixtures/lab, routes/healthy, ospf/healthy and
firewall/no-zones are the healthy lab; routes/fault1 and ospf/fault1 are fault-1.
"""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ainops.config import REPO_ROOT
from ainops.network import parsers
from labsim import cisco, junos
from labsim.model import apply_faults, load_lab
from labsim.network import ArpCache
from labsim.state import View

FIXTURES = REPO_ROOT / "fixtures"
LAB = load_lab()
NOW = time.time()


def view(*faults: str) -> View:
    lab = apply_faults(LAB, list(faults))
    return View(lab, ArpCache.seeded(lab, NOW), NOW - 4000, NOW - 3000, NOW)


def rows(items: list[dict[str, Any]], keys: tuple[str, ...]) -> list[tuple[str, ...]]:
    return sorted(tuple(str(item.get(k)) for k in keys) for item in items)


Parse = Callable[[str, str], list[dict[str, Any]]]
CISCO: list[tuple[str, str, Parse, tuple[str, ...], tuple[str, ...]]] = [
    ("lab", "show ip interface", parsers.interfaces, ("name", "status", "ipv4"), ()),
    ("lab", "show cdp neighbors", parsers.neighbors,
     ("local_interface", "neighbor", "neighbor_interface", "neighbor_platform"), ()),
    ("ospf/healthy", "show ip ospf neighbor", parsers.ospf_neighbors,
     ("neighbor_id", "state", "role", "address", "interface"), ()),
    ("ospf/fault1", "show ip ospf neighbor", parsers.ospf_neighbors,
     ("neighbor_id", "state", "role", "address", "interface"), ("fault-1",)),
    ("routes/healthy", "show ip route", parsers.routes,
     ("prefix", "protocol", "next_hop", "interface", "distance_metric"), ()),
    ("routes/fault1", "show ip route", parsers.routes,
     ("prefix", "protocol", "next_hop", "interface", "distance_metric"), ("fault-1",)),
    ("lab", "show arp", parsers.arp, ("address", "interface"), ()),
]  # fmt: skip

# Real differences that are not simulation errors, with the reason.
KNOWN = {
    # ARP entries age out on real routers; this recording was made when the leased-line peer's
    # entry had expired. The simulator keeps every cabled neighbour (what a busy lab shows).
    ("lab", "IPLC-RTR-MAA", "show arp"): "10.10.4.1",
}

# Recordings made while the real device had a fault the folder does not say.
RECORDED_IN = {
    # 09-29: ISP-MAA-1 before Praveen's fix (the simulated healthy lab is the 10-07 one).
    ("lab", "ISP-MAA-1"): ("isp-maa-1-wrong-subnet",),
}
# The port to the outside follows the lab laptop's Wi-Fi (home 192.168.1.x on 09-29, the phone
# hotspot 172.20.10.x on 10-07): not part of the lab, so not compared.
UPSTREAM = {"ISP-MAA-1": "Fa0/0"}


def _cisco_cases() -> list[Any]:
    cases = []
    for folder, command, parse, keys, faults in CISCO:
        for path in sorted((FIXTURES / folder).glob(f"*/{command.replace(' ', '-')}.txt")):
            device = path.parent.name
            faults = faults + RECORDED_IN.get((folder, device), ())
            cases.append(
                pytest.param(path, command, parse, keys, faults, id=f"{folder}/{device}/{command}")
            )
    return cases


def _inside(device: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    upstream = UPSTREAM.get(device)
    names = ("name", "interface", "local_interface")
    return [item for item in items if upstream not in {item.get(n) for n in names}]


@pytest.mark.parametrize(("path", "command", "parse", "keys", "faults"), _cisco_cases())
def test_cisco_answers_parse_like_the_real_recordings(
    path: Path, command: str, parse: Parse, keys: tuple[str, ...], faults: tuple[str, ...]
) -> None:
    state = view(*faults)
    device = state.lab.devices[path.parent.name]
    real = rows(_inside(device.name, parse("cisco_ios", path.read_text(encoding="utf-8"))), keys)
    text, _ = cisco.answer(state, device, command, privileged=False)
    simulated = rows(_inside(device.name, parse("cisco_ios", text)), keys)
    extra = KNOWN.get((path.parent.parent.name, device.name, command))
    if extra:
        simulated = [row for row in simulated if row[0] != extra]
    assert simulated == real


def test_the_known_arp_difference_is_still_the_only_one() -> None:
    """If the simulator stopped listing the peer, the exception above would hide nothing."""
    state = view()
    text, _ = cisco.answer(state, state.lab.devices["IPLC-RTR-MAA"], "show arp", False)
    assert "10.10.4.1" in {r["address"] for r in parsers.arp("cisco_ios", text)}


@pytest.mark.parametrize("path", sorted((FIXTURES / "lab").glob("*/show-ip-protocols.txt")))
def test_cisco_routing_protocols_parse_like_the_real_recordings(path: Path) -> None:
    state = view()
    text, _ = cisco.answer(state, state.lab.devices[path.parent.name], "show ip protocols", False)
    assert parsers.routing_protocols(text) == parsers.routing_protocols(path.read_text("utf-8"))


@pytest.mark.parametrize(
    ("device", "destination", "faults"),
    [
        ("CORE-SW-TRV", "192.168.200.1", ()),  # across the leased line
        ("CORE-SW-TRV", "10.10.2.1", ()),  # a vSRX: it drops pings (no zones)
        ("CORE-SW-MAA", "10.10.6.1", ()),
        ("IPLC-RTR-MAA", "10.10.4.1", ()),
        ("IPLC-RTR-MAA", "10.10.5.2", ()),
        # Recorded on 09-29 while the leadership-demo fault was on (IPLC-RTR-MAA Fa2/0 had the
        # wrong address 10.10.40.2): the OSPF table recorded with it has no MAA neighbour either.
        ("IPLC-RTR-TRV", "10.10.4.2", ("leased-line-wrong-ip",)),
        ("ISP-TRV-1", "10.10.1.2", ()),
        # 09-29, before the fix: 10.10.7.2 was in none of its subnets (no route).
        ("ISP-MAA-1", "10.10.7.2", ("isp-maa-1-wrong-subnet",)),
    ],
)
def test_cisco_pings_succeed_and_fail_like_the_real_ones(
    device: str, destination: str, faults: tuple[str, ...]
) -> None:
    path = FIXTURES / "lab" / device / f"ping-{destination.replace('.', '-')}.txt"
    real = parsers.ping("cisco_ios", path.read_text(encoding="utf-8"))
    state = view(*faults)
    text, _ = cisco.answer(state, state.lab.devices[device], f"ping {destination}", False)
    simulated = parsers.ping("cisco_ios", text)
    keys = ("sent", "received", "success_percent", "replies")
    assert {k: simulated[k] for k in keys} == {k: real[k] for k in keys}


# Not compared: IPLC-RTR-TRV ping 10.10.3.1 (its own core router, one cable away) failed in the
# 09-29 recording while the OSPF neighbour on that same cable was FULL. No fault explains it (a
# glitch of the real lab at that moment); the simulator answers it as the healthy cable it is.
UNEXPLAINED_PINGS = {"IPLC-RTR-TRV ping-10-10-3-1"}


def test_every_recorded_ping_is_compared_or_explained() -> None:
    recorded = {p.parent.name + " " + p.stem for p in (FIXTURES / "lab").glob("*/ping-*.txt")}
    assert len(recorded - UNEXPLAINED_PINGS) == 8  # the list above: update both with a recording


def test_cisco_version_reads_like_the_real_router() -> None:
    state = view()
    text, _ = cisco.answer(state, state.lab.devices["IPLC-RTR-MAA"], "show version", False)
    real = (FIXTURES / "lab" / "IPLC-RTR-MAA" / "show-version-include-ios.txt").read_text("utf-8")
    assert real.strip() in text  # the recorded line, exactly
    facts = parsers.facts("cisco_ios", text)
    assert (facts["hostname"], facts["version"], facts["model"]) == (
        "IPLC-RTR-MAA", "15.2(4)S6", "7206VXR"
    )  # fmt: skip


@pytest.mark.parametrize(
    ("path", "command", "parse"),
    [
        (FIXTURES / "routes/healthy/FWL-MAA/show-route-display-json.txt",
         "show route | display json", lambda t: parsers.routes("juniper_junos", t)),
        (FIXTURES / "firewall/no-zones/FWL-MAA/show-interfaces-terse-display-json.txt",
         "show interfaces terse | display json", lambda t: parsers.interfaces("juniper_junos", t)),
        # This one is hand-written in the real shape (see fixtures/firewall/README.md).
        (FIXTURES / "firewall/no-zones/FWL-MAA/show-security-zones-display-json.txt",
         "show security zones | display json", parsers.firewall_zones),
    ],
    ids=["routes", "interfaces", "zones"],
)  # fmt: skip
def test_junos_answers_parse_like_the_real_recordings(
    path: Path, command: str, parse: Callable[[str], list[dict[str, Any]]]
) -> None:
    state = view()
    text, _ = junos.answer(state, state.lab.devices["FWL-MAA"], command)
    assert parse(text) == parse(path.read_text(encoding="utf-8"))
