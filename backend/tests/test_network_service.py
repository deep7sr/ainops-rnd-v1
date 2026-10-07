"""The network tools, run against the recorded lab outputs (replay: no device is contacted)."""

import json
from pathlib import Path

import pytest
from replay import ReplayExecutor

from ainops.network.audit import AuditLog
from ainops.network.capture import fixture_path
from ainops.network.redact import redact
from ainops.network.service import NetworkService, ToolFailure


def test_interfaces_by_alias(service: NetworkService) -> None:
    result = service.get_interfaces("maa-p2p")
    assert result.device == "IPLC-RTR-MAA"
    assert result.evidence.command == "show ip interface"
    assert result.evidence.source == "replay"
    by_name = {row["name"]: row for row in result.data}
    assert by_name["Fa2/0"]["status"] == "up"
    assert by_name["Fa2/0"]["ipv4"] == ["10.10.4.2/24"]
    assert by_name["Fa1/0"]["status"] == "admin-down"


def test_ospf_neighbors(service: NetworkService) -> None:
    result = service.get_ospf_neighbors("IPLC-RTR-MAA")
    assert result.summary == "2 OSPF neighbour(s), all FULL"
    assert {row["interface"] for row in result.data} == {"Fa2/0", "Fa0/0"}


def test_cdp_neighbors_use_short_interface_names(service: NetworkService) -> None:
    rows = service.get_neighbors("IPLC-RTR-MAA").data
    assert {"local_interface": "Fa2/0", "neighbor": "IPLC-RTR-TRV"}.items() <= rows[0].items()


def test_ping(service: NetworkService) -> None:
    result = service.ping("IPLC-RTR-MAA", "10.10.4.1")
    assert result.data["received"] == 5
    assert result.evidence.command == "ping 10.10.4.1"


@pytest.mark.parametrize(
    ("destination", "reason"),
    [
        ("8.8.8.8", "outside the private network ranges"),
        ("127.0.0.1", "outside the private network ranges"),
        ("224.0.0.5", "outside the private network ranges"),
        ("10.10.4", "not a valid IPv4 address"),
        ("10.10.4.1; reload", "not a valid IPv4 address"),
    ],
)
def test_ping_refuses_bad_destinations(
    service: NetworkService, destination: str, reason: str
) -> None:
    # Matching the reason matters: without it the test would also pass because replay has no
    # recording for the address (a pass for the wrong reason, found by a mutation check).
    with pytest.raises(ToolFailure, match=reason):
        service.ping("IPLC-RTR-MAA", destination)


def test_routes_refuse_public_destination(service: NetworkService) -> None:
    with pytest.raises(ToolFailure, match="outside the private network ranges"):
        service.get_routes("IPLC-RTR-MAA", "8.8.8.8")


@pytest.mark.parametrize("interface", ["Fa2/0; reload", "Fa2/0 | redirect x", "", "a" * 40])
def test_interface_detail_refuses_bad_names(service: NetworkService, interface: str) -> None:
    with pytest.raises(ToolFailure, match="not a valid interface"):
        service.get_interface_detail("IPLC-RTR-MAA", interface)


def test_unknown_device_lists_the_valid_names(service: NetworkService) -> None:
    with pytest.raises(ToolFailure, match="Known devices: ISP-TRV-1"):
        service.get_interfaces("R99")


def test_firewall_tool_on_a_router_is_not_supported(service: NetworkService) -> None:
    with pytest.raises(ToolFailure, match="not supported"):
        service.get_firewall_policies("IPLC-RTR-MAA")


def test_every_call_is_audited_without_device_output(
    service: NetworkService, audit: AuditLog
) -> None:
    service.get_interfaces("IPLC-RTR-MAA")
    with pytest.raises(ToolFailure):
        service.ping("IPLC-RTR-MAA", "8.8.8.8")
    first, second = audit.tail()
    assert first["outcome"] == "ok" and first["command"] == "show ip interface"
    assert second["outcome"] == "failed" and "outside the private" in second["reason"]
    assert "10.10.4.2" not in json.dumps(first)  # device output never goes to the audit log


def test_unparseable_output_comes_back_as_text(service: NetworkService, tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    path = fixture_path(fixtures, "IPLC-RTR-MAA", "ping 10.10.4.9")
    path.parent.mkdir(parents=True)
    path.write_text("something unexpected", encoding="utf-8")
    service.executor = ReplayExecutor(fixtures, delay_s=0)
    result = service.ping("IPLC-RTR-MAA", "10.10.4.9")
    assert result.data == {"raw_excerpt": "something unexpected"}
    assert result.note


def test_device_error_is_reported(service: NetworkService, tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    path = fixture_path(fixtures, "IPLC-RTR-MAA", "show ip route")
    path.parent.mkdir(parents=True)
    path.write_text("% Invalid input detected at '^' marker.", encoding="utf-8")
    service.executor = ReplayExecutor(fixtures, delay_s=0)
    with pytest.raises(ToolFailure, match="rejected the command"):
        service.get_routes("IPLC-RTR-MAA")


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("enable secret 5 $1$abcd$xyz", "$1$abcd$xyz"),
        ("username admin password 7 0822455D0A16", "0822455D0A16"),
        ("snmp-server community Publ1c RO", "Publ1c"),
        ("crypto isakmp key S3cr3t address 10.0.0.1", "S3cr3t"),
        ('"encrypted-password" : "$6$salt$hash"', "$6$salt$hash"),
        ('authentication-key "$9$AbCdEf"', "$9$AbCdEf"),
        ("pre-shared-key ascii-text MyPsk", "MyPsk"),
        # Junos hashes without any keyword in front (only the hash pattern catches these).
        ('"data" : "$9$qwErTy12"', "$9$qwErTy12"),
        ("secret-value $6$abc$def;", "$6$abc$def"),
    ],
)
def test_redaction_removes_secrets(text: str, secret: str) -> None:
    assert secret not in redact(text)
