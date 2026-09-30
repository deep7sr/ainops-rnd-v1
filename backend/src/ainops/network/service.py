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
from ainops.network import parsers
from ainops.network.audit import AuditLog
from ainops.network.executor import (
    DeviceUnreachableError,
    Executor,
    NoRecordingError,
    RawOutput,
)
from ainops.network.guard import CommandRefusedError

COMMANDS_FILE = Path(__file__).with_name("commands.yaml")

_INTERFACE = re.compile(r"^[A-Za-z]{1,20}-?\d{1,3}(?:/\d{1,3}){0,3}(?:\.\d{1,5})?$")
_RAW_EXCERPT = 2500


class ToolFailure(Exception):
    """The tool could not do what was asked. The message is safe to show to the LLM and the user."""


class Evidence(BaseModel):
    """Where a result came from: shown in the UI and cited in the diagnosis."""

    command: str
    source: str  # "live" (from the device now) or "replay" (a recorded output)
    collected_at: str
    duration_ms: int


class ToolResult(BaseModel):
    device: str
    site: str
    role: str
    platform: str
    summary: str  # one line, written by code, e.g. "2 OSPF neighbours, 1 not FULL"
    data: Any
    evidence: Evidence
    note: str | None = None


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
            if raw.device_error:
                handled = tolerate_device_error(raw.device_error) if tolerate_device_error else None
                if handled is None:
                    raise ToolFailure(f"{device.name} rejected the command: {raw.device_error}")
                data, summary = handled
            else:
                try:
                    data, summary = parse(device, raw)
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
            NoRecordingError,
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

        return self._run("get_interfaces", device, "interfaces", parse)

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
            "get_interface_detail", device, "interface_detail", parse, args={"interface": name}
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

        return self._run("get_routes", device, "routes", parse)

    def get_ospf_neighbors(self, device: str) -> ToolResult:
        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            rows = parsers.ospf_neighbors(d.platform, raw.text)
            if not rows:
                return rows, "no OSPF neighbours"
            not_full = [f"{r['neighbor_id']} ({r['state']})" for r in rows if r["state"] != "FULL"]
            summary = f"{len(rows)} OSPF neighbour(s)"
            summary += f"; not FULL: {', '.join(not_full)}" if not_full else ", all FULL"
            return rows, summary

        def not_running(error: str) -> tuple[Any, str] | None:
            if "not running" in error.lower():
                return [], "OSPF is not running on this device"
            return None

        return self._run(
            "get_ospf_neighbors", device, "ospf_neighbors", parse, tolerate_device_error=not_running
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
            return result, (
                f"ping {target}: {result['received']}/{result['sent']} replies "
                f"({result['success_percent']}%){rtt}"
            )

        return self._run("ping", device, "ping", parse, args={"destination": target})

    def get_firewall_policies(self, device: str) -> ToolResult:
        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            rows = parsers.firewall_policies(raw.text)
            denies = [r["name"] for r in rows if r["action"] in ("deny", "reject")]
            summary = f"{len(rows)} policies"
            summary += f"; deny/reject: {', '.join(denies)}" if denies else "; none deny traffic"
            return rows, summary

        return self._run("get_firewall_policies", device, "firewall_policies", parse)

    def get_firewall_zones(self, device: str) -> ToolResult:
        def parse(d: Device, raw: RawOutput) -> tuple[Any, str]:
            rows = parsers.firewall_zones(raw.text)
            text = "; ".join(f"{r['zone']}: {', '.join(r['interfaces']) or '-'}" for r in rows)
            return rows, text or "no security zones"

        return self._run("get_firewall_zones", device, "firewall_zones", parse)
