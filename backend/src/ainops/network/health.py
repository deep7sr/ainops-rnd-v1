"""A verdict on each tool result, worked out by code from the parsed data (never by the LLM).

The UI colours the device on the live map with it, and the agent reads it with the result:
- "ok":      the check passed (addressed interfaces up, OSPF neighbours FULL, ping replied);
- "problem": the check found something wrong, listed in `issues` (with the interface, if any);
- "info":    the tool only reports facts and does not judge them (ARP table, logs, policies).
"""

from typing import Any, Literal

from pydantic import BaseModel


class Issue(BaseModel):
    text: str  # one short sentence for an engineer, e.g. "Fa2/0 is administratively down"
    interface: str | None = None


class Health(BaseModel):
    status: Literal["ok", "problem", "info"]
    issues: list[Issue] = []


INFO = Health(status="info")


def _verdict(issues: list[Issue]) -> Health:
    return Health(status="problem", issues=issues) if issues else Health(status="ok")


def interfaces(rows: list[dict[str, Any]]) -> Health:
    """Only interfaces with an address count: unused ports are often shut on purpose."""
    issues = []
    for row in rows:
        if not row["ipv4"] or row["status"] == "up":
            continue
        state = "administratively down (shut)" if row["status"] == "admin-down" else "down"
        issues.append(Issue(text=f"{row['name']} is {state}", interface=row["name"]))
    return _verdict(issues)


def interface_detail(detail: dict[str, Any], name: str) -> Health:
    interface = detail.get("name") or name
    issues = []
    status = str(detail.get("link_status") or detail.get("oper_status") or "").lower()
    if status and status != "up":
        issues.append(Issue(text=f"{interface} is {status}", interface=interface))
    errors = str(detail.get("input_errors") or "0")
    if errors.isdigit() and int(errors) > 0:
        issues.append(Issue(text=f"{interface} has {errors} input errors", interface=interface))
    return _verdict(issues)


def missing_ospf(
    rows: list[dict[str, Any]], expected: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Expected neighbours (seen FULL at discovery) that are not in the neighbour table at all."""
    present = {r.get("address") for r in rows} | {r.get("neighbor_id") for r in rows}
    return [
        e
        for e in expected
        if e.get("address") not in present and e.get("neighbor_id") not in present
    ]


def ospf_neighbors(
    rows: list[dict[str, Any]], expected: list[dict[str, Any]] | None = None
) -> Health:
    """`expected`: the neighbours this router normally has (knowledge graph). Without it only the
    neighbours that are there can be judged, and a missing one goes unnoticed."""
    issues = [
        Issue(
            text=f"OSPF neighbour {r['neighbor_id']} is {r['state']}, not FULL",
            interface=r.get("interface") or None,
        )
        for r in rows
        if r["state"] != "FULL"
    ]
    issues += [
        Issue(
            text=f"OSPF neighbour {e['peer']} ({e['address']}) on {e['interface']} is missing: "
            "it was FULL at discovery",
            interface=e.get("interface") or None,
        )
        for e in missing_ospf(rows, expected or [])
    ]
    if not rows and not issues:
        issues.append(Issue(text="no OSPF neighbours"))
    return _verdict(issues)


def routes_to(destination: str, matches: list[dict[str, Any]]) -> Health:
    return _verdict([] if matches else [Issue(text=f"no route to {destination}")])


def first_lost_only(result: dict[str, Any]) -> bool:
    """Only the first packet lost (".!!!!"): normal, the router was looking up the next hop's
    hardware address (ARP) and dropped the packet while it waited."""
    sent: int = result["sent"]
    return sent > 1 and result.get("replies") == "." + "!" * (sent - 1)


def ping(result: dict[str, Any]) -> Health:
    sent, received = result["sent"], result["received"]
    if received == 0:
        return _verdict([Issue(text=f"no replies from {result['destination']} (0/{sent})")])
    if received < sent and not first_lost_only(result):
        return _verdict(
            [Issue(text=f"{sent - received} of {sent} pings to {result['destination']} lost")]
        )
    return Health(status="ok")
