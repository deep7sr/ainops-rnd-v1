"""Discovery: build the knowledge graph from what the devices report. Plain code, no LLM.

For every device in the inventory it asks the network MCP server (the only way to reach devices)
for the interfaces and the CDP/LLDP neighbours, then works out the links:
- a CDP/LLDP neighbour on an interface is a link (if the neighbour is in the inventory);
- two devices with addresses in the same subnet are linked (this finds the vSRX firewalls,
  which do not speak CDP).
It also reports what looks wrong: links that are down, neighbours not in the inventory, both ends
of a CDP link in different subnets, addressed interfaces with no known peer.
Then it compares with the previous graph (links added/removed, interfaces changed) and replaces it.

A device that does not answer never erases what the graph knew about it: its last known interfaces
and links are kept, marked `stale_since` (when it last answered). If no device answers at all (the
lab is off, the network MCP server cannot reach anything), the graph is not changed.

It also learns each router's normal OSPF neighbours (OSPF_PEER): every neighbour seen FULL. A
neighbour that is missing later stays expected as long as the link to it is in the graph, so a
discovery that runs during an outage does not make the outage look normal. The OSPF check of the
network MCP server compares with these to report a neighbour that is missing.
"""

import asyncio
import ipaddress
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from ainops.inventory import Inventory
from ainops.topology.graph import GraphStore, InterfaceFact, LinkFact, OspfPeer

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class DeviceReport:
    interfaces: list[dict[str, Any]] = field(default_factory=list)
    neighbors: list[dict[str, Any]] = field(default_factory=list)
    ospf: list[dict[str, Any]] | None = None  # None: not known (not asked, or the call failed)
    error: str | None = None


@dataclass
class DiscoveryResult:
    at: str
    source: str
    devices_ok: list[str]
    devices_failed: list[str]
    interfaces: list[InterfaceFact]
    links: list[LinkFact]
    findings: list[str]
    added_links: list[str]
    removed_links: list[str]
    ospf_peers: list[OspfPeer] = field(default_factory=list)
    devices_kept: list[str] = field(default_factory=list)  # did not answer: last known state kept
    graph_updated: bool = True  # False when no device answered and the graph was left as it was

    def summary(self) -> dict[str, Any]:
        """Flat values only: stored as the (:Discovery) node and shown in the UI."""
        return {
            "at": self.at,
            "source": self.source,
            "devices_ok": self.devices_ok,
            "devices_failed": self.devices_failed,
            "interface_count": len(self.interfaces),
            "link_count": len(self.links),
            "ospf_peer_count": len(self.ospf_peers),
            "findings": self.findings,
            "added_links": self.added_links,
            "removed_links": self.removed_links,
            "devices_kept": self.devices_kept,
            "graph_updated": self.graph_updated,
        }


