"""Turn device output into the same small JSON shape for every vendor.

This is what makes the tools vendor-neutral: `get_interfaces` on a Cisco router and on a Juniper
firewall return the same fields, so the agent never needs to know the brand.

Cisco text is parsed with ntc-templates (the standard community TextFSM templates). Junos output is
requested as JSON (`| display json`); Junos wraps every value as {"key": [{"data": "value"}]}.
A parser that cannot read an output raises ParseError; the service then returns an excerpt of the
raw text instead, so the agent still sees what the device said.
"""

import ipaddress
import json
import re
from typing import Any

from ntc_templates.parse import parse_output


class ParseError(Exception):
    """The output did not have the expected shape."""


# ---------- helpers ----------


def _ntc(command: str, text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []  # an empty listing means "none found" (e.g. no OSPF neighbours)
    try:
        return list(parse_output(platform="cisco_ios", command=command, data=text))
    except Exception as error:  # noqa: BLE001 - TextFSM raises its own types
        raise ParseError(f"could not parse '{command}': {error}") from error


def junos_json(text: str) -> dict[str, Any]:
    """The JSON document in a Junos answer (the CLI may add its prompt after it)."""
    start = text.find("{")
    if start < 0:
        raise ParseError("no JSON in the output")
    try:
        document, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as error:
        raise ParseError(f"invalid JSON: {error}") from error
    if not isinstance(document, dict):
        raise ParseError("JSON output is not an object")
    return document


def _items(node: Any, key: str) -> list[Any]:
    """Junos container list under `key` ([] if missing)."""
    if not isinstance(node, dict):
        return []
    value = node.get(key)
    return value if isinstance(value, list) else []


def _first(node: Any, key: str) -> Any:
    items = _items(node, key)
    return items[0] if items else {}


def _leaf(node: Any, key: str) -> str:
    """Junos leaf value under `key` ("" if missing)."""
    for item in _items(node, key):
        if isinstance(item, dict) and "data" in item:
            return str(item["data"]).strip()
    return ""


_CISCO_LONG = {
    "fa": "FastEthernet",
    "fas": "FastEthernet",
    "gi": "GigabitEthernet",
    "gig": "GigabitEthernet",
    "te": "TenGigabitEthernet",
    "e": "Ethernet",
    "et": "Ethernet",
    "eth": "Ethernet",
    "se": "Serial",
    "ser": "Serial",
    "lo": "Loopback",
    "tu": "Tunnel",
}


def cisco_interface(name: str) -> str:
    """Fa2/0, 'Fas 2/0', FastEthernet2/0 -> FastEthernet2/0 (one spelling for matching)."""
    compact = name.replace(" ", "")
    match = re.fullmatch(r"([A-Za-z]+)([\d/.:]+)", compact)
    if not match:
        return compact
    prefix, number = match.groups()
    return _CISCO_LONG.get(prefix.lower(), prefix) + number


def short_interface(name: str) -> str:
    """FastEthernet2/0 -> Fa2/0, as engineers write it."""
    for long, short in (
        ("TenGigabitEthernet", "Te"),
        ("GigabitEthernet", "Gi"),
        ("FastEthernet", "Fa"),
        ("Ethernet", "E"),
        ("Serial", "Se"),
        ("Loopback", "Lo"),
        ("Tunnel", "Tu"),
    ):
        if name.startswith(long):
            return short + name[len(long) :]
    return name


# Junos creates many internal interfaces; only these are interesting for troubleshooting.
_JUNOS_USEFUL = re.compile(r"^(ge|xe|et|ae|reth|st0|lo0|fxp0|em0|irb|vlan)")


# ---------- interfaces ----------


def interfaces(platform: str, text: str) -> list[dict[str, Any]]:
    """One row per interface: name, status (up / down / admin-down), IPv4 addresses with prefix."""
    rows: list[dict[str, Any]] = []
    if platform == "cisco_ios":
        for row in _ntc("show ip interface", text):
            link = row.get("link_status", "")
            status = (
                "admin-down"
                if link.startswith("administratively")
                else ("up" if link == "up" and row.get("protocol_status") == "up" else "down")
            )
            addresses = [
                f"{ip}/{length}"
                for ip, length in zip(
                    row.get("ip_address", []), row.get("prefix_length", []), strict=False
                )
            ]
            rows.append(
                {
                    "name": short_interface(row["interface"]),
                    "status": status,
                    "link": link,
                    "protocol": row.get("protocol_status", ""),
                    "ipv4": addresses,
                }
            )
        return rows

    info = _first(junos_json(text), "interface-information")
    for physical in _items(info, "physical-interface"):
        name = _leaf(physical, "name")
        if not _JUNOS_USEFUL.match(name):
            continue
        admin = _leaf(physical, "admin-status")
        oper = _leaf(physical, "oper-status")
        addresses = []
        for logical in _items(physical, "logical-interface"):
            # lo0.16384 / lo0.16385 / lo0.32768 are Junos-internal (127.x, 128.x): skip them.
            unit = _leaf(logical, "name").rpartition(".")[2]
            if unit.isdigit() and int(unit) >= 16384:
                continue
            for family in _items(logical, "address-family"):
                if _leaf(family, "address-family-name") != "inet":
                    continue
                for address in _items(family, "interface-address"):
                    local = _leaf(address, "ifa-local")
                    if local:
                        addresses.append(local)
        status = "admin-down" if admin == "down" else ("up" if oper == "up" else "down")
        rows.append(
            {"name": name, "status": status, "link": admin, "protocol": oper, "ipv4": addresses}
        )
    return rows


def interface_detail(platform: str, text: str) -> dict[str, Any]:
    """Health of one interface: status, errors, drops, last flap."""
    if platform == "cisco_ios":
        rows = _ntc("show interfaces", text)
        if not rows:
            raise ParseError("no interface in the output")
        row = rows[0]
        keep = (
            "link_status", "protocol_status", "description", "ip_address", "prefix_length", "mtu",
            "bandwidth", "duplex", "speed", "last_input", "last_output", "last_output_hang",
            "input_packets", "input_errors", "crc", "output_packets", "output_errors",
            "interface_resets", "input_rate", "output_rate",
        )  # fmt: skip
        detail = {key: row[key] for key in keep if key in row and row[key] not in ("", [])}
        detail["name"] = short_interface(row.get("interface", ""))
        return detail

    info = _first(junos_json(text), "interface-information")
    physical = _first(info, "physical-interface")
    if not physical:
        raise ParseError("no interface in the output")
    errors_in = _first(physical, "input-error-list")
    errors_out = _first(physical, "output-error-list")
    flapped = _first(physical, "interface-flapped")
    return {
        "name": _leaf(physical, "name"),
        "admin_status": _leaf(physical, "admin-status"),
        "oper_status": _leaf(physical, "oper-status"),
        "description": _leaf(physical, "description"),
        "speed": _leaf(physical, "speed"),
        "last_flapped": flapped.get("data", "") if isinstance(flapped, dict) else "",
        "input_errors": _leaf(errors_in, "input-errors"),
        "input_drops": _leaf(errors_in, "input-drops"),
        "output_errors": _leaf(errors_out, "output-errors"),
        "output_drops": _leaf(errors_out, "output-drops"),
    }


# ---------- device facts ----------


def facts(platform: str, text: str) -> dict[str, Any]:
    if platform == "cisco_ios":
        rows = _ntc("show version", text)
        if not rows:
            raise ParseError("no version information in the output")
        row = rows[0]
        return {
            "hostname": row.get("hostname", ""),
            "os": "Cisco IOS",
            "version": row.get("version", ""),
            "model": ", ".join(row.get("hardware", [])),
            "uptime": row.get("uptime", ""),
            "last_reload_reason": row.get("reload_reason", ""),
        }
    info = _first(junos_json(text), "software-information")
    if not info:
        raise ParseError("no software-information in the output")
    return {
        "hostname": _leaf(info, "host-name"),
        "os": "Junos",
        "version": _leaf(info, "junos-version"),
        "model": _leaf(info, "product-model"),
    }


# ---------- routing ----------

_CISCO_PROTOCOLS = {
    "C": "connected",
    "L": "local",
    "S": "static",
    "O": "ospf",
    "O IA": "ospf-inter-area",
    "O E1": "ospf-external",
    "O E2": "ospf-external",
    "B": "bgp",
    "D": "eigrp",
    "R": "rip",
}


def routes(platform: str, text: str) -> list[dict[str, Any]]:
    """One row per route: prefix, protocol, next hop, outgoing interface."""
    rows: list[dict[str, Any]] = []
    if platform == "cisco_ios":
        for row in _ntc("show ip route", text):
            network, length = row.get("network", ""), row.get("prefix_length", "")
            if not network:
                continue
            code = row.get("protocol", "").strip()
            rows.append(
                {
                    "prefix": f"{network}/{length}" if length else network,
                    "protocol": _CISCO_PROTOCOLS.get(code, code),
                    "next_hop": row.get("nexthop_ip", ""),
                    "interface": short_interface(row.get("nexthop_if", "")),
                    "distance_metric": (
                        f"{row['distance']}/{row['metric']}" if row.get("distance") else ""
                    ),
                }
            )
        return rows

    info = _first(junos_json(text), "route-information")
    for table in _items(info, "route-table"):
        table_name = _leaf(table, "table-name")
        if table_name and table_name != "inet.0":
            continue
        for route in _items(table, "rt"):
            prefix = _leaf(route, "rt-destination")
            for entry in _items(route, "rt-entry")[:1]:  # the active entry comes first
                hop = _first(entry, "nh")
                rows.append(
                    {
                        "prefix": prefix,
                        "protocol": _leaf(entry, "protocol-name").lower(),
                        "next_hop": _leaf(hop, "to"),
                        "interface": _leaf(hop, "via") or _leaf(hop, "nh-local-interface"),
                        "distance_metric": _leaf(entry, "preference"),
                    }
                )
    return rows


def matching_routes(rows: list[dict[str, Any]], destination: str) -> list[dict[str, Any]]:
    """The routes that cover `destination`, most specific first (what the router would use)."""
    address = ipaddress.ip_address(destination)
    matches = []
    for row in rows:
        try:
            network = ipaddress.ip_network(row["prefix"], strict=False)
        except ValueError:
            continue
        if address in network:
            matches.append((network.prefixlen, row))
    return [row for _, row in sorted(matches, key=lambda item: -item[0])]


def ospf_neighbors(platform: str, text: str) -> list[dict[str, Any]]:
    """One row per OSPF neighbour: its router id, state (FULL is healthy), address, interface."""
    rows: list[dict[str, Any]] = []
    if platform == "cisco_ios":
        for row in _ntc("show ip ospf neighbor", text):
            state, _, role = row.get("state", "").partition("/")
            rows.append(
                {
                    "neighbor_id": row.get("neighbor_id", ""),
                    "state": state,
                    "role": role.strip() or None,
                    "address": row.get("ip_address", ""),
                    "interface": short_interface(row.get("interface", "")),
                }
            )
        return rows

    info = _first(junos_json(text), "ospf-neighbor-information")
    for neighbor in _items(info, "ospf-neighbor"):
        rows.append(
            {
                "neighbor_id": _leaf(neighbor, "neighbor-id"),
                "state": _leaf(neighbor, "ospf-neighbor-state").upper(),
                "role": None,
                "address": _leaf(neighbor, "neighbor-address"),
                "interface": _leaf(neighbor, "interface-name"),
            }
        )
    return rows


_OSPF_PROCESS = re.compile(r'Routing Protocol is "ospf (?P<process>\d+)"')
_ROUTER_ID = re.compile(r"Router ID (?P<rid>\d+\.\d+\.\d+\.\d+)")
_NETWORK = re.compile(
    r"^\s+(?P<network>\d+\.\d+\.\d+\.\d+) (?P<wildcard>\d+\.\d+\.\d+\.\d+) area (?P<area>\S+)",
    re.MULTILINE,
)
_PASSIVE = re.compile(r"Passive Interface\(s\):\s*\n((?:\s+\S+\n?)+)")
_PROTOCOL = re.compile(r'Routing Protocol is "(?P<name>[^"]+)"')


def routing_protocols(text: str) -> dict[str, Any]:
    """Cisco `show ip protocols`: which routing protocols run; for OSPF its networks and areas."""
    ospf = _OSPF_PROCESS.search(text)
    router_id = _ROUTER_ID.search(text)
    passive = _PASSIVE.search(text)
    return {
        "protocols": [m["name"] for m in _PROTOCOL.finditer(text)],
        "ospf_process": ospf["process"] if ospf else None,
        "ospf_router_id": router_id["rid"] if router_id else None,
        "ospf_networks": [
            {"network": m["network"], "wildcard": m["wildcard"], "area": m["area"]}
            for m in _NETWORK.finditer(text)
        ],
        "passive_interfaces": passive.group(1).split() if passive else [],
    }


# ---------- neighbours (CDP / LLDP) ----------


def neighbors(platform: str, text: str) -> list[dict[str, Any]]:
    """Directly connected devices seen by CDP (Cisco) or LLDP (Junos)."""
    rows: list[dict[str, Any]] = []
    if platform == "cisco_ios":
        for row in _ntc("show cdp neighbors", text):
            rows.append(
                {
                    "local_interface": short_interface(cisco_interface(row["local_interface"])),
                    "neighbor": row.get("neighbor_name", "").split(".")[0],
                    "neighbor_interface": short_interface(
                        cisco_interface(row.get("neighbor_interface", ""))
                    ),
                    "neighbor_platform": row.get("platform", ""),
                    "protocol": "cdp",
                }
            )
        return rows

    info = _first(junos_json(text), "lldp-neighbors-information")
    for neighbor in _items(info, "lldp-neighbor-information"):
        rows.append(
            {
                "local_interface": _leaf(neighbor, "lldp-local-port-id")
                or _leaf(neighbor, "lldp-local-interface"),
                "neighbor": _leaf(neighbor, "lldp-remote-system-name"),
                "neighbor_interface": _leaf(neighbor, "lldp-remote-port-description")
                or _leaf(neighbor, "lldp-remote-port-id"),
                "neighbor_platform": "",
                "protocol": "lldp",
            }
        )
    return rows


def arp(platform: str, text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if platform == "cisco_ios":
        for row in _ntc("show arp", text):
            rows.append(
                {
                    "address": row.get("address", ""),
                    "mac": row.get("hardware_address", ""),
                    "interface": short_interface(row.get("interface", "")),
                    "age_min": row.get("age_min", ""),
                }
            )
        return rows
    info = _first(junos_json(text), "arp-table-information")
    for entry in _items(info, "arp-table-entry"):
        rows.append(
            {
                "address": _leaf(entry, "ip-address"),
                "mac": _leaf(entry, "mac-address"),
                "interface": _leaf(entry, "interface-name"),
                "age_min": "",
            }
        )
    return rows


# ---------- logs ----------

_CISCO_LOG_LINE = re.compile(r"%[A-Z0-9_]+-\d-[A-Z0-9_]+:")


def logs(platform: str, text: str, limit: int) -> list[str]:
    """The last `limit` log messages, oldest first."""
    if platform == "cisco_ios":
        lines = [line.strip() for line in text.splitlines() if _CISCO_LOG_LINE.search(line)]
    else:
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().endswith(">") and "---(more" not in line
        ]
    return lines[-limit:]


# ---------- ping ----------

_CISCO_PING = re.compile(r"Success rate is (\d+) percent \((\d+)/(\d+)\)")
_CISCO_RTT = re.compile(r"min/avg/max = \d+/(\d+)/\d+ ms")
_JUNOS_PING = re.compile(
    r"(\d+) packets transmitted, (\d+) packets received, ([\d.]+)% packet loss"
)
_JUNOS_RTT = re.compile(r"min/avg/max/stddev = [\d.]+/([\d.]+)/")
# The reply marks, one per packet: "!" a reply, "." a timeout, U/Q/M/?/& Cisco error codes.
_PING_MARKS = re.compile(r"^[!.UQM?&]+[ \t]*$", re.MULTILINE)


def _replies(text: str, sent: int, received: int) -> str | None:
    """The marks in packet order (e.g. ".!!!!"); None when missing or when they disagree with the
    counts (not one per packet, or a different number of replies)."""
    marks = "".join(line.strip() for line in _PING_MARKS.findall(text))
    return marks if len(marks) == sent and marks.count("!") == received else None


def ping(platform: str, text: str) -> dict[str, Any]:
    if platform == "cisco_ios":
        match = _CISCO_PING.search(text)
        if not match:
            raise ParseError("no ping result in the output")
        rtt = _CISCO_RTT.search(text)
        return {
            "sent": int(match[3]),
            "received": int(match[2]),
            "success_percent": int(match[1]),
            "avg_rtt_ms": float(rtt[1]) if rtt else None,
            "replies": _replies(text, int(match[3]), int(match[2])),
        }
    match = _JUNOS_PING.search(text)
    if not match:
        raise ParseError("no ping result in the output")
    rtt = _JUNOS_RTT.search(text)
    sent, received = int(match[1]), int(match[2])
    return {
        "sent": sent,
        "received": received,
        "success_percent": round(100 * received / sent) if sent else 0,
        "avg_rtt_ms": float(rtt[1]) if rtt else None,
        "replies": _replies(text, sent, received),
    }


# ---------- firewall ----------


def firewall_policies(text: str) -> list[dict[str, Any]]:
    """Junos security policies, in evaluation order per zone pair."""
    rows: list[dict[str, Any]] = []
    document = junos_json(text)
    info = _first(document, "security-policies")
    for context in _items(info, "security-context"):
        ctx = _first(context, "context-information")
        from_zone = _leaf(ctx, "source-zone-name")
        to_zone = _leaf(ctx, "destination-zone-name")
        for policies in _items(context, "policies"):
            for policy in _items(policies, "policy-information"):
                action = _first(policy, "policy-action")
                rows.append(
                    {
                        "from_zone": from_zone,
                        "to_zone": to_zone,
                        "name": _leaf(policy, "policy-name"),
                        "action": _leaf(action, "action-type"),
                        "sources": [
                            _leaf(a, "address-name")
                            for a in _items(_first(policy, "source-addresses"), "source-address")
                        ],
                        "destinations": [
                            _leaf(a, "address-name")
                            for a in _items(
                                _first(policy, "destination-addresses"), "destination-address"
                            )
                        ],
                        "applications": [
                            _leaf(a, "application-name")
                            for a in _items(_first(policy, "applications"), "application")
                        ],
                    }
                )
    return rows


def firewall_zones(text: str) -> list[dict[str, Any]]:
    """Junos security zones and the interfaces in each."""
    rows: list[dict[str, Any]] = []
    info = _first(junos_json(text), "zones-information")
    for zone in _items(info, "zones-security"):
        interfaces_node = _first(zone, "zones-security-interfaces")
        rows.append(
            {
                "zone": _leaf(zone, "zones-security-zonename"),
                "interfaces": [
                    _leaf(i, "zones-security-interface-name")
                    for i in _items(interfaces_node, "zones-security-interface")
                ],
            }
        )
    return rows
