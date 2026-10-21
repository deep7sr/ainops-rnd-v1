"""Junos 21.3 (vSRX) answers, as `| display json` documents in the shape the real lab printed.

Interfaces, routes and the security-zone shape follow the real recordings in fixtures/. Version,
interface detail, ARP, OSPF and LLDP neighbours, logs and security policies follow Juniper's
documented output and are NOT yet checked against our lab (only two kinds of Junos output were
recorded before the lab laptop went away).
"""

import ipaddress
import json
import random
import re
import time
from typing import Any

from labsim import network
from labsim.model import Device
from labsim.state import View

VERSION = "21.3R1.9"
UNKNOWN = "\n".join(["                     ^", "unknown command."])
NOT_SIMULATED = "error: labsim does not simulate this command"
NEEDS_JSON = "error: labsim answers this command only with '| display json'"

# The vSRX's own interfaces, in the order the real one lists them: (name, after which ge- port).
_INTERNAL_AFTER_GE0 = ["gr-0/0/0", "ip-0/0/0", "lsq-0/0/0", "lt-0/0/0", "mt-0/0/0", "sp-0/0/0"]
_INTERNAL_LAST = [
    "dsc", "fti0", "fxp0", "gre", "ipip", "irb", "lo0", "lsi", "mtun", "pimd", "pime", "pp0",
    "ppd0", "ppe0", "st0", "tap", "vlan",
]  # fmt: skip


def leaf(value: Any) -> list[dict[str, Any]]:
    return [{"data": str(value)}]


def _document(body: dict[str, Any]) -> str:
    return json.dumps(body, indent=4)


def _age(seconds: float) -> dict[str, Any]:
    s = max(0, int(seconds))
    if s < 86400:
        text = f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
    else:
        text = f"{s // 86400}d {s % 86400 // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return {"data": text, "attributes": {"junos:seconds": str(s)}}


# ---------- version ----------


def show_version(view: View, device: Device) -> str:
    return _document(
        {
            "software-information": [
                {
                    "host-name": leaf(device.name),
                    "product-model": leaf("vsrx"),
                    "product-name": leaf("vsrx"),
                    "junos-version": leaf(VERSION),
                    "package-information": [
                        {
                            "name": leaf("junos"),
                            "comment": leaf(f"JUNOS Software Release [{VERSION}]"),
                        }
                    ],
                }
            ]
        }
    )


# ---------- interfaces ----------


def _physical(device: Device, name: str) -> dict[str, Any]:
    interface = device.interfaces.get(name)
    if interface is None:  # one of the vSRX's own interfaces
        lo0 = name == "lo0"
        entry: dict[str, Any] = {
            "name": leaf(name),
            "admin-status": leaf("up"),
            "oper-status": leaf("down" if name == "vlan" else "up"),
        }
        if lo0:
            entry["logical-interface"] = [
                _logical("lo0.16384", True, ["127.0.0.1"]),
                _logical("lo0.16385", True, ["10.0.0.1", "10.0.0.16", "128.0.0.1", "128.0.0.4"]),
            ]
        elif name == "fxp0":
            entry["logical-interface"] = [_logical("fxp0.0", True, None)]
        return entry
    status = "up" if interface.admin_up else "down"
    entry = {"name": leaf(name), "admin-status": leaf(status), "oper-status": leaf(status)}
    if interface.address is not None:
        entry["logical-interface"] = [
            _logical(f"{name}.0", interface.admin_up, [interface.address.with_prefixlen])
        ]
    return entry


def _logical(name: str, up: bool, addresses: list[str] | None) -> dict[str, Any]:
    unit: dict[str, Any] = {
        "name": leaf(name),
        "admin-status": leaf("up"),
        "oper-status": leaf("up" if up else "down"),
        "filter-information": [{}],
    }
    if addresses is not None:
        unit["address-family"] = [
            {
                "address-family-name": leaf("inet"),
                "interface-address": [
                    {"ifa-local": [{"data": a, "attributes": {"junos:emit": "emit"}}]}
                    for a in addresses
                ],
            }
        ]
    return unit


