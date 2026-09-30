"""The AINOPS topology MCP server: questions about the knowledge graph (Neo4j).

It never touches a device.

Run it with `uv run python -m ainops mcp-topology` (http://127.0.0.1:8102/mcp).

The agent uses it first: which device is meant, who owns an IP address, and which devices and
links lie on the path between two points. It then checks that path live with the network tools.
The graph is a snapshot from the last discovery run; every answer says when that was.
"""

import inspect
import ipaddress
from collections.abc import Callable
from functools import partial
from typing import Annotated, Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from ainops.config import get_settings
from ainops.topology.graph import GraphStore

INSTRUCTIONS = """\
The network knowledge graph of the TRV/MAA lab: sites, devices, interfaces, subnets and links,
built by automatic discovery (CDP/LLDP neighbours and shared subnets). Use it to resolve names and
IP addresses to devices and to find the path between two points before checking devices live.
"""

settings = get_settings()
mcp = FastMCP(
    "ainops-topology",
    instructions=INSTRUCTIONS,
    host="127.0.0.1",
    port=settings.mcp_topology_port,
)
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
_store: GraphStore | None = None


def store() -> GraphStore:
    global _store
    if _store is None:
        _store = GraphStore(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password.get_secret_value()
        )
    return _store


def tool(title: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        description = inspect.cleandoc(fn.__doc__ or "")
        return mcp.tool(title=title, description=description, annotations=READ_ONLY)(fn)

    return register


async def _run(fn: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
    try:
        result = await anyio.to_thread.run_sync(partial(fn, *args))
    except LookupError as error:
        raise ToolError(str(error)) from error
    last = store().last_discovery()
    result["graph_as_of"] = last["at"] if last else "never discovered"
    return result


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return True


def _resolve(point: str) -> tuple[str, dict[str, Any] | None]:
    """A device name/alias or an IP address -> (device name, how the IP was matched or None)."""
    if _is_ip(point):
        owners = store().owner_of_ip(point.strip())
        if not owners:
            raise LookupError(f"no device owns {point} and no known subnet contains it")
        return owners[0]["device"], owners[0]
    device = store().device(point)
    if device is None:
        names = ", ".join(d["name"] for d in store().devices())
        raise LookupError(f"'{point}' is not a known device. Known devices: {names}")
    return device["name"], None


def _summary() -> dict[str, Any]:
    snapshot = store().snapshot()
    discovery = snapshot["discovery"] or {}
    sites: dict[str, list[str]] = {}
    for device in snapshot["devices"]:
        sites.setdefault(device["site"], []).append(f"{device['name']} ({device['role']})")
    findings = discovery.get("findings", [])
    return {
        "summary": (
            f"{len(snapshot['devices'])} devices in {len(sites)} sites, "
            f"{len(snapshot['links'])} links, {len(findings)} discovery findings"
        ),
        "sites": sites,
        "device_count": len(snapshot["devices"]),
        "link_count": len(snapshot["links"]),
        "findings_from_last_discovery": discovery.get("findings", []),
        "devices_not_reached": discovery.get("devices_failed", []),
    }


def _find(query: str) -> dict[str, Any]:
    if _is_ip(query):
        owners = store().owner_of_ip(query.strip())
        if not owners:
            raise LookupError(f"no device owns {query} and no known subnet contains it")
        first = owners[0]
        return {
            "summary": f"{query}: {first['match']} {first['device']} {first['interface']}",
            "query": query,
            "ip_matches": owners,
        }
    device = store().device(query)
    if device is None:
        names = ", ".join(d["name"] for d in store().devices())
        raise LookupError(f"'{query}' is not a known device. Known devices: {names}")
    links = store().links(device["name"])
    return {
        "summary": (
            f"{device['name']}: {device['role']} at {device['site']}, "
            f"{len(device['interfaces'])} interfaces, {len(links)} links"
        ),
        "query": query,
        "device": device,
        "links": links,
    }


def _links(device: str) -> dict[str, Any]:
    name, _ = _resolve(device)
    links = store().links(name)
    peers = ", ".join(row["b"] if row["a"] == name else row["a"] for row in links)
    return {"summary": f"{len(links)} links: {peers or 'none'}", "device": name, "links": links}


def _path(source: str, destination: str) -> dict[str, Any]:
    start, start_match = _resolve(source)
    end, end_match = _resolve(destination)
    notes = []
    ends = (("source", source, start_match), ("destination", destination, end_match))
    for label, point, match in ends:
        if match:
            notes.append(
                f"{label} {point}: {match['match']} {match['device']} {match['interface']}"
            )
    if start == end:
        return {
            "summary": f"both points are on {start}",
            "source": start,
            "destination": end,
            "hops": [],
            "devices": [start],
            "notes": notes,
        }
    hops = store().path(start, end)
    if not hops:
        notes.append(f"no chain of known links connects {start} and {end}")
    devices = [start] + [hop["to"] for hop in hops]
    summary = (
        f"path {' -> '.join(devices)} ({len(hops)} hops)" if hops else f"no path {start} -> {end}"
    )
    return {
        "summary": summary,
        "source": start,
        "destination": end,
        "devices": devices,
        "hops": hops,
        "notes": notes,
    }


@tool("Topology summary")
async def get_topology_summary() -> dict[str, Any]:
    """Overview of the network: sites with their devices and roles, number of links, and anything
    the last discovery found suspicious (links down, mismatched addresses, unknown neighbours).
    A good first call when the question is broad ("is anything wrong in MAA?")."""
    return await _run(_summary)


@tool("List devices")
async def list_devices(
    site: Annotated[str | None, Field(description="Site code, e.g. TRV or MAA")] = None,
    role: Annotated[
        str | None, Field(description="Role, e.g. firewall, core, wan-router, isp-router")
    ] = None,
) -> dict[str, Any]:
    """Devices in the inventory, optionally only one site or one role."""

    def run() -> dict[str, Any]:
        devices = store().devices(site, role)
        return {"summary": f"{len(devices)} devices", "devices": devices}

    return await _run(run)


@tool("Find a device or IP")
async def find_device(
    query: Annotated[str, Field(description="Device name, alias (e.g. MAA-P2P) or IPv4 address")],
) -> dict[str, Any]:
    """Resolve what the user named: a device (with its interfaces, addresses and links) or an IP
    address (which device and interface owns it, or whose subnet it is in, e.g. a LAN host).
    Use this first whenever the question names a device or an address."""
    return await _run(_find, query)


@tool("Links of a device")
async def get_device_links(
    device: Annotated[str, Field(description="Device name or alias")],
) -> dict[str, Any]:
    """The links of one device: the neighbour at the other end, both interfaces, their status at the
    last discovery, the subnet, and how the link was found (cdp, lldp, subnet)."""
    return await _run(_links, device)


@tool("Path between two points")
async def get_path(
    source: Annotated[
        str, Field(description="Device name/alias or IPv4 address where traffic starts")
    ],
    destination: Annotated[
        str, Field(description="Device name/alias or IPv4 address it should reach")
    ],
) -> dict[str, Any]:
    """The chain of devices and links between two points, hop by hop with the interfaces on each
    side. IP addresses are mapped to the device that owns them (or the LAN they are in). Use it to
    decide which devices to check live, in order, for a reachability problem."""
    return await _run(_path, source, destination)


def main() -> None:
    mcp.run(transport="streamable-http")
