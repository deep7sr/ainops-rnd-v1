"""Follow the routing tables hop by hop from a device to a destination: the way traffic really goes.

The knowledge graph knows how devices are cabled; only the routing tables say which way a packet is
sent. Code, not the LLM, walks them:
1. read the routing table of the current device (the normal read-only command, on the device);
2. take the route the device itself uses: the most specific prefix that covers the destination.
   The table already holds only the winners: the device chose between static, OSPF, BGP... by
   administrative distance and then metric. We show that choice; we do not redo it;
3. a connected or local route means the destination is on this device's own network: arrived;
4. otherwise find the device that owns the next-hop address (from the knowledge graph), confirm
   with that device's own table (it has a local route for the address) and repeat from there.
The walk stops where a route is missing, at a loop, where traffic leaves the devices AINOPS
knows, at a device that does not answer, or after MAX_HOPS devices.
"""

import ipaddress
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

MAX_HOPS = 12
ARRIVED = ("connected", "direct", "local")  # Junos calls a connected route "direct"

Status = Literal["reached", "no_route", "loop", "left_network", "device_failed", "too_many_hops"]


@dataclass
class TableRead:
    """One device's routing table as read by the network tools."""

    device: str
    site: str
    rows: list[dict[str, Any]] | None  # None: the table could not be read or parsed
    command: str
    source: str  # "live" (tests replay recorded outputs)
    duration_ms: int
    error: str | None = None


ReadTable = Callable[[str], TableRead]
# Interfaces that own an address, as GraphStore.owner_of_ip returns them.
Locate = Callable[[str], list[dict[str, Any]]]


@dataclass
class Trace:
    status: Status
    hops: list[dict[str, Any]]
    summary: str
    stopped_at: str  # the device where the walk ended


def _covering(rows: list[dict[str, Any]], destination: str) -> list[dict[str, Any]]:
    """Routes for the most specific prefix covering `destination` (several = equal-cost paths)."""
    address = ipaddress.ip_address(destination)
    best: list[dict[str, Any]] = []
    best_length = -1
    for row in rows:
        try:
            network = ipaddress.ip_network(row["prefix"], strict=False)
        except ValueError:
            continue
        if address not in network or network.prefixlen < best_length:
            continue
        if network.prefixlen > best_length:
            best, best_length = [], network.prefixlen
        best.append(row)
    return best


def _owns(rows: list[dict[str, Any]], address: str) -> bool:
    return any(r["protocol"] == "local" and r["prefix"] == f"{address}/32" for r in rows)


def owner(locate: Locate, address: str) -> str | None:
    """The device that has `address` on one of its interfaces, according to the graph."""
    for row in locate(address):
        if row.get("match") == "owns this address":
            return str(row["device"])
    return None


def walk(start: str, destination: str, read: ReadTable, locate: Locate) -> Trace:
    hops: list[dict[str, Any]] = []
    visited: set[str] = set()
    current = start
    confirm: str | None = None  # next-hop address the current device should own
    for _ in range(MAX_HOPS):
        table = read(current)
        visited.add(table.device)
        hop: dict[str, Any] = {
            "device": table.device,
            "site": table.site,
            "route": None,
            "equal_paths": 0,
            "next_hop_device": None,
            "note": None,
            "command": table.command,
            "source": table.source,
        }
        hops.append(hop)
        if table.rows is None:
            hop["note"] = table.error or "the routing table could not be read"
            return Trace(
                "device_failed",
                hops,
                f"{_lead(hops)}could not read the routing table of {table.device}: {hop['note']}",
                table.device,
            )
        if confirm and not _owns(table.rows, confirm):
            hop["note"] = (
                f"its routing table has no local route for {confirm}: the knowledge graph may be "
                "out of date (run discovery)"
            )
        routes = _covering(table.rows, destination)
        if not routes:
            return Trace(
                "no_route",
                hops,
                f"{_lead(hops)}{table.device} has no route to {destination} "
                "(no matching route and no default route)",
                table.device,
            )
        route = routes[0]
        hop["route"] = route
        hop["equal_paths"] = len(routes)
        if route["protocol"] in ARRIVED:
            where = route["interface"] or route["prefix"]
            return Trace(
                "reached",
                hops,
                f"{_lead(hops)}{destination} is on {table.device}'s own network "
                f"{route['prefix']} ({where}); the route is complete in this direction",
                table.device,
            )
        next_hop = route["next_hop"]
        nxt = owner(locate, next_hop) if next_hop else None
        if nxt is None:
            leaves = f"towards {next_hop}" if next_hop else f"out of {route['interface']}"
            return Trace(
                "left_network",
                hops,
                f"{_lead(hops)}{table.device} sends it {leaves} via {route['prefix']} "
                f"({route['protocol']}), to a device AINOPS does not know",
                table.device,
            )
        hop["next_hop_device"] = nxt
        if nxt.upper() in (v.upper() for v in visited):
            return Trace(
                "loop",
                hops,
                f"{_chain(hops)} -> {nxt}: routing loop, {table.device} sends it back to {nxt}",
                table.device,
            )
        current, confirm = nxt, next_hop
    return Trace(
        "too_many_hops",
        hops,
        f"{_lead(hops)}stopped after {MAX_HOPS} devices without arriving",
        hops[-1]["device"],
    )


def _chain(hops: list[dict[str, Any]]) -> str:
    return " -> ".join(h["device"] for h in hops)


def _lead(hops: list[dict[str, Any]]) -> str:
    """The devices walked, before the sentence about the last one (none for a single device)."""
    return f"{_chain(hops)}: " if len(hops) > 1 else ""
