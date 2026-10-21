"""The AINOPS network MCP server: read-only troubleshooting tools for the lab routers and firewalls.

Run it with `uv run ainops mcp-network` (streamable HTTP on http://127.0.0.1:8101/mcp).
Test it without any LLM using the MCP Inspector: `npx @modelcontextprotocol/inspector`.

Each tool below is what an MCP client (our agent, the Inspector, Claude, VS Code...) sees: a name,
a description (the LLM chooses tools by reading it, so it says WHEN to use the tool) and typed
inputs. The commands behind the tools live in commands.yaml and are never part of the definition.
"""

import inspect
from collections.abc import Callable
from functools import partial
from typing import Annotated, Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from ainops.config import get_settings
from ainops.inventory import load_inventory, local_path
from ainops.network.audit import AuditLog
from ainops.network.executor import LiveExecutor
from ainops.network.service import (
    NetworkService,
    ToolFailure,
    ToolResult,
    TraceResult,
    load_commands,
)
from ainops.topology.graph import GraphStore

INSTRUCTIONS = """\
Read-only troubleshooting tools for the network devices of the TRV/MAA lab (Cisco IOS routers and
Juniper vSRX firewalls). Every tool takes a device name from the inventory (for example
IPLC-RTR-MAA or its alias MAA-P2P) and returns the same JSON shape whatever the vendor, with a
one-line `summary` and `evidence` (the command that ran and when). No tool can change a device.
"""

settings = get_settings()
mcp = FastMCP(
    "ainops-network",
    instructions=INSTRUCTIONS,
    host="127.0.0.1",
    port=settings.mcp_network_port,
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)

DeviceName = Annotated[
    str, Field(description="Device name or alias from the inventory, e.g. IPLC-RTR-MAA or MAA-P2P")
]


