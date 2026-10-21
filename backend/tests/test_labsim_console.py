"""End to end: the real Netmiko and AINOPS's own LiveExecutor and network tools against the
simulated consoles, over telnet on 127.0.0.1 (free ports, instant answers).

Logging in takes a few seconds per console, like on the lab (Netmiko waits for prompts), so the
consoles and AINOPS's sessions are shared by the tests in this file.
"""

import asyncio
import dataclasses
import os
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from netmiko import ConnectHandler

from ainops.config import REPO_ROOT
from ainops.inventory import Inventory, load_inventory
from ainops.network.audit import AuditLog
from ainops.network.executor import IDLE_REFRESH_S, LiveExecutor
from ainops.network.service import NetworkService, ToolFailure, load_commands
from labsim.console import Console, Session, TelnetText, start
from labsim.model import load_lab
from labsim.state import Simulator, write_faults

LOGIN = {"AINOPS_CRED_LAB_SRX_ADMIN_USERNAME": "root", "AINOPS_CRED_LAB_SRX_ADMIN_PASSWORD": "t3st"}


@dataclasses.dataclass
class Running:
    ports: dict[str, int]
    state_file: Path
    inventory: Inventory


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Running]:
    saved = {k: os.environ.get(k) for k in LOGIN}
    os.environ.update(LOGIN)  # the simulator and AINOPS read the same login, as on the lab
    state_file = tmp_path_factory.mktemp("labsim") / "state.json"
    simulator = Simulator(load_lab(), state_file=state_file)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    consoles = simulator.base.consoles()
    servers = asyncio.run_coroutine_threadsafe(
        start(simulator, speed=0, ports={d.name: 0 for d in consoles}, log=lambda _: None), loop
    ).result(timeout=10)
    ports = {d.name: s.sockets[0].getsockname()[1] for d, s in zip(consoles, servers, strict=True)}
    real = load_inventory(REPO_ROOT / "lab" / "inventory.yaml")
    inventory = Inventory(
        sites=real.sites,
        devices=[dataclasses.replace(d, port=ports[d.name]) for d in real.devices],
    )
    yield Running(ports, state_file, inventory)

    async def close() -> None:
        for server in servers:
            server.close()
            await server.wait_closed()

    asyncio.run_coroutine_threadsafe(close(), loop).result(timeout=10)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="module")
def executor() -> Iterator[LiveExecutor]:
    live = LiveExecutor("127.0.0.1")
    yield live
    live.close()


@pytest.fixture
def tools(lab: Running, executor: LiveExecutor, tmp_path: Path) -> NetworkService:
    write_faults([], lab.state_file)  # every test starts on the healthy lab
    return NetworkService(
        inventory=lab.inventory,
        executor=executor,
        audit=AuditLog(tmp_path / "audit.jsonl"),
        commands=load_commands(),
        expected_ospf=lambda device: [
            {"peer": "IPLC-RTR-MAA", "neighbor_id": "10.10.5.1", "address": "10.10.4.2",
             "interface": "Fa2/0"},
        ] if device == "IPLC-RTR-TRV" else [],
    )  # fmt: skip


# ---------- telnet ----------


def test_telnet_commands_from_the_client_are_dropped() -> None:
    text = TelnetText()
    assert text.feed(b"\xff\xfd\x01sh\xff\xf1ow\xff\xff") == "show\xff"  # DO ECHO, NOP, IAC IAC
    assert text.feed(b"\xff") == ""  # an IAC split across two reads
    assert text.feed(b"\xfb\x03ip\xff\xfa\x18\x00x\xff\xf0") == "ip"  # WILL SGA, SB ... SE


# ---------- Netmiko ----------


def test_netmiko_logs_in_to_a_cisco_console_and_reads_ospf(lab: Running) -> None:
    session = ConnectHandler(
        device_type="cisco_ios_telnet", host="127.0.0.1", port=lab.ports["CORE-SW-MAA"],
        username="", password="", fast_cli=False,
    )  # fmt: skip
    try:
        assert session.find_prompt() == "CORE-SW-MAA>"
        output = session.send_command("show ip ospf neighbor", read_timeout=30)
        assert "10.10.5.1         1   FULL/BDR" in output
    finally:
        session.disconnect()