def _order(device: Device) -> list[str]:
    ports = list(device.interfaces)
    return [*ports[:1], *_INTERNAL_AFTER_GE0, *ports[1:], *_INTERNAL_LAST]


def show_interfaces_terse(view: View, device: Device) -> str:
    return _document(
        {
            "interface-information": [
                {"physical-interface": [_physical(device, n) for n in _order(device)]}
            ]
        }
    )


def show_interface_extensive(view: View, device: Device, name: str) -> str | None:
    interface = device.interfaces.get(name.split(".")[0])
    if interface is None:
        return None
    up = "up" if interface.admin_up else "down"
    since = view.changed if not interface.admin_up else view.started
    flapped = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(since))
    entry = _physical(device, interface.name)
    entry.update(
        {
            "description": leaf(""),
            "speed": leaf("1000mbps"),
            "current-physical-address": leaf(_colon_mac(interface.mac)),
            "interface-flapped": [{"data": f"{flapped} ({network_age(view.now - since)} ago)"}],
            "input-error-list": [{"input-errors": leaf(0), "input-drops": leaf(0)}],
            "output-error-list": [{"output-errors": leaf(0), "output-drops": leaf(0)}],
        }
    )
    entry["admin-status"] = leaf(up)
    return _document({"interface-information": [{"physical-interface": [entry]}]})