def tool(title: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a read-only tool; its docstring (without source indentation) is the description."""

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        description = inspect.cleandoc(fn.__doc__ or "")
        return mcp.tool(title=title, description=description, annotations=READ_ONLY)(fn)

    return register


_service: NetworkService | None = None


def build_service() -> NetworkService:
    if not settings.lab_eve_host:
        raise SystemExit("LAB_EVE_HOST is not set in the repo-root .env: AINOPS only works live")
    executor = LiveExecutor(settings.lab_eve_host)
    graph = GraphStore(
        settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password.get_secret_value()
    )
    return NetworkService(
        inventory=load_inventory(settings.lab_inventory),
        executor=executor,
        audit=AuditLog(settings.logs_dir / "network-audit.jsonl"),
        commands=load_commands(),
        # Read only: trace_route asks the knowledge graph which device owns a next-hop address,
        # get_ospf_neighbors which neighbours a router normally has, get_firewall_zones which
        # device each firewall port is cabled to.
        locate=graph.owner_of_ip,
        expected_ospf=graph.ospf_peers,
        cabling=graph.links,
    )


_inventory_seen: tuple[int | None, ...] | None = None


def _inventory_stamp() -> tuple[int | None, ...]:
    files = (settings.lab_inventory, local_path(settings.lab_inventory))
    return tuple(f.stat().st_mtime_ns if f.is_file() else None for f in files)


def service() -> NetworkService:
    """The service; its inventory is read again when a device was added or removed (the
    Inventory page writes inventory.local.yaml), so no restart is needed."""
    global _service, _inventory_seen
    stamp = _inventory_stamp()
    if _service is None:
        _service = build_service()
        _inventory_seen = stamp
    elif stamp != _inventory_seen:
        try:
            _service.inventory = load_inventory(settings.lab_inventory)
            _inventory_seen = stamp
        except ValueError:
            pass  # a broken file: keep the devices AINOPS had, try again on the next call
    return _service


async def _call[R: (ToolResult, TraceResult)](method: Callable[..., R], *args: Any) -> R:
    """Run a (blocking) tool in a worker thread so one slow console never blocks the server."""
    try:
        return await anyio.to_thread.run_sync(partial(method, *args))
    except ToolFailure as error:
        raise ToolError(str(error)) from error


@mcp.resource("lab://inventory", name="inventory", mime_type="application/json")
def inventory_resource() -> list[dict[str, Any]]:
    """The devices these tools can reach: name, site, role, platform, aliases."""
    return [
        {
            "name": d.name,
            "site": d.site,
            "role": d.role,
            "platform": d.platform,
            "aliases": list(d.aliases),
            "description": d.description,
        }
        for d in service().inventory.devices
    ]


@tool("Device facts")
async def get_device_facts(device: DeviceName) -> ToolResult:
    """Model, OS version and uptime of a device. Use to check whether a device rebooted recently
    (short uptime) or to confirm what it is."""
    return await _call(service().get_device_facts, device)


@tool("Interfaces")
async def get_interfaces(device: DeviceName) -> ToolResult:
    """All interfaces of a device with status (up, down, admin-down) and IPv4 addresses.
    Usually the FIRST check on a device: a link that is down or admin-down (shut) explains most
    reachability problems."""
    return await _call(service().get_interfaces, device)


@tool("Interface detail")
async def get_interface_detail(
    device: DeviceName,
    interface: Annotated[str, Field(description="Interface name, e.g. Fa2/0 or ge-0/0/1")],
) -> ToolResult:
    """Health of ONE interface: status, errors, CRC, drops, resets, last input/output or last flap.
    Use after get_interfaces when a link is up but traffic still fails or flaps."""
    return await _call(service().get_interface_detail, device, interface)


@tool("Routes")
async def get_routes(
    device: DeviceName,
    destination: Annotated[
        str | None,
        Field(description="Optional IPv4 address: return only the routes that cover it"),
    ] = None,
) -> ToolResult:
    """The routing table of a device. With `destination`, answers "does this device know how to
    reach this IP, and via which next hop?". A missing route explains why traffic cannot leave."""
    return await _call(service().get_routes, device, destination)


@tool("Trace the route")
async def trace_route(
    source: Annotated[
        str,
        Field(
            description="Device name/alias to start from, or the IPv4 address of a host or LAN "
            "where traffic starts (the walk starts at that LAN's gateway)"
        ),
    ],
    destination: Annotated[str, Field(description="IPv4 address the traffic should reach")],
) -> TraceResult:
    """Follow the routing tables hop by hop from the source towards the destination: the way
    traffic REALLY goes (each device's own choice of route), not just how devices are cabled.
    Each hop shows the route used (prefix, learned from connected/static/OSPF/BGP, next hop,
    distance/metric). Use it FIRST for "cannot reach" questions: where it stops is where to look.
    "no_route" = that device has no route (check its OSPF neighbours and interfaces towards the
    destination); "reached" = routing is fine in this direction (trace back from the destination
    side too, replies need a way back; then test with ping)."""
    return await _call(service().trace_route, source, destination)


@tool("OSPF neighbours")
async def get_ospf_neighbors(device: DeviceName) -> ToolResult:
    """OSPF neighbours of a router and their state. FULL is healthy; a missing neighbour or a state
    stuck in INIT/EXSTART means routes between sites are not exchanged. Compared with the
    neighbours the router had at discovery: one that is MISSING is reported as a problem, with
    the interface it should be on. Use when routes to the other site are missing."""
    return await _call(service().get_ospf_neighbors, device)


@tool("Routing protocols")
async def get_routing_protocols(device: DeviceName) -> ToolResult:
    """Which routing protocols run on a Cisco router and, for OSPF, which networks, areas and
    passive interfaces are configured. Use when an OSPF neighbour is missing but the link is up
    (wrong area, network not included, interface passive)."""
    return await _call(service().get_routing_protocols, device)


@tool("Connected neighbours (CDP/LLDP)")
async def get_neighbors(device: DeviceName) -> ToolResult:
    """Devices directly connected to this one, seen by CDP (Cisco) or LLDP (Juniper), with the
    local and remote interface. Use to confirm what is physically plugged in where."""
    return await _call(service().get_neighbors, device)


@tool("ARP table")
async def get_arp_table(device: DeviceName) -> ToolResult:
    """IP-to-MAC entries the device has learned. Use to see whether a next hop or host on a
    directly connected network has answered at layer 2."""
    return await _call(service().get_arp_table, device)


@tool("Recent logs")
async def get_logs(
    device: DeviceName,
    lines: Annotated[int, Field(description="How many recent messages (5-60)", ge=5, le=60)] = 30,
) -> ToolResult:
    """The most recent log messages (link up/down, neighbour changes, errors). Use to find WHEN
    something changed and what happened just before a problem."""
    return await _call(service().get_logs, device, lines)


@tool("Ping from a device")
async def ping(
    device: DeviceName,
    destination: Annotated[str, Field(description="IPv4 address to ping (private ranges only)")],
) -> ToolResult:
    """Send 5 pings FROM the device to an IPv4 address. Use to test reachability hop by hop along a
    path. Only use addresses from the question, the inventory or earlier tool results; never guess.
    Note: the lab vSRX firewalls do not answer pings to their own interfaces. Losing only the first
    ping (".!!!!") is normal: the router was looking up the address (ARP); it is not a problem."""
    return await _call(service().ping, device, destination)


@tool("Firewall policies")
async def get_firewall_policies(device: DeviceName) -> ToolResult:
    """Security policies of a Juniper firewall per zone pair, in order, with their action (permit,
    deny, reject). Use when the path crosses a firewall and routing looks fine."""
    return await _call(service().get_firewall_policies, device)


@tool("Firewall zones")
async def get_firewall_zones(device: DeviceName) -> ToolResult:
    """Security zones of a Juniper firewall and the interfaces in each. Use with
    get_firewall_policies to know which zone pair applies to a flow. Also reads the firewall's
    interfaces and reports any with an address that is in no zone: the firewall drops its
    traffic."""
    return await _call(service().get_firewall_zones, device)


def main() -> None:
    service()  # load inventory and commands now: fail at start, not on the first call
    mcp.run(transport="streamable-http")