def test_netmiko_logs_in_to_a_junos_console_through_the_root_shell(lab: Running) -> None:
    session = ConnectHandler(
        device_type="juniper_junos_telnet", host="127.0.0.1", port=lab.ports["FWL-TRV"],
        username="root", password="t3st", fast_cli=False,
    )  # fmt: skip
    try:
        assert session.find_prompt() == "root@FWL-TRV>"
        assert '"inet.0"' in session.send_command("show route | display json", read_timeout=30)
    finally:
        session.disconnect()


def test_a_wrong_junos_password_is_refused_like_on_the_lab() -> None:
    """At the console itself: with Netmiko a refused login takes ~40 s of its retries."""
    simulator = Simulator(load_lab(), state_file=Path("no-such-state.json"))
    console = Console(
        simulator, simulator.base.devices["FWL-MAA"], speed=0,
        credentials=lambda ref: ("root", "t3st") if ref == "lab-srx-admin" else None,
        log=lambda _: None,
    )  # fmt: skip
    session = Session(state="idle")

    async def typed(*lines: str) -> list[str]:
        return [await console.line(session, line) for line in lines]

    refused = asyncio.run(typed("", "root", "wrong"))
    assert refused[-1].endswith("Login incorrect\r\nlogin: ")
    accepted = asyncio.run(typed("root", "t3st", "cli"))
    assert accepted[1].endswith("root@FWL-MAA:~ # ") and accepted[2].endswith("root@FWL-MAA> ")


# ---------- AINOPS's tools ----------


def test_ainops_tools_read_the_healthy_lab(tools: NetworkService) -> None:
    ospf = tools.get_ospf_neighbors("IPLC-RTR-TRV")
    assert (ospf.health.status, ospf.evidence.source) == ("ok", "live")
    assert ospf.summary == "2 OSPF neighbour(s), all FULL"
    routes = tools.get_routes("CORE-SW-TRV", "192.168.200.10")
    assert routes.summary == "192.168.200.10 is reached via 192.168.200.0/24 (ospf) -> 10.10.3.2"


def test_ainops_sees_fault_1_switched_on_while_its_sessions_are_open(
    lab: Running, tools: NetworkService
) -> None:
    assert tools.get_ospf_neighbors("IPLC-RTR-TRV").health.status == "ok"
    write_faults(["fault-1"], lab.state_file)
    ospf = tools.get_ospf_neighbors("IPLC-RTR-TRV")
    assert ospf.health.status == "problem"
    assert "MISSING (FULL at discovery): IPLC-RTR-MAA on Fa2/0" in ospf.summary
    interfaces = tools.get_interfaces("IPLC-RTR-MAA")
    assert [i.text for i in interfaces.health.issues] == ["Fa2/0 is administratively down (shut)"]
    assert tools.ping("CORE-SW-TRV", "192.168.200.10").health.status == "problem"


def test_ainops_flags_the_vsrx_interfaces_that_are_in_no_zone(tools: NetworkService) -> None:
    zones = tools.get_firewall_zones("FWL-MAA")
    assert zones.health.status == "problem"
    assert "NOT IN ANY ZONE: ge-0/0/0 (10.10.7.2/24), ge-0/0/1 (10.10.6.1/24)" in zones.summary


def test_an_idle_ainops_session_is_woken_and_prepared_again(
    tools: NetworkService, executor: LiveExecutor
) -> None:
    tools.get_device_facts("IPLC-RTR-MAA")
    real_clock = executor._clock
    executor._clock = lambda: real_clock() + IDLE_REFRESH_S + 1
    try:
        facts = tools.get_device_facts("IPLC-RTR-MAA")
    finally:
        executor._clock = real_clock
    assert facts.data["hostname"] == "IPLC-RTR-MAA"


def test_the_read_only_guard_still_stops_a_change_before_the_simulator(
    lab: Running, executor: LiveExecutor
) -> None:
    device = lab.inventory.get("IPLC-RTR-MAA")
    with pytest.raises(Exception, match="allowed read-only prefix"):
        executor.run(device, "configure terminal")


def test_a_device_with_no_console_fails_like_an_unreachable_one(
    lab: Running, executor: LiveExecutor, tmp_path: Path
) -> None:
    gone = dataclasses.replace(lab.inventory.get("ISP-TRV-1"), port=1)  # nothing listens there
    service = NetworkService(
        inventory=Inventory(lab.inventory.sites, [gone]),
        executor=LiveExecutor("127.0.0.1"),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        commands=load_commands(),
    )
    with pytest.raises(ToolFailure, match="did not answer on the console"):
        service.get_interfaces("ISP-TRV-1")