def network_age(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _colon_mac(dotted: str) -> str:
    digits = dotted.replace(".", "")
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


# ---------- routes ----------


def _rt(
    prefix: str, protocol: str, preference: int, age: dict[str, Any], hop: dict[str, Any]
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "active-tag": leaf("*"),
        "current-active": [{"data": [None]}],
        "last-active": [{"data": [None]}],
        "protocol-name": leaf(protocol),
        "preference": leaf(preference),
        "age": [age],
    }
    if protocol == "Local":
        entry["nh-type"] = leaf("Local")
    entry["nh"] = [hop]
    return {
        "attributes": {"junos:style": "brief"},
        "rt-destination": leaf(prefix),
        "rt-entry": [entry],
    }


def show_route(view: View, device: Device) -> str:
    age = _age(view.now - view.changed)
    rows = []
    for route in network.routes(view.lab, device.name):
        unit = route.hops[0].interface + ".0"
        if route.code == "C":
            rows.append(
                _rt(
                    str(route.prefix),
                    "Direct",
                    0,
                    age,
                    {"selected-next-hop": [{"data": [None]}], "via": leaf(unit)},
                )
            )
        elif route.code == "L":
            rows.append(_rt(str(route.prefix), "Local", 0, age, {"nh-local-interface": leaf(unit)}))
        elif route.code == "O":
            hop = route.hops[0]
            via = {
                "selected-next-hop": [{"data": [None]}],
                "to": leaf(hop.address),
                "via": leaf(unit),
            }
            rows.append(_rt(str(route.prefix), "OSPF", 10, age, via))
    count = str(len(rows))
    multicast = _rt("ff02::2/128", "INET6", 0, age, {})
    multicast["rt-entry"][0]["nh-type"] = leaf("MultiRecv")
    del multicast["rt-entry"][0]["nh"]
    tables = [
        {
            "comment": "keepalive",
            "table-name": leaf("inet.0"),
            "destination-count": leaf(count),
            "total-route-count": leaf(count),
            "active-route-count": leaf(count),
            "holddown-route-count": leaf(0),
            "hidden-route-count": leaf(0),
            "rt": rows,
        },
        {
            "table-name": leaf("inet6.0"),
            "destination-count": leaf(1),
            "total-route-count": leaf(1),
            "active-route-count": leaf(1),
            "holddown-route-count": leaf(0),
            "hidden-route-count": leaf(0),
            "rt": [multicast],
        },
    ]
    return _document(
        {
            "route-information": [
                {
                    "attributes": {"xmlns": "http://xml.juniper.net/junos/21.3R0/junos-routing"},
                    "route-table": tables,
                }
            ]
        }
    )


# ---------- neighbours, ARP ----------


def show_ospf_neighbor(view: View, device: Device) -> str:
    rows = [
        {
            "neighbor-address": leaf(a.peer_address),
            "interface-name": leaf(a.interface + ".0"),
            "ospf-neighbor-state": leaf("Full"),
            "neighbor-id": leaf(a.peer_router_id),
            "neighbor-priority": leaf(128),
            "activity-timer": leaf(random.randint(30, 39)),
        }
        for a in network.adjacencies(view.lab, device.name)
    ]
    return _document({"ospf-neighbor-information": [{"ospf-neighbor": rows} if rows else {}]})


def show_lldp_neighbors(view: View, device: Device) -> str:
    # Nothing in the lab speaks LLDP to the vSRX (the 7200s only speak CDP).
    return _document({"lldp-neighbors-information": [{}]})


def show_arp(view: View, device: Device) -> str:
    rows = [
        {
            "mac-address": leaf(_colon_mac(mac)),
            "ip-address": leaf(address),
            "interface-name": leaf(interface + ".0"),
            "arp-table-entry-flags": [{"none": [{"data": [None]}]}],
        }
        for address, mac, interface, learned in network.arp_table(view.lab, device.name, view.cache)
        if learned is not None  # Junos does not list its own addresses
    ]
    return _document(
        {"arp-table-information": [{"arp-table-entry": rows, "arp-entry-count": leaf(len(rows))}]}
    )


def show_log_messages(view: View, device: Device) -> str:
    def stamp(t: float) -> str:
        return time.strftime("%b %d %H:%M:%S", time.localtime(t)).replace(" 0", "  ", 1)

    boot = view.started
    lines = [
        f"{stamp(boot)}  {device.name} kernel: KERNEL_BOOT: Junos {VERSION} booted",
        f"{stamp(boot + 40)}  {device.name} mgd[3121]: UI_COMMIT_COMPLETED: commit complete",
    ]
    for name, interface in device.interfaces.items():
        state = "up" if interface.admin_up else "down"
        when = boot + 60 if interface.admin_up else view.changed
        lines.append(f"{stamp(when)}  {device.name} mib2d[3130]: SNMP_TRAP_LINK_{state.upper()}: "
                     f"ifIndex 51{len(lines)}, ifAdminStatus {state}(1), ifOperStatus {state}(1), "
                     f"ifName {name}")  # fmt: skip
    return "\n".join(sorted(lines))


# ---------- firewall ----------


def _zone_unit(unit: str) -> dict[str, Any]:
    return {"zones-security-interface-name": leaf(unit)}


def _any(item: str, key: str) -> list[dict[str, Any]]:
    """Junos's "any" in a policy: [{item: [{key: "any"}]}]."""
    return [{item: [{key: leaf("any")}]}]


def show_security_zones(view: View, device: Device) -> str:
    zones = device.zones or {}
    return _document(
        {
            "zones-information": [
                {
                    "zones-security": [
                        {
                            "zones-security-zonename": leaf(zone),
                            "zones-security-interfaces": [
                                {"zones-security-interface": [_zone_unit(u) for u in units]}
                                if units else {}
                            ],
                        }
                        for zone, units in zones.items()
                    ]
                }
            ]
        }
    )  # fmt: skip


def show_security_policies(view: View, device: Device) -> str:
    """The vSRX factory policies: trust -> trust and trust -> untrust are allowed."""

    def policy(from_zone: str, to_zone: str) -> dict[str, Any]:
        return {
            "context-information": [
                {"source-zone-name": leaf(from_zone), "destination-zone-name": leaf(to_zone)}
            ],
            "policies": [
                {
                    "policy-information": [
                        {
                            "policy-name": leaf("default-permit"),
                            "policy-state": leaf("enabled"),
                            "policy-action": [{"action-type": leaf("permit")}],
                            "source-addresses": _any("source-address", "address-name"),
                            "destination-addresses": _any("destination-address", "address-name"),
                            "applications": _any("application", "application-name"),
                        }
                    ]
                }
            ],
        }  # fmt: skip

    contexts = [policy("trust", "trust"), policy("trust", "untrust")] if device.zones else []
    return _document({"security-policies": [{"security-context": contexts}]})


# ---------- ping ----------


def ping_text(destination: ipaddress.IPv4Address, result: network.PingResult) -> str:
    sent, received = len(result.marks), result.marks.count("!")
    lines = [f"PING {destination} ({destination}): 56 data bytes", result.marks, "",
             f"--- {destination} ping statistics ---",
             f"{sent} packets transmitted, {received} packets received, "
             f"{round(100 * (sent - received) / sent)}% packet loss"]  # fmt: skip
    if result.rtts_ms:
        rtts = result.rtts_ms
        mean = sum(rtts) / len(rtts)
        spread = (sum((r - mean) ** 2 for r in rtts) / len(rtts)) ** 0.5
        figures = "/".join(f"{x:.3f}" for x in (min(rtts), mean, max(rtts), spread))
        lines.append(f"round-trip min/avg/max/stddev = {figures} ms")
    return "\n".join(lines)


# ---------- the command line ----------

_JSON = [
    (r"show version", show_version),
    (r"show interfaces terse", show_interfaces_terse),
    (r"show route", show_route),
    (r"show ospf neighbor", show_ospf_neighbor),
    (r"show lldp neighbors", show_lldp_neighbors),
    (r"show arp no-resolve", show_arp),
    (r"show security zones", show_security_zones),
    (r"show security policies", show_security_policies),
]


def answer(view: View, device: Device, line: str) -> tuple[str, int]:
    """What the vSRX CLI prints for `line`, and how many ping packets timed out."""
    command, *pipes = [" ".join(part.split()) for part in line.split("|")]
    as_json = "display json" in pipes
    pipes = [p for p in pipes if p not in ("display json", "no-more")]

    setting = re.fullmatch(r"set cli (screen-width|screen-length) (\d+)", command)
    if setting:
        kind = "width" if setting[1] == "screen-width" else "length"
        return f"Screen {kind} set to {setting[2]}", 0
    if command == "set cli complete-on-space off":
        return "Disabling complete-on-space", 0

    text: str | None = None
    timeouts = 0
    for pattern, render in _JSON:
        if re.fullmatch(pattern, command):
            text = render(view, device) if as_json else NEEDS_JSON
            break
    if text is None:
        detail = re.fullmatch(r"show interfaces (\S+) extensive", command)
        ping = re.fullmatch(r"ping (\d+\.\d+\.\d+\.\d+)(?: count (\d+))?(?: rapid)?", command)
        if detail:
            shown = show_interface_extensive(view, device, detail[1]) if as_json else NEEDS_JSON
            text = shown if shown is not None else f"error: device {detail[1]} not found"
        elif command == "show log messages":
            text = show_log_messages(view, device)
        elif ping:
            destination = ipaddress.IPv4Address(ping[1])
            count = int(ping[2] or 5)
            result = network.ping(view.lab, device.name, destination, view.cache, count)
            text, timeouts = ping_text(destination, result), result.marks.count(".")
        elif command.startswith(("show ", "ping ")):
            text = NOT_SIMULATED
        else:
            text = UNKNOWN
    for pipe in pipes:
        last = re.fullmatch(r"last (\d+)", pipe)
        match = re.fullmatch(r"(match|except) (.+)", pipe)
        lines = text.split("\n")
        if last:
            text = "\n".join(lines[-int(last[1]) :])
        elif match:
            regex = re.compile(match[2].strip('"'))
            keep = match[1] == "match"
            text = "\n".join(x for x in lines if bool(regex.search(x)) == keep)
        elif pipe.startswith("count"):
            text = f"Count: {len(lines)} lines"
        else:
            return "syntax error, expecting <command>.", 0
    return text, timeouts
