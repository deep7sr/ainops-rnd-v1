"""How the simulated network behaves: everything a device shows is worked out here from the Lab.

- Interfaces: up when not shut. As in EVE-NG, a cable does not carry "link down": shutting one end
  leaves the other end up/up (the real lab's fault-1 recordings show exactly this).
- OSPF: an interface takes part when it is up, has an address and an OSPF network statement covers
  it. Two routers become FULL neighbours across a cable when both interfaces take part, neither is
  passive, and they are in the same subnet and area. On a two-router segment the higher router id
  is the DR (what the lab showed on 10-07).
- Routes: connected (C) and local (L) for every up interface with an address, OSPF (O) by shortest
  path over the FULL neighbours, cost 1 for FastEthernet/ge and 10 for Ethernet.
- Ping: the packet follows the routing tables hop by hop, there and back. At each hop the next
  device must have the address on the cabled interface (that is ARP answering). A router with no
  route drops it. A Junos firewall drops every packet on an interface that is in no security
  zone. A hop whose ARP entry is missing loses the first packet, like the real routers.
"""

import heapq
import ipaddress
import random
import time
from dataclasses import dataclass, field

from labsim.model import Device, End, Interface, Lab

IPv4 = ipaddress.IPv4Address
Network = ipaddress.IPv4Network

MAX_PATHS = 4  # "Maximum path: 4" in show ip protocols
OSPF_DISTANCE = 110


def up_addresses(device: Device) -> list[tuple[Interface, ipaddress.IPv4Interface]]:
    return [(i, i.address) for i in device.interfaces.values() if i.admin_up and i.address]


def owns(device: Device, address: IPv4) -> bool:
    return any(a.ip == address for _, a in up_addresses(device))


# ---------- OSPF ----------


def ospf_interfaces(device: Device) -> dict[str, str]:
    """Interface -> area, for the interfaces OSPF runs on (passive ones included)."""
    if device.ospf is None:
        return {}
    result = {}
    for interface, address in up_addresses(device):
        for network in device.ospf.networks:
            if network.matches(address.ip):
                result[interface.name] = network.area
                break
    return result


@dataclass(frozen=True)
class Adjacency:
    interface: str  # ours
    peer: str
    peer_interface: str
    peer_router_id: str
    peer_address: IPv4
    peer_role: str  # DR or BDR (two routers per segment in this lab)


def adjacencies(lab: Lab, name: str) -> list[Adjacency]:
    device = lab.devices[name]
    if device.ospf is None:
        return []
    ours = ospf_interfaces(device)
    result = []
    for interface, area in ours.items():
        if interface in device.ospf.passive:
            continue
        end = lab.peer(name, interface)
        if end is None:
            continue
        peer = lab.devices[end.device]
        if peer.ospf is None or peer.ospf.router_id == device.ospf.router_id:
            continue
        theirs = ospf_interfaces(peer)
        if theirs.get(end.interface) != area or end.interface in peer.ospf.passive:
            continue
        local = device.interfaces[interface].address
        remote = peer.interfaces[end.interface].address
        if local is None or remote is None or local.network != remote.network:
            continue
        higher = IPv4(peer.ospf.router_id) > IPv4(device.ospf.router_id)
        result.append(
            Adjacency(
                interface=interface,
                peer=peer.name,
                peer_interface=end.interface,
                peer_router_id=peer.ospf.router_id,
                peer_address=remote.ip,
                peer_role="DR" if higher else "BDR",
            )
        )
    return result


# ---------- routes ----------


@dataclass(frozen=True)
class Hop:
    address: IPv4 | None  # next hop (None: directly connected)
    interface: str


@dataclass(frozen=True)
class Route:
    prefix: Network
    code: str  # C, L, O (Cisco codes; Junos shows Direct, Local, OSPF)
    hops: tuple[Hop, ...]
    distance: int = 0
    metric: int = 0


def _shortest(lab: Lab, name: str) -> tuple[dict[str, int], dict[str, set[Hop]]]:
    """OSPF shortest paths from `name`: cost to each router, and the first hops towards it."""
    dist = {name: 0}
    first: dict[str, set[Hop]] = {name: set()}
    queue = [(0, name)]
    done: set[str] = set()
    while queue:
        cost, router = heapq.heappop(queue)
        if router in done:
            continue
        done.add(router)
        for adjacency in adjacencies(lab, router):
            step = cost + lab.devices[router].interfaces[adjacency.interface].cost
            hops = (
                {Hop(adjacency.peer_address, adjacency.interface)}
                if router == name
                else first[router]
            )
            known = dist.get(adjacency.peer)
            if known is None or step < known:
                dist[adjacency.peer] = step
                first[adjacency.peer] = set(hops)
                heapq.heappush(queue, (step, adjacency.peer))
            elif step == known:
                first[adjacency.peer] |= hops
    return dist, first


