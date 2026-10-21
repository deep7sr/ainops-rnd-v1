"""The console in the UI: the command a tool runs (from commands.yaml) and the first lines of what
the device answered. The lines are for people only: redacted, short, and never read by the AI."""

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from ainops.agent.runner import _compact, _without_excerpt
from ainops.api.app import app
from ainops.inventory import Device
from ainops.network.audit import AuditLog
from ainops.network.executor import RawOutput
from ainops.network.service import (
    TOOL_COMMANDS,
    NetworkService,
    command_catalog,
    load_commands,
    output_excerpt,
)

NETWORK_SERVER = Path(__file__).parents[1] / "src" / "ainops" / "network" / "server.py"


def test_a_tool_result_carries_the_first_lines_of_the_output(service: NetworkService) -> None:
    result = service.get_interfaces("IPLC-RTR-MAA")
    lines = result.evidence.excerpt
    real = [line for line in lines if line != "…"]
    assert len(real) == 12
    assert all(line.strip() and len(line) <= 120 for line in real)
    # A long answer shows every interface's heading, so the down one is on screen, in order.
    assert real[0] == "FastEthernet0/0 is up, line protocol is up"
    assert "FastEthernet1/0 is administratively down, line protocol is down" in real
    assert "FastEthernet2/0 is up, line protocol is up" in real
    assert "…" in lines  # left-out lines are marked, never hidden


class _LeakyExecutor:
    """A device answer with secrets in it, not redacted by the executor."""

    mode = "test"

    def run(self, device: Device, command: str) -> RawOutput:
        text = (
            "username admin password 7 0822455D0A16\n"
            "enable secret 5 $1$abcd$xyz\n"
            "Cisco IOS Software, Version 15.2(4)M7\n"
        )
        return RawOutput(command, text, "live", 5, None)


def test_the_excerpt_is_redacted_whatever_the_executor_did(
    service: NetworkService, audit: AuditLog
) -> None:
    leaky = NetworkService(service.inventory, _LeakyExecutor(), audit, service.commands)
    lines = leaky.get_device_facts("IPLC-RTR-MAA").evidence.excerpt
    joined = "\n".join(lines)
    assert "0822455D0A16" not in joined
    assert "$1$abcd$xyz" not in joined
    assert "<redacted>" in joined and "Version 15.2(4)M7" in joined


def test_the_excerpt_is_capped() -> None:
    lines = output_excerpt("\n".join(["x" * 300] * 40 + ["", "   "]))
    assert lines[:12] == ["x" * 120] * 12
    assert lines[12:] == ["…"]
    assert output_excerpt("a\n  b\n\nc") == ["a", "  b", "c"]  # short answers whole


def test_the_ai_never_reads_the_excerpt() -> None:
    payload = {
        "device": "IPLC-RTR-MAA",
        "summary": "3 interfaces",
        "data": [],
        "evidence": {"command": "show ip interface", "source": "live", "excerpt": ["MARKER-LINE"]},
    }
    assert "MARKER-LINE" not in _compact(payload)


def test_an_address_only_in_the_excerpt_is_not_one_the_ai_saw() -> None:
    payload = {
        "summary": "ping 10.10.4.1: 5/5",
        "evidence": {"command": "ping 10.10.4.1", "excerpt": ["Sending to 172.16.99.9"]},
    }
    seen = _without_excerpt(payload)
    assert "10.10.4.1" in seen
    assert "172.16.99.9" not in seen


def test_every_network_tool_has_its_command_entry() -> None:
    source = NETWORK_SERVER.read_text("utf-8")
    tools = re.findall(r"^@tool\([^\n]*\)\nasync def (\w+)", source, re.M)
    assert sorted(tools) == sorted(TOOL_COMMANDS)
    commands = load_commands()
    for tool, key in TOOL_COMMANDS.items():
        assert any(key in table for table in commands.values()), tool


def test_the_catalog_names_each_command_by_tool() -> None:
    catalog = command_catalog(load_commands())
    assert catalog["cisco_ios"]["get_ospf_neighbors"] == "show ip ospf neighbor"
    assert catalog["cisco_ios"]["ping"] == "ping {destination}"
    assert catalog["cisco_ios"]["trace_route"] == "show ip route"
    assert "get_firewall_zones" not in catalog["cisco_ios"]  # not supported on IOS
    assert catalog["juniper_junos"]["get_firewall_zones"].startswith("show security zones")


def test_the_api_serves_the_catalog() -> None:
    response = TestClient(app).get("/api/commands")
    assert response.status_code == 200
    body = response.json()
    assert body == json.loads(json.dumps(command_catalog(load_commands())))
