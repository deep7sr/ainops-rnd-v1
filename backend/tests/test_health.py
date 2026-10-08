"""The code-computed verdict on tool results (what colours a device on the live map)."""

from pathlib import Path

import pytest

from ainops.network import health
from ainops.network.service import NetworkService


def row(name: str, status: str, ipv4: list[str]) -> dict[str, object]:
    return {"name": name, "status": status, "ipv4": ipv4}


def test_interfaces_ok_when_every_addressed_interface_is_up() -> None:
    rows = [row("Fa0/0", "up", ["10.10.5.1/24"]), row("E1/0", "admin-down", [])]
    assert health.interfaces(rows).status == "ok"  # unused shut ports are not a problem


def test_shut_interface_with_an_address_is_a_problem_naming_the_interface() -> None:
    rows = [row("Fa0/0", "up", ["10.10.5.1/24"]), row("Fa2/0", "admin-down", ["10.10.4.2/24"])]
    verdict = health.interfaces(rows)
    assert verdict.status == "problem"
    assert [(i.text, i.interface) for i in verdict.issues] == [
        ("Fa2/0 is administratively down (shut)", "Fa2/0")
    ]


def test_down_interface_is_told_apart_from_a_shut_one() -> None:
    verdict = health.interfaces([row("Fa2/0", "down", ["10.10.4.1/24"])])
    assert verdict.issues[0].text == "Fa2/0 is down"


def test_ospf_neighbours() -> None:
    full = {"neighbor_id": "10.10.5.1", "state": "FULL", "interface": "Fa2/0"}
    stuck = {"neighbor_id": "10.10.4.1", "state": "INIT", "interface": "Fa2/0"}
    assert health.ospf_neighbors([full]).status == "ok"
    assert health.ospf_neighbors([]).issues[0].text == "no OSPF neighbours"
    verdict = health.ospf_neighbors([full, stuck])
    assert verdict.status == "problem"
    assert verdict.issues[0].text == "OSPF neighbour 10.10.4.1 is INIT, not FULL"
    assert verdict.issues[0].interface == "Fa2/0"


def test_ping() -> None:
    def result(received: int) -> dict[str, object]:
        return {"sent": 5, "received": received, "destination": "192.168.200.10"}

    assert health.ping(result(5)).status == "ok"
    assert health.ping(result(0)).issues[0].text == "no replies from 192.168.200.10 (0/5)"
    assert health.ping(result(3)).issues[0].text == "2 of 5 pings to 192.168.200.10 lost"


def ping_result(replies: str | None) -> dict[str, object]:
    received = 4 if replies is None else replies.count("!")
    return {"sent": 5, "received": received, "replies": replies, "destination": "10.10.4.1"}


def test_ping_losing_only_the_first_packet_is_normal() -> None:
    # Cisco "4/5, first lost": the router looked up the next hop's address (ARP) first.
    assert health.ping(ping_result(".!!!!")) == health.Health(status="ok")


@pytest.mark.parametrize("replies", ["!.!!!", "!!!!.", "..!!!", ".!!!U", "U!!!!", None])
def test_any_other_loss_is_still_a_problem(replies: str | None) -> None:
    verdict = health.ping(ping_result(replies))
    assert verdict.status == "problem"
    assert verdict.issues[0].text.endswith("pings to 10.10.4.1 lost")


def test_one_packet_ping_that_failed_is_a_problem() -> None:
    lone = {"sent": 1, "received": 0, "replies": ".", "destination": "10.10.4.1"}
    assert health.ping(lone).status == "problem"
    assert not health.first_lost_only(lone)  # the summary must not call it normal either


def test_routes_and_interface_detail() -> None:
    assert health.routes_to("192.168.200.10", []).issues[0].text == "no route to 192.168.200.10"
    assert health.routes_to("192.168.200.10", [{"prefix": "192.168.200.0/24"}]).status == "ok"
    detail = {"name": "Fa2/0", "link_status": "administratively down", "input_errors": "12"}
    texts = [i.text for i in health.interface_detail(detail, "Fa2/0").issues]
    assert texts == ["Fa2/0 is administratively down", "Fa2/0 has 12 input errors"]
    clean = {"name": "Fa2/0", "link_status": "up", "input_errors": "0"}
    assert health.interface_detail(clean, "Fa2/0").status == "ok"


def test_tools_that_only_report_facts_do_not_judge(service: NetworkService) -> None:
    assert service.get_arp_table("IPLC-RTR-MAA").health.status == "info"
    assert service.get_routing_protocols("IPLC-RTR-MAA").health.status == "info"


def test_service_attaches_the_verdict(service: NetworkService) -> None:
    assert service.get_interfaces("IPLC-RTR-MAA").health.status == "ok"
    assert service.get_ospf_neighbors("IPLC-RTR-MAA").health.status == "ok"
    assert service.ping("IPLC-RTR-MAA", "10.10.4.1").health.status == "ok"


def test_fault_recording_gives_a_problem(service: NetworkService, tmp_path: Path) -> None:
    """The real fault-1 output (Fa2/0 shut on IPLC-RTR-MAA) must come out as a problem."""
    from replay import ReplayExecutor

    from ainops.network.capture import fixture_path

    path = fixture_path(tmp_path, "IPLC-RTR-MAA", "show ip interface")
    path.parent.mkdir(parents=True)
    path.write_text(FAULT1_SHOW_IP_INTERFACE, encoding="utf-8")
    service.executor = ReplayExecutor(tmp_path, delay_s=0)
    result = service.get_interfaces("IPLC-RTR-MAA")
    assert result.health.status == "problem"
    assert result.health.issues[0].interface == "Fa2/0"


def replay_ping(service: NetworkService, tmp_path: Path, marks: str, received: int) -> None:
    from replay import ReplayExecutor

    from ainops.network.capture import fixture_path

    path = fixture_path(tmp_path, "IPLC-RTR-TRV", "ping 10.10.4.2")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Type escape sequence to abort.\n"
        "Sending 5, 100-byte ICMP Echos to 10.10.4.2, timeout is 2 seconds:\n"
        f"{marks}\n"
        f"Success rate is {received * 20} percent ({received}/5), "
        "round-trip min/avg/max = 12/16/28 ms",
        encoding="utf-8",
    )
    service.executor = ReplayExecutor(tmp_path, delay_s=0)


def test_first_lost_ping_is_ok_and_says_why(service: NetworkService, tmp_path: Path) -> None:
    replay_ping(service, tmp_path, ".!!!!", 4)
    result = service.ping("IPLC-RTR-TRV", "10.10.4.2")
    assert result.health.status == "ok"
    assert result.summary.endswith(
        "; first lost: normal (the router was looking up the address, ARP)"
    )


def test_other_lost_ping_says_nothing_about_arp(service: NetworkService, tmp_path: Path) -> None:
    replay_ping(service, tmp_path, "!!!!.", 4)
    result = service.ping("IPLC-RTR-TRV", "10.10.4.2")
    assert result.health.status == "problem"
    assert "ARP" not in result.summary


FAULT1_SHOW_IP_INTERFACE = """\
FastEthernet0/0 is up, line protocol is up
  Internet address is 10.10.5.1/24
  Broadcast address is 255.255.255.255
FastEthernet1/0 is administratively down, line protocol is down
  Internet protocol processing disabled
FastEthernet2/0 is administratively down, line protocol is down
  Internet address is 10.10.4.2/24
  Broadcast address is 255.255.255.255
"""