def routes(lab: Lab, name: str) -> list[Route]:
    device = lab.devices[name]
    table: dict[Network, Route] = {}
    for interface, address in up_addresses(device):
        table[address.network] = Route(address.network, "C", (Hop(None, interface.name),))
        local = Network(f"{address.ip}/32")
        table[local] = Route(local, "L", (Hop(None, interface.name),))

    if device.ospf is not None:
        dist, first = _shortest(lab, name)
        best: dict[Network, tuple[int, set[Hop]]] = {}
        for router, cost in dist.items():
            if router == name:
                continue
            other = lab.devices[router]
            for advertised in ospf_interfaces(other):
                stub = other.interfaces[advertised]
                assert stub.address is not None  # ospf_interfaces only lists addressed ones
                prefix = stub.address.network
                if prefix in table:
                    continue  # connected wins
                total = cost + stub.cost
                known = best.get(prefix)
                if known is None or total < known[0]:
                    best[prefix] = (total, set(first[router]))
                elif total == known[0]:
                    known[1].update(first[router])
        for prefix, (metric, hops) in best.items():
            ordered = sorted(hops, key=lambda h: (int(h.address or 0), h.interface))[:MAX_PATHS]
            table[prefix] = Route(prefix, "O", tuple(ordered), OSPF_DISTANCE, metric)

    if device.is_host and device.gateway is not None:
        default = Network("0.0.0.0/0")
        out = next((i.name for i, a in up_addresses(device) if device.gateway in a.network), "eth0")
        table[default] = Route(default, "S", (Hop(device.gateway, out),), 1, 0)

    return sorted(table.values(), key=lambda r: (int(r.prefix.network_address), r.prefix.prefixlen))


def lookup(lab: Lab, name: str, address: IPv4) -> Route | None:
    """The route the device uses for `address` (longest prefix match)."""
    matches = [r for r in routes(lab, name) if address in r.prefix]
    return max(matches, key=lambda r: r.prefix.prefixlen) if matches else None


# ---------- neighbours (CDP) and ARP ----------


def cdp_neighbors(lab: Lab, name: str) -> list[tuple[str, End]]:
    """(our interface, the other end) for every up cable to an up Cisco interface."""
    device = lab.devices[name]
    result = []
    for interface in device.interfaces.values():
        end = lab.peer(name, interface.name)
        if end is None or not interface.admin_up:
            continue
        peer = lab.devices[end.device]
        if peer.platform == "cisco_ios" and peer.interfaces[end.interface].admin_up:
            result.append((interface.name, end))
    return result


@dataclass
class ArpEntry:
    mac: str
    interface: str
    learned: float  # time.time()


@dataclass
class ArpCache:
    """What each device has learned by ARP. Lives as long as the simulator runs (like the real
    tables), so a fault does not wipe it: an entry stays until its own interface goes down."""

    tables: dict[str, dict[IPv4, ArpEntry]] = field(default_factory=dict)

    @classmethod
    def seeded(cls, lab: Lab, now: float | None = None) -> "ArpCache":
        """The tables a lab that has run for a while has: every directly cabled device (and the
        home router), but not the PCs, which only appear after traffic to them."""
        now = time.time() if now is None else now
        cache = cls()
        for a, b in lab.links:
            for here, there in ((a, b), (b, a)):
                device, other = lab.devices[here.device], lab.devices[there.device]
                if device.is_host or (other.is_host and other.gateway is not None):
                    continue
                local = device.interfaces[here.interface]
                remote = other.interfaces[there.interface]
                if not (local.admin_up and remote.admin_up and local.address and remote.address):
                    continue
                if remote.address.ip not in local.address.network:
                    continue
                age = random.Random(f"{here}{there}").uniform(0, 15 * 60)
                cache.learn(device.name, remote.address.ip, remote.mac, local.name, now - age)
        return cache

    def learn(
        self, device: str, address: IPv4, mac: str, interface: str, when: float | None = None
    ) -> None:
        self.tables.setdefault(device, {})[address] = ArpEntry(
            mac, interface, time.time() if when is None else when
        )

    def knows(self, device: str, address: IPv4) -> bool:
        return address in self.tables.get(device, {})