def build_links(
    inventory: Inventory, reports: dict[str, DeviceReport]
) -> tuple[list[InterfaceFact], list[LinkFact], list[str]]:
    """Interfaces, links and findings from the per-device answers (pure: unit-tested)."""
    known = {d.name for d in inventory.devices}
    interfaces = [
        InterfaceFact(device=name, name=row["name"], status=row["status"], ipv4=list(row["ipv4"]))
        for name, report in reports.items()
        for row in report.interfaces
    ]
    by_end = {(i.device, i.name): i for i in interfaces}
    links: dict[str, LinkFact] = {}
    findings: list[str] = []

    def add(link: LinkFact) -> None:
        existing = links.get(link.key)
        if existing is None:
            links[link.key] = link
        else:
            existing.sources = sorted(set(existing.sources) | set(link.sources))
            existing.subnet = existing.subnet or link.subnet

    # 1. CDP / LLDP neighbours.
    for name, report in reports.items():
        for n in report.neighbors:
            neighbor = n["neighbor"]
            if neighbor not in known:
                findings.append(
                    f"{name} {n['local_interface']} sees '{neighbor}' ({n['protocol'].upper()}), "
                    "which is not in the inventory"
                )
                continue
            local = by_end.get((name, n["local_interface"]))
            remote = by_end.get((neighbor, n["neighbor_interface"]))
            local_nets = set(local.subnets()) if local else set()
            remote_nets = set(remote.subnets()) if remote else set()
            shared = sorted(local_nets & remote_nets)
            if local_nets and remote_nets and not shared:
                findings.append(
                    f"Address mismatch: {name} {n['local_interface']} ({', '.join(local.ipv4)}) "  # type: ignore[union-attr]
                    f"and {neighbor} {n['neighbor_interface']} ({', '.join(remote.ipv4)}) are "  # type: ignore[union-attr]
                    "connected but in different subnets"
                )
            add(
                LinkFact(
                    a=name,
                    a_interface=n["local_interface"],
                    b=neighbor,
                    b_interface=n["neighbor_interface"],
                    subnet=shared[0] if shared else None,
                    sources=[n["protocol"]],
                )
            )

    # 2. Shared subnets.
    members: dict[str, list[InterfaceFact]] = defaultdict(list)
    for interface in interfaces:
        for cidr in interface.subnets():
            if ipaddress.ip_network(cidr).prefixlen < 31:
                members[cidr].append(interface)
    for cidr, group in sorted(members.items()):
        for i, first in enumerate(group):
            for second in group[i + 1 :]:
                if first.device != second.device:
                    add(
                        LinkFact(
                            a=first.device,
                            a_interface=first.name,
                            b=second.device,
                            b_interface=second.name,
                            subnet=cidr,
                            sources=["subnet"],
                        )
                    )

    # 3. What looks wrong.
    linked_ends = {(link.a, link.a_interface) for link in links.values()} | {
        (link.b, link.b_interface) for link in links.values()
    }
    for link in sorted(links.values(), key=lambda x: x.key):
        down = [
            f"{d} {i} is {by_end[(d, i)].status}"
            for d, i in ((link.a, link.a_interface), (link.b, link.b_interface))
            if (d, i) in by_end and by_end[(d, i)].status != "up"
        ]
        if down:
            findings.append(f"Link {link.a} - {link.b} is not up: {'; '.join(down)}")
    for interface in interfaces:
        if interface.ipv4 and (interface.device, interface.name) not in linked_ends:
            findings.append(
                f"{interface.device} {interface.name} ({', '.join(interface.ipv4)}, "
                f"{interface.status}) has no known peer: a LAN or uplink, or a mis-addressed link"
            )
    return interfaces, sorted(links.values(), key=lambda x: x.key), findings


