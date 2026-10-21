"""What each network tool does, independent of MCP (so it can be tested directly).

Every tool follows the same steps:
1. find the device in the inventory (unknown names are refused with the list of valid names);
2. validate the arguments (interface names, IP addresses) against strict patterns;
3. look the command up in commands.yaml (no command for this platform = not supported);
4. run it through the executor (guard -> device or recording -> redaction);
5. parse the output into the shared JSON shape and write a one-line summary;
6. write an audit record.
"""

import ipaddress
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from ainops.inventory import Device, Inventory, UnknownDeviceError
from ainops.network import health, parsers, trace
from ainops.network.audit import AuditLog
from ainops.network.executor import (
    DeviceUnreachableError,
    Executor,
    RawOutput,
)
from ainops.network.guard import CommandRefusedError
from ainops.network.health import Health, Issue

COMMANDS_FILE = Path(__file__).with_name("commands.yaml")

_INTERFACE = re.compile(r"^[A-Za-z]{1,20}-?\d{1,3}(?:/\d{1,3}){0,3}(?:\.\d{1,5})?$")
_RAW_EXCERPT = 2500


class ToolFailure(Exception):
    """The tool could not do what was asked. The message is safe to show to the LLM and the user."""


class Evidence(BaseModel):
    """Where a result came from: shown in the UI and cited in the diagnosis."""

    command: str
    source: str  # "live": from the device now (only tests replay recorded outputs)
    collected_at: str
    duration_ms: int


class ToolResult(BaseModel):
    device: str
    site: str
    role: str
    platform: str
    summary: str  # one line, written by code, e.g. "2 OSPF neighbours, 1 not FULL"
    data: Any
    health: Health  # verdict worked out by code: ok / problem (with issues) / info
    evidence: Evidence
    note: str | None = None


class TraceResult(BaseModel):
    """trace_route: one result for the whole walk; `data.hops` has one entry per device."""

    device: str  # where the walk started
    site: str
    summary: str
    data: dict[str, Any]
    health: Health
    evidence: Evidence