def arp_table(lab: Lab, name: str, cache: ArpCache) -> list[tuple[IPv4, str, str, float | None]]:
    """(address, MAC, interface, learned or None for our own address), sorted by address."""
    device = lab.devices[name]
    rows: dict[IPv4, tuple[IPv4, str, str, float | None]] = {}
    for own, address in up_addresses(device):
        rows[address.ip] = (address.ip, own.mac, own.name, None)
    for learned, entry in cache.tables.get(name, {}).items():
        local = device.interfaces[entry.interface]
        if learned in rows or not local.admin_up or local.address is None:
            continue
        if learned in local.address.network:
            rows[learned] = (learned, entry.mac, entry.interface, entry.learned)
    return [rows[a] for a in sorted(rows)]


# ---------- ping ----------


@dataclass
class Walk:
    status: str  # arrived, no_route (at `at`), dropped
    at: str
    links: int  # cables crossed
    arp: list[tuple[str, IPv4, str, str]] = field(default_factory=list)  # who, whom, mac, if


def _in_zone(device: Device, interface: str) -> bool:
    if device.zones is None:
        return True
    units = [unit for members in device.zones.values() for unit in members]
    return any(u == interface or u.startswith(interface + ".") for u in units)


def walk(lab: Lab, start: str, destination: IPv4) -> Walk:
    """Follow one packet from `start` to `destination` through the routing tables."""
    current, ingress, crossed = start, None, 0
    arp: list[tuple[str, IPv4, str, str]] = []
    for _ in range(32):
        device = lab.devices[current]
        if ingress is not None and not _in_zone(device, ingress):
            return Walk("dropped", current, crossed, arp)
        if owns(device, destination):
            return Walk("arrived", current, crossed, arp)
        if device.is_host and current != start:
            return Walk("dropped", current, crossed, arp)  # hosts do not forward
        route = lookup(lab, current, destination)
        if route is None:
            return Walk("no_route", current, crossed, arp)
        hop = route.hops[0]
        if not _in_zone(device, hop.interface):
            return Walk("dropped", current, crossed, arp)
        target = hop.address or destination
        end = lab.peer(current, hop.interface)
        if end is None:
            return Walk("dropped", current, crossed, arp)
        peer = lab.devices[end.device].interfaces[end.interface]
        if not peer.admin_up or peer.address is None or peer.address.ip != target:
            return Walk("dropped", current, crossed, arp)  # nobody answers ARP for the next hop
        arp.append((current, target, peer.mac, hop.interface))
        current, ingress, crossed = end.device, end.interface, crossed + 1
    return Walk("dropped", current, crossed, arp)  # a routing loop: the TTL runs out


def source_address(lab: Lab, name: str, destination: IPv4) -> IPv4 | None:
    """The address a router's ping comes from: its outgoing interface's address."""
    device = lab.devices[name]
    if owns(device, destination):
        return destination
    route = lookup(lab, name, destination)
    if route is None:
        return None
    address = device.interfaces[route.hops[0].interface].address
    return address.ip if address else None


@dataclass
class PingResult:
    marks: str  # one per packet: ! reply, . timeout, U unreachable
    rtts_ms: list[float]


def ping(lab: Lab, name: str, destination: IPv4, cache: ArpCache, count: int = 5) -> PingResult:
    """Every packet times out unless it gets there and the reply gets back. (With OSPF only, all
    routers know the same routes, so the "unreachable from a router in the middle" case of real
    networks cannot happen in this lab and is not simulated.)"""
    source = source_address(lab, name, destination)
    there = walk(lab, name, destination)
    if there.status != "arrived" or source is None:
        return PingResult("." * count, [])
    back = walk(lab, there.at, source)
    if back.status != "arrived":
        return PingResult("." * count, [])

    missed = False
    for who, whom, mac, interface in there.arp + back.arp:
        if lab.devices[who].is_host:
            continue  # a PC learns the router from the router's own ARP request
        if not cache.knows(who, whom):
            missed = True
            cache.learn(who, whom, mac, interface)
    crossings = there.links + back.links
    rng = random.Random()
    if crossings == 0:  # our own address
        rtts = [rng.uniform(0.5, 2) for _ in range(count)]
    else:
        rtts = [sum(rng.uniform(6, 25) for _ in range(crossings)) for _ in range(count)]
    marks = ("." if missed else "!") + "!" * (count - 1)
    return PingResult(marks, [r for r, m in zip(rtts, marks, strict=True) if m == "!"])