async def collect(
    network_url: str, inventory: Inventory, progress: ProgressCallback | None = None
) -> tuple[dict[str, DeviceReport], str]:
    """Ask the network MCP server about every device (4 at a time: one console each)."""
    reports: dict[str, DeviceReport] = {}
    source = "unknown"
    limit = asyncio.Semaphore(4)
    async with (
        streamablehttp_client(network_url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        async def one(name: str) -> None:
            nonlocal source
            async with limit:
                if progress:
                    await progress({"type": "device_started", "device": name})
                report = DeviceReport()
                result = await session.call_tool("get_interfaces", {"device": name})
                if result.isError or not result.structuredContent:
                    report.error = _error_text(result)
                else:
                    report.interfaces = result.structuredContent["data"]
                    source = result.structuredContent["evidence"]["source"]
                    neighbors = await session.call_tool("get_neighbors", {"device": name})
                    if not neighbors.isError and neighbors.structuredContent:
                        data = neighbors.structuredContent["data"]
                        report.neighbors = data if isinstance(data, list) else []
                    ospf = await session.call_tool("get_ospf_neighbors", {"device": name})
                    if not ospf.isError and ospf.structuredContent:
                        data = ospf.structuredContent["data"]
                        report.ospf = data if isinstance(data, list) else None
                reports[name] = report
                if progress:
                    await progress(
                        {
                            "type": "device_done",
                            "device": name,
                            "ok": report.error is None,
                            "interfaces": len(report.interfaces),
                            "neighbors": len(report.neighbors),
                            "error": report.error,
                        }
                    )

        await asyncio.gather(*(one(d.name) for d in inventory.devices))
    return reports, source


def _error_text(result: Any) -> str:
    try:
        return str(result.content[0].text)[:300]
    except (AttributeError, IndexError):
        return "no answer"


def ospf_peers(
    reports: dict[str, DeviceReport],
    interfaces: list[InterfaceFact],
    links: list[LinkFact],
    previous: list[dict[str, Any]],
) -> list[OspfPeer]:
    """The OSPF neighbours each router normally has (pure: unit-tested).

    Learned from the neighbours seen FULL now; a neighbour seen before stays expected while a link
    between the two devices is still in the graph (it may be missing because of a fault).
    """
    owner = {str(ipaddress.ip_interface(cidr).ip): i.device for i in interfaces for cidr in i.ipv4}
    peers: dict[str, OspfPeer] = {}
    for name, report in reports.items():
        for row in report.ospf or []:
            peer = owner.get(str(row.get("address") or ""))
            if row.get("state") == "FULL" and peer and peer != name:
                found = OspfPeer(
                    device=name,
                    peer=peer,
                    interface=str(row.get("interface") or ""),
                    address=str(row["address"]),
                    neighbor_id=str(row.get("neighbor_id") or ""),
                )
                peers[found.key] = found
    linked = {frozenset((link.a, link.b)) for link in links}
    for row in previous:
        kept = OspfPeer(
            device=row["device"],
            peer=row["peer"],
            interface=row["interface"],
            address=row["address"],
            neighbor_id=row.get("neighbor_id") or "",
        )
        if kept.key not in peers and frozenset((kept.device, kept.peer)) in linked:
            peers[kept.key] = kept
    return sorted(peers.values(), key=lambda p: p.key)


def plan_update(
    inventory: Inventory,
    reports: dict[str, DeviceReport],
    previous: dict[str, Any],
    source: str,
    at: str,
) -> DiscoveryResult:
    """What the graph should hold after this run (pure: unit-tested).

    `previous` is GraphStore.snapshot(): the graph before the run.
    """
    usable = {name: r for name, r in reports.items() if r.error is None}
    failed = sorted(f"{n}: {r.error}" for n, r in reports.items() if r.error)
    last_at = (previous.get("discovery") or {}).get("at")
    previous_keys = {row["key"] for row in previous.get("links", [])}
    if not usable:
        return DiscoveryResult(
            at=at,
            source=source,
            devices_ok=[],
            devices_failed=failed,
            interfaces=[],
            links=[],
            findings=[
                "No device answered: the knowledge graph was not changed (it still shows the "
                f"discovery of {last_at or 'never: it is empty'})"
            ],
            added_links=[],
            removed_links=[],
            graph_updated=False,
        )

    # Devices that did not answer: link them with what the graph knew about them.
    unanswered = {name for name, r in reports.items() if r.error}
    kept: dict[str, str] = {}  # device -> since when its data is not refreshed
    combined = dict(usable)
    for device in previous.get("devices", []):
        name, known = device["name"], device.get("interfaces") or []
        if name not in unanswered or not known:
            continue
        since = next((i["stale_since"] for i in known if i.get("stale_since")), None)
        kept[name] = since or last_at or at
        combined[name] = DeviceReport(
            interfaces=[
                {"name": i["name"], "status": i["status"], "ipv4": list(i.get("ipv4") or [])}
                for i in known
            ]
        )

    interfaces, links, findings = build_links(inventory, combined)
    for interface in interfaces:
        interface.stale_since = kept.get(interface.device)
    found = {link.key for link in links}
    for row in previous.get("links", []):  # e.g. a CDP link only the silent device reported
        if row["key"] not in found and (row["a"] in kept or row["b"] in kept):
            links.append(
                LinkFact(
                    a=row["a"],
                    a_interface=row["a_interface"],
                    b=row["b"],
                    b_interface=row["b_interface"],
                    subnet=row.get("subnet"),
                    sources=list(row.get("sources") or []),
                )
            )
    for link in links:
        since = [kept[end] for end in (link.a, link.b) if end in kept]
        link.stale_since = min(since) if since else None
    links.sort(key=lambda x: x.key)
    findings += [
        f"{name} did not answer: its interfaces and links as of {since} are kept, marked not "
        "refreshed"
        for name, since in sorted(kept.items())
    ]

    current = {link.key for link in links}

    def answered(key: str) -> bool:  # a link can only be "removed" if both ends answered
        return all(end.split(":", 1)[0] in usable for end in key.split("|"))

    return DiscoveryResult(
        at=at,
        source=source,
        devices_ok=sorted(usable),
        devices_failed=failed,
        interfaces=interfaces,
        links=links,
        ospf_peers=ospf_peers(usable, interfaces, links, previous.get("ospf_peers", [])),
        findings=findings,
        added_links=sorted(current - previous_keys) if previous_keys else [],
        removed_links=sorted(k for k in previous_keys - current if answered(k)),
        devices_kept=sorted(kept),
    )


async def discover(
    network_url: str,
    inventory: Inventory,
    store: GraphStore,
    progress: ProgressCallback | None = None,
) -> DiscoveryResult:
    previous = store.snapshot()
    reports, source = await collect(network_url, inventory, progress)
    at = datetime.now(UTC).isoformat(timespec="seconds")
    result = plan_update(inventory, reports, previous, source, at)
    if result.graph_updated:
        store.replace_topology(
            inventory, result.interfaces, result.links, result.summary(), result.ospf_peers
        )
    return result
