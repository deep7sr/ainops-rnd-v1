"""The Inventory page: every device AINOPS knows, its status, and what is known about it.

Pure functions over data the API already has: the inventory file (which devices exist and how to
reach them), the knowledge graph snapshot (what the last discovery found), the cases and the saved
investigations. No device is contacted here: a live check is a separate, read-only tool call.

Status comes from the last discovery, never from polling:

    reached         the device answered the last discovery
    not_reached     it did not answer; its last known state is kept (and since when)
    not_discovered  it is in the inventory but no discovery has reached it yet
"""

from typing import Any, Literal

from ainops.cases import Case
from ainops.inventory import Device, Inventory

State = Literal["reached", "not_reached", "not_discovered"]


def device_status(
    name: str, graph_device: dict[str, Any] | None, discovery: dict[str, Any] | None
) -> dict[str, Any]:
    """What the last discovery says about one device."""
    if graph_device is None or discovery is None:
        return {"state": "not_discovered", "at": None, "last_seen": None, "error": None}
    at = discovery.get("at")
    failed = {
        entry.split(": ", 1)[0]: (entry.split(": ", 1) + [""])[1]
        for entry in discovery.get("devices_failed") or []
    }
    if name in failed:
        stale = [
            i["stale_since"] for i in graph_device.get("interfaces") or [] if i.get("stale_since")
        ]
        return {
            "state": "not_reached",
            "at": at,
            "last_seen": min(stale) if stale else None,
            "error": failed[name] or None,
        }
    return {"state": "reached", "at": at, "last_seen": at, "error": None}


def _connection(device: Device) -> str:
    return f"EVE-NG console, port {device.port}"  # production: management address (see docs)


def inventory_rows(
    inventory: Inventory,
    snapshot: dict[str, Any] | None,
    cases: list[Case] | None,
) -> list[dict[str, Any]]:
    """One row per inventory device, for the table. `None` inputs: the graph could not be read."""
    graph = {d["name"]: d for d in (snapshot or {}).get("devices") or []}
    discovery = (snapshot or {}).get("discovery")
    rows = []
    for device in inventory.devices:
        found = graph.get(device.name)
        interfaces = (found or {}).get("interfaces") or []
        addressed = [i for i in interfaces if i.get("ipv4")]
        mine = [c for c in cases or [] if device.name in c.draft.devices]
        rows.append(
            {
                "name": device.name,
                "aliases": list(device.aliases),
                "site": device.site,
                "site_name": inventory.sites.get(device.site, device.site),
                "role": device.role,
                "platform": device.platform,
                "description": device.description,
                "connection": _connection(device),
                "credential_ref": device.credential_ref,
                # Added on the Inventory page (removable there); None: in the hand-written file.
                "added": {"by": device.added_by, "at": device.added_at}
                if device.added_by
                else None,
                "status": device_status(device.name, found, discovery),
                "interfaces": {
                    "total": len(interfaces),
                    "addressed": len(addressed),
                    "addressed_down": sum(1 for i in addressed if i.get("status") != "up"),
                },
                "cases": None
                if cases is None
                else {
                    "total": len(mine),
                    "pending": sum(1 for c in mine if c.status == "pending"),
                },
            }  # fmt: skip
        )
    return rows


def device_detail(
    inventory: Inventory,
    device: Device,
    snapshot: dict[str, Any] | None,
    cases: list[Case] | None,
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Everything known about one device: graph facts, its cases, investigations that checked it.

    `runs` are saved investigations as {id, title, started_at, events, summary}.
    """
    snapshot = snapshot or {}
    found = next((d for d in snapshot.get("devices") or [] if d["name"] == device.name), None)
    links = [
        link
        for link in snapshot.get("links") or []
        if device.name in (link.get("a"), link.get("b"))
    ]
    peers = [p for p in snapshot.get("ospf_peers") or [] if p.get("device") == device.name]
    names = {device.name.upper(), *(a.upper() for a in device.aliases)}

    def checked(events: list[dict[str, Any]]) -> int:
        count = 0
        for event in events:
            if event.get("type") != "tool_result":
                continue
            named = event.get("device")
            if isinstance(named, str) and named.upper() in names:
                count += 1
        return count

    investigations = []
    for run in runs:
        n = checked(run["events"])
        if n:
            investigations.append(
                {
                    "id": run["id"],
                    "title": run["title"],
                    "started_at": run["started_at"],
                    "outcome": run["summary"].get("outcome"),
                    "checks": n,
                }
            )
    investigations.sort(key=lambda r: r["started_at"], reverse=True)
    mine = [c for c in cases or [] if device.name in c.draft.devices]
    return {
        "row": next(
            r for r in inventory_rows(inventory, snapshot, cases) if r["name"] == device.name
        ),
        "interfaces": (found or {}).get("interfaces") or [],
        "links": links,
        "ospf_peers": peers,
        "cases": None
        if cases is None
        else [
            {
                "id": c.id,
                "status": c.status,
                "question": c.question,
                "root_cause": c.root_cause,
                "updated_at": c.updated_at,
            }
            for c in sorted(mine, key=lambda c: c.updated_at, reverse=True)
        ],
        "investigations": investigations[:20],
    }