def load_commands(path: Path = COMMANDS_FILE) -> dict[str, dict[str, str]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {platform: dict(commands) for platform, commands in raw.items()}


def validate_interface(name: str) -> str:
    cleaned = name.strip()
    if not _INTERFACE.fullmatch(cleaned):
        raise ToolFailure(
            f"'{name}' is not a valid interface name (examples: Fa2/0, FastEthernet2/0, ge-0/0/1)"
        )
    return cleaned


def validate_ipv4(value: str, *, what: str) -> str:
    try:
        address = ipaddress.IPv4Address(value.strip())
    except ValueError as error:
        raise ToolFailure(f"{what} '{value}' is not a valid IPv4 address") from error
    if not address.is_private or address.is_loopback or address.is_multicast:
        raise ToolFailure(f"{what} {address} is outside the private network ranges AINOPS may test")
    return str(address)


@dataclass
class NetworkService:
    inventory: Inventory
    executor: Executor
    audit: AuditLog
    commands: dict[str, dict[str, str]]
    # Which device owns an IP address (GraphStore.owner_of_ip); only trace_route needs it.
    locate: trace.Locate | None = None
    # The OSPF neighbours a router normally has (GraphStore.ospf_peers), to spot a missing one.
    expected_ospf: Callable[[str], list[dict[str, Any]]] | None = None
    # The cables of a device (GraphStore.links): which device each firewall port faces.
    cabling: Callable[[str], list[dict[str, Any]]] | None = None

    # ---------- plumbing ----------

    def _device(self, name: str) -> Device:
        try:
            return self.inventory.get(name)
        except UnknownDeviceError as error:
            raise ToolFailure(str(error)) from error

    def _run(
        self,
        tool: str,
        device_name: str,
        key: str,
        parse: Callable[[Device, RawOutput], tuple[Any, str]],
        *,
        args: dict[str, str] | None = None,
        assess: Callable[[Any], Health] = lambda data: health.INFO,
        tolerate_device_error: Callable[[str], tuple[Any, str] | None] | None = None,
    ) -> ToolResult:
        args = args or {}
        started = time.monotonic()
        device: Device | None = None
        command = ""
        try:
            device = self._device(device_name)
            template = self.commands.get(device.platform, {}).get(key)
            if template is None:
                raise ToolFailure(
                    f"{tool} is not supported on {device.name} ({device.platform}, {device.role})"
                )
            command = template.format(**args)
            raw = self.executor.run(device, command)
            note = None
            verdict = health.INFO
            if raw.device_error:
                handled = tolerate_device_error(raw.device_error) if tolerate_device_error else None
                if handled is None:
                    raise ToolFailure(f"{device.name} rejected the command: {raw.device_error}")
                data, summary = handled
            else:
                try:
                    data, summary = parse(device, raw)
                    verdict = assess(data)
                except parsers.ParseError as error:
                    data = {"raw_excerpt": raw.text[:_RAW_EXCERPT]}
                    summary = "output returned as text (it could not be parsed)"
                    note = str(error)
            result = ToolResult(
                device=device.name,
                site=device.site,
                role=device.role,
                platform=device.platform,
                summary=summary,
                data=data,
                health=verdict,
                evidence=Evidence(
                    command=raw.command,
                    source=raw.source,
                    collected_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    duration_ms=raw.duration_ms,
                ),
                note=note,
            )
        except (
            ToolFailure,
            CommandRefusedError,
            DeviceUnreachableError,
        ) as error:
            self.audit.write(
                tool=tool,
                device=device.name if device else device_name,
                args=args,
                command=command or None,
                outcome="refused" if isinstance(error, CommandRefusedError) else "failed",
                reason=str(error),
                source=self.executor.mode,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            if isinstance(error, CommandRefusedError):
                raise ToolFailure(f"safety check refused the command: {error}") from error
            if isinstance(error, ToolFailure):
                raise
            raise ToolFailure(str(error)) from error
        self.audit.write(
            tool=tool,
            device=result.device,
            args=args,
            command=command,
            outcome="ok",
            summary=result.summary,
            source=result.evidence.source,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return result

    # ---------- tools ----------

    def get_device_facts(self, device: str) -> ToolResult:
        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            facts = parsers.facts(d.platform, raw.text)
            summary = f"{facts['os']} {facts['version']}".strip()
            if facts.get("uptime"):
                summary += f", up {facts['uptime']}"
            return facts, summary

        return self._run("get_device_facts", device, "facts", parse)

    def get_interfaces(self, device: str) -> ToolResult:
        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            rows = parsers.interfaces(d.platform, raw.text)
            down = [r["name"] for r in rows if r["status"] != "up" and r["ipv4"]]
            summary = f"{len(rows)} interfaces"
            summary += (
                f"; with an address but not up: {', '.join(down)}"
                if down
                else "; all addressed interfaces up"
            )
            return rows, summary

        return self._run("get_interfaces", device, "interfaces", parse, assess=health.interfaces)

    def _audit_invalid(
        self, tool: str, device: str, args: dict[str, str], error: Exception
    ) -> None:
        self.audit.write(
            tool=tool,
            device=device,
            args=args,
            command=None,
            outcome="failed",
            reason=str(error),
            source=self.executor.mode,
            duration_ms=0,
        )

    def get_interface_detail(self, device: str, interface: str) -> ToolResult:
        try:
            name = validate_interface(interface)
        except ToolFailure as error:
            self._audit_invalid("get_interface_detail", device, {"interface": interface}, error)
            raise

        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            detail = parsers.interface_detail(d.platform, raw.text)
            status = detail.get("link_status") or detail.get("oper_status") or "unknown"
            errors = detail.get("input_errors") or "0"
            return detail, f"{detail.get('name') or name} is {status}; input errors {errors}"

        return self._run(
            "get_interface_detail",
            device,
            "interface_detail",
            parse,
            args={"interface": name},
            assess=lambda detail: health.interface_detail(detail, name),
        )

    def get_routes(self, device: str, destination: str | None = None) -> ToolResult:
        try:
            target = validate_ipv4(destination, what="destination") if destination else None
        except ToolFailure as error:
            self._audit_invalid("get_routes", device, {"destination": str(destination)}, error)
            raise

        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            rows = parsers.routes(d.platform, raw.text)
            if target is None:
                protocols = sorted({r["protocol"] for r in rows})
                return rows, f"{len(rows)} routes ({', '.join(protocols) or 'none'})"
            matches = parsers.matching_routes(rows, target)
            if not matches:
                return {"destination": target, "routes": []}, f"no route to {target}"
            best = matches[0]
            via = best["next_hop"] or best["interface"] or "directly connected"
            return (
                {"destination": target, "routes": matches},
                f"{target} is reached via {best['prefix']} ({best['protocol']}) -> {via}",
            )

        def assess(data: Any) -> Health:
            if target is None:
                return health.INFO
            return health.routes_to(target, data["routes"])

        return self._run("get_routes", device, "routes", parse, assess=assess)

    def _expected_ospf(self, device: str) -> tuple[list[dict[str, Any]], str]:
        """The neighbours the device normally has, and a note when they could not be read."""
        if self.expected_ospf is None:
            return [], ""
        try:
            name = self.inventory.get(device).name
        except UnknownDeviceError:
            return [], ""  # the tool itself reports the unknown device
        try:
            return self.expected_ospf(name), ""
        except Exception:  # noqa: BLE001 - the graph driver raises its own errors; the check
            # still runs without the comparison and says so
            return [], " (expected neighbours not checked: knowledge graph not reachable)"

    def get_ospf_neighbors(self, device: str) -> ToolResult:
        expected, unchecked = self._expected_ospf(device)

        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            rows = parsers.ospf_neighbors(d.platform, raw.text)
            gone = health.missing_ospf(rows, expected)
            missing = [f"{e['peer']} on {e['interface']}" for e in gone]
            if not rows:
                summary = "no OSPF neighbours"
            else:
                not_full = [
                    f"{r['neighbor_id']} ({r['state']})" for r in rows if r["state"] != "FULL"
                ]
                summary = f"{len(rows)} OSPF neighbour(s)"
                summary += f"; not FULL: {', '.join(not_full)}" if not_full else ", all FULL"
            if missing:
                summary += f"; MISSING (FULL at discovery): {', '.join(missing)}"
            return rows, summary + unchecked

        def not_running(error: str) -> tuple[Any, str] | None:
            if "not running" in error.lower():
                return [], "OSPF is not running on this device"
            return None

        return self._run(
            "get_ospf_neighbors",
            device,
            "ospf_neighbors",
            parse,
            assess=lambda rows: health.ospf_neighbors(rows, expected),
            tolerate_device_error=not_running,
        )

    def get_routing_protocols(self, device: str) -> ToolResult:
        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            info = parsers.routing_protocols(raw.text)
            summary = f"protocols: {', '.join(info['protocols']) or 'none'}"
            if info["ospf_networks"]:
                nets = ", ".join(f"{n['network']} area {n['area']}" for n in info["ospf_networks"])
                summary += f"; OSPF networks: {nets}"
            return info, summary

        return self._run("get_routing_protocols", device, "routing_protocols", parse)

    def get_neighbors(self, device: str) -> ToolResult:
        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            rows = parsers.neighbors(d.platform, raw.text)
            names = ", ".join(f"{r['neighbor']} on {r['local_interface']}" for r in rows)
            return rows, f"{len(rows)} neighbour(s): {names}" if rows else "no neighbours seen"

        def lldp_off(error: str) -> tuple[Any, str] | None:
            if "lldp" in error.lower() or "not running" in error.lower():
                return [], "neighbour discovery (LLDP) is not enabled on this device"
            return None

        return self._run(
            "get_neighbors", device, "neighbors", parse, tolerate_device_error=lldp_off
        )

    def get_arp_table(self, device: str) -> ToolResult:
        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            rows = parsers.arp(d.platform, raw.text)
            return rows, f"{len(rows)} ARP entries"

        return self._run("get_arp_table", device, "arp", parse)

    def get_logs(self, device: str, lines: int = 30) -> ToolResult:
        limit = max(5, min(int(lines), 60))

        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            entries = parsers.logs(d.platform, raw.text, limit)
            return entries, f"last {len(entries)} log messages" if entries else "no log messages"

        return self._run("get_logs", device, "logs", parse)

    def ping(self, device: str, destination: str) -> ToolResult:
        try:
            target = validate_ipv4(destination, what="destination")
        except ToolFailure as error:
            self._audit_invalid("ping", device, {"destination": destination}, error)
            raise

        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            result = parsers.ping(d.platform, raw.text)
            result["destination"] = target
            rtt = f", avg {result['avg_rtt_ms']:g} ms" if result["avg_rtt_ms"] is not None else ""
            arp = (
                "; first lost: normal (the router was looking up the address, ARP)"
                if health.first_lost_only(result)
                else ""
            )
            return result, (
                f"ping {target}: {result['received']}/{result['sent']} replies "
                f"({result['success_percent']}%){rtt}{arp}"
            )

        return self._run(
            "ping", device, "ping", parse, args={"destination": target}, assess=health.ping
        )

    def get_firewall_policies(self, device: str) -> ToolResult:
        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            rows = parsers.firewall_policies(raw.text)
            denies = [r["name"] for r in rows if r["action"] in ("deny", "reject")]
            summary = f"{len(rows)} policies"
            summary += f"; deny/reject: {', '.join(denies)}" if denies else "; none deny traffic"
            return rows, summary

        return self._run("get_firewall_policies", device, "firewall_policies", parse)

    def _firewall_interfaces(self, device: str) -> tuple[list[dict[str, Any]] | None, str]:
        """The firewall's interfaces, to find addressed ones in no zone (None: not checked)."""
        try:
            platform = self.inventory.get(device).platform
        except UnknownDeviceError:
            return None, ""  # the tool itself reports the unknown device
        if "firewall_zones" not in self.commands.get(platform, {}):
            return None, ""  # the tool itself reports that zones are not supported here
        try:
            result = self.get_interfaces(device)
        except ToolFailure as error:
            return None, f" (interfaces not checked: {error})"
        if not isinstance(result.data, list):
            return None, " (interfaces not checked: their output could not be parsed)"
        return result.data, ""

    def _faces(self, device: str) -> tuple[dict[str, str], str]:
        """Port -> the device its cable goes to ('ISP-TRV-1 Fa1/0, isp-router'), from the
        knowledge graph, so a zone is never suggested by guessing which side is outside."""
        if self.cabling is None:
            return {}, ""
        try:
            name = self.inventory.get(device).name
        except UnknownDeviceError:
            return {}, ""  # the tool itself reports the unknown device
        try:
            links = self.cabling(name)
        except Exception:  # noqa: BLE001 - the graph driver raises its own errors
            return {}, " (cabling not checked: knowledge graph not reachable)"
        roles = {d.name: d.role for d in self.inventory.devices}
        faces = {}
        for link in links:
            mine, peer = ("a", "b") if link["a"] == name else ("b", "a")
            role = roles.get(link[peer])
            faces[link[f"{mine}_interface"]] = f"{link[peer]} {link[f'{peer}_interface']}" + (
                f", {role}" if role else ""
            )
        return faces, ""

    def get_firewall_zones(self, device: str) -> ToolResult:
        interfaces, unchecked = self._firewall_interfaces(device)
        faces, not_cabled = self._faces(device) if interfaces else ({}, "")

        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            rows = parsers.firewall_zones(raw.text)
            text = "; ".join(f"{r['zone']}: {', '.join(r['interfaces']) or '-'}" for r in rows)
            outside = health.outside_zones(rows, interfaces or [])
            if outside:
                listed = ", ".join(
                    f"{r['name']} ({', '.join([*r['ipv4'], *_cabled(faces, r['name'])])})"
                    for r in outside
                )
                text = (text + "; " if text else "") + f"NOT IN ANY ZONE: {listed}; {ZONE_NOTE}"
            return rows, (text or "no security zones") + unchecked + not_cabled

        return self._run(
            "get_firewall_zones",
            device,
            "firewall_zones",
            parse,
            assess=lambda rows: health.firewall_zones(rows, interfaces, faces),
        )

    def trace_route(self, source: str, destination: str) -> TraceResult:
        args = {"source": source, "destination": destination}
        started = time.monotonic()
        try:
            target = validate_ipv4(destination, what="destination")
            start, start_note = self._trace_start(source)
        except ToolFailure as error:
            self._audit_invalid("trace_route", source, args, error)
            raise

        def read(name: str) -> trace.TableRead:
            try:
                result = self.get_routes(name)
            except ToolFailure as error:
                return trace.TableRead(name, "", None, "", self.executor.mode, 0, str(error))
            rows = result.data if isinstance(result.data, list) else None
            return trace.TableRead(
                device=result.device,
                site=result.site,
                rows=rows,
                command=result.evidence.command,
                source=result.evidence.source,
                duration_ms=result.evidence.duration_ms,
                error=None if rows is not None else result.note,
            )

        try:
            walked = trace.walk(start, target, read, self._locate)
        except ToolFailure as error:
            self._audit_invalid("trace_route", start, args, error)
            raise
        sources = {h["source"] for h in walked.hops}
        result = TraceResult(
            device=walked.hops[0]["device"],
            site=walked.hops[0]["site"],
            summary=walked.summary,
            data={
                "source": source,
                "destination": target,
                "start_note": start_note,
                "status": walked.status,
                "stopped_at": walked.stopped_at,
                "path": [h["device"] for h in walked.hops],
                "hops": walked.hops,
            },
            health=_trace_health(walked, target),
            evidence=Evidence(
                command="; ".join(dict.fromkeys(h["command"] for h in walked.hops if h["command"])),
                source=sources.pop() if len(sources) == 1 else "live",
                collected_at=datetime.now(UTC).isoformat(timespec="seconds"),
                duration_ms=int((time.monotonic() - started) * 1000),
            ),
        )
        self.audit.write(
            tool="trace_route",
            device=result.device,
            args=args,
            command=None,
            outcome="ok",
            summary=result.summary,
            source=result.evidence.source,
            duration_ms=result.evidence.duration_ms,
        )
        return result

    def _locate(self, address: str) -> list[dict[str, Any]]:
        if self.locate is None:
            raise ToolFailure(
                "trace_route needs the knowledge graph to know which device owns an address"
            )
        try:
            return self.locate(address)
        except Exception as error:  # the graph driver raises its own errors
            raise ToolFailure(f"the knowledge graph could not be read: {error}") from error

    def _trace_start(self, source: str) -> tuple[str, str | None]:
        """A device name, or the device whose network holds the source address (its gateway)."""
        text = source.strip()
        try:
            address = str(ipaddress.ip_interface(text).ip)
        except ValueError:
            return self._device(text).name, None
        validate_ipv4(address, what="source")
        rows = self._locate(address)
        owners = trace.owner(lambda _: rows, address)
        if owners:
            return owners, None
        gateways = {str(r["device"]): r for r in rows}
        if not gateways:
            raise ToolFailure(f"no device in the knowledge graph has {address} in its networks")
        if len(gateways) > 1:
            names = ", ".join(sorted(gateways))
            raise ToolFailure(
                f"{address} is in a network shared by {names}: give the device to start from"
            )
        name, row = next(iter(gateways.items()))
        return name, f"{address} is on {name}'s network {row['subnet']} ({row['interface']})"


# What a fix needs besides the zone (Junos SRX): zones alone pass no traffic.
ZONE_NOTE = (
    "a zone alone is not enough: traffic between two zones also needs a security policy, and "
    "ping to the firewall itself needs host-inbound ping in that zone"
)


def _cabled(faces: dict[str, str], port: str) -> list[str]:
    return [f"cabled to {faces[port]}"] if port in faces else []


def _trace_health(walked: trace.Trace, destination: str) -> Health:
    if walked.status == "reached":
        return Health(status="ok")
    if walked.status == "no_route":
        return Health(
            status="problem",
            issues=[Issue(text=f"{walked.stopped_at} has no route to {destination}")],
        )
    if walked.status == "loop":
        return Health(
            status="problem",
            issues=[Issue(text=f"routing loop: {walked.stopped_at} sends {destination} back")],
        )
    return health.INFO  # left the known network, a device did not answer, too many hops
