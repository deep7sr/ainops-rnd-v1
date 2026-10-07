"""trace_route: following the routing tables hop by hop (recorded lab tables, no device contacted).

fixtures/routes/healthy and fixtures/routes/fault1 hold `show ip route` outputs of the lab (see the
README there). The graph lookup is the real matching code (owners_of_ip) over the lab's addresses.
"""

import asyncio
import json
import os
from collections.abc import Mapping
from functools import partial
from typing import Any

import pytest
from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import ToolCall, ToolMessage
from replay import ReplayExecutor

from ainops.agent.runner import AinopsMiddleware, Investigation
from ainops.config import REPO_ROOT
from ainops.inventory import load_inventory
from ainops.network import trace
from ainops.network.audit import AuditLog
from ainops.network.service import NetworkService, ToolFailure, load_commands
from ainops.topology.graph import owners_of_ip

# The lab's interface addresses, as discovery stores them in the graph.
LAB = {
    "CORE-SW-TRV": {"Fa0/0": "10.10.2.2/24", "E1/0": "192.168.100.1/24", "Fa2/0": "10.10.3.1/24"},
    "IPLC-RTR-TRV": {"Fa0/0": "10.10.3.2/24", "Fa2/0": "10.10.4.1/24"},
    "IPLC-RTR-MAA": {"Fa0/0": "10.10.5.1/24", "Fa2/0": "10.10.4.2/24"},
    "CORE-SW-MAA": {"Fa0/0": "10.10.6.2/24", "E1/0": "192.168.200.1/24", "Fa2/0": "10.10.5.2/24"},
    "FWL-TRV": {"ge-0/0/0": "10.10.1.2/24", "ge-0/0/1": "10.10.2.1/24"},
    "FWL-MAA": {"ge-0/0/0": "10.10.7.2/24", "ge-0/0/1": "10.10.6.1/24"},
}
LAB_INTERFACES = [
    {"device": device, "site": device[-3:], "interface": name, "ipv4": [cidr], "status": "up"}
    for device, interfaces in LAB.items()
    for name, cidr in interfaces.items()
]
lab_locate = partial(owners_of_ip, LAB_INTERFACES)


def _service(scenario: str, audit: AuditLog, locate: Any = lab_locate) -> NetworkService:
    return NetworkService(
        inventory=load_inventory(REPO_ROOT / "lab" / "inventory.yaml"),
        executor=ReplayExecutor(REPO_ROOT / "fixtures" / "routes" / scenario, delay_s=0),
        audit=audit,
        commands=load_commands(),
        locate=locate,
    )


@pytest.fixture
def healthy(audit: AuditLog) -> NetworkService:
    return _service("healthy", audit)


@pytest.fixture
def fault1(audit: AuditLog) -> NetworkService:
    return _service("fault1", audit)


# ---------- the lab, recorded ----------


def test_healthy_lab_follows_ospf_over_the_leased_line(healthy: NetworkService) -> None:
    result = healthy.trace_route("192.168.100.10", "192.168.200.10")
    data = result.data
    assert data["status"] == "reached"
    assert data["path"] == ["CORE-SW-TRV", "IPLC-RTR-TRV", "IPLC-RTR-MAA", "CORE-SW-MAA"]
    assert data["start_note"] == (
        "192.168.100.10 is on CORE-SW-TRV's network 192.168.100.0/24 (E1/0)"
    )
    first = data["hops"][0]
    assert first["route"] == {
        "prefix": "192.168.200.0/24",
        "protocol": "ospf",
        "next_hop": "10.10.3.2",
        "interface": "Fa2/0",
        "distance_metric": "110/13",
    }
    assert first["next_hop_device"] == "IPLC-RTR-TRV"
    assert [h["route"]["protocol"] for h in data["hops"]] == ["ospf", "ospf", "ospf", "connected"]
    assert all(h["note"] is None for h in data["hops"])  # every next hop confirmed by its owner
    assert result.health.status == "ok"
    assert result.device == "CORE-SW-TRV"
    assert result.evidence.source == "replay"
    assert result.evidence.command == "show ip route"


def test_fault1_the_route_to_maa_is_missing_on_the_trv_side(fault1: NetworkService) -> None:
    result = fault1.trace_route("192.168.100.0/24", "192.168.200.10")
    assert result.data["status"] == "no_route"
    assert result.data["path"] == ["CORE-SW-TRV"]
    assert result.data["stopped_at"] == "CORE-SW-TRV"
    assert result.health.status == "problem"
    assert result.health.issues[0].text == "CORE-SW-TRV has no route to 192.168.200.10"
    assert "no default route" in result.summary


def test_fault1_from_the_wan_router(fault1: NetworkService) -> None:
    result = fault1.trace_route("IPLC-RTR-TRV", "192.168.200.10")
    assert result.data["status"] == "no_route"
    assert result.data["path"] == ["IPLC-RTR-TRV"]


def test_the_way_back_is_traced_from_the_other_side(healthy: NetworkService) -> None:
    result = healthy.trace_route("CORE-SW-MAA", "192.168.100.10")
    assert result.data["status"] == "reached"
    assert result.data["path"] == ["CORE-SW-MAA", "IPLC-RTR-MAA", "IPLC-RTR-TRV", "CORE-SW-TRV"]


def test_a_juniper_firewall_hop_is_read_from_its_json_table(healthy: NetworkService) -> None:
    result = healthy.trace_route("FWL-MAA", "10.10.6.20")
    hop = result.data["hops"][0]
    assert result.data["status"] == "reached"
    assert hop["route"]["protocol"] == "direct"
    assert hop["route"]["interface"] == "ge-0/0/1.0"


def test_every_routing_table_read_and_the_trace_are_audited(
    healthy: NetworkService, audit: AuditLog
) -> None:
    healthy.trace_route("CORE-SW-TRV", "192.168.200.10")
    records = audit.tail()
    assert [r["tool"] for r in records] == ["get_routes"] * 4 + ["trace_route"]
    assert records[-1]["outcome"] == "ok"


# ---------- inputs ----------


def test_destination_must_be_a_private_address(healthy: NetworkService, audit: AuditLog) -> None:
    with pytest.raises(ToolFailure, match="outside the private network ranges"):
        healthy.trace_route("CORE-SW-TRV", "8.8.8.8")
    assert audit.tail()[-1]["outcome"] == "failed"


def test_a_source_address_must_be_private(healthy: NetworkService) -> None:
    with pytest.raises(ToolFailure, match="source 8.8.8.8 is outside the private network"):
        healthy.trace_route("8.8.8.8", "192.168.200.10")


def test_a_source_in_a_shared_network_is_ambiguous(healthy: NetworkService) -> None:
    with pytest.raises(ToolFailure, match="shared by CORE-SW-TRV, IPLC-RTR-TRV"):
        healthy.trace_route("10.10.3.77", "192.168.200.10")


def test_a_source_nobody_routes_is_refused(healthy: NetworkService) -> None:
    with pytest.raises(ToolFailure, match="no device in the knowledge graph"):
        healthy.trace_route("172.16.9.9", "192.168.200.10")


def test_an_unknown_source_device_is_refused(healthy: NetworkService) -> None:
    with pytest.raises(ToolFailure, match="not in the inventory"):
        healthy.trace_route("CORE-SW-XYZ", "192.168.200.10")


def test_without_the_graph_it_says_so(audit: AuditLog) -> None:
    with pytest.raises(ToolFailure, match="needs the knowledge graph"):
        _service("healthy", audit, locate=None).trace_route("CORE-SW-TRV", "192.168.200.10")


def test_a_graph_failure_becomes_a_tool_failure(audit: AuditLog) -> None:
    def down(address: str) -> list[dict[str, Any]]:
        raise ConnectionError("neo4j is not running")

    service = _service("healthy", audit, locate=down)
    with pytest.raises(ToolFailure, match="knowledge graph could not be read"):
        service.trace_route("CORE-SW-TRV", "192.168.200.10")
    assert audit.tail()[-1]["outcome"] == "failed"


# ---------- the walk, on made-up tables ----------


def _route(prefix: str, protocol: str, next_hop: str = "", interface: str = "") -> dict[str, Any]:
    return {
        "prefix": prefix,
        "protocol": protocol,
        "next_hop": next_hop,
        "interface": interface,
        "distance_metric": "",
    }


def _reader(tables: Mapping[str, list[dict[str, Any]] | None]) -> trace.ReadTable:
    def read(device: str) -> trace.TableRead:
        return trace.TableRead(device, "X", tables[device], "show ip route", "replay", 0)

    return read


def _owners(owned: dict[str, str]) -> trace.Locate:
    return lambda ip: [{"device": owned[ip], "match": "owns this address"}] if ip in owned else []


def test_the_most_specific_route_wins_over_the_default_route() -> None:
    tables = {
        "A": [  # not in prefix order: a router lists its table its own way
            _route("10.9.0.0/16", "ospf", "10.0.0.2"),
            _route("10.9.9.0/24", "ospf", "10.0.0.3"),
            _route("0.0.0.0/0", "static", "10.0.0.9"),
        ],
        "C": [_route("10.0.0.3/32", "local"), _route("10.9.9.0/24", "connected", interface="E0")],
    }
    result = trace.walk("A", "10.9.9.9", _reader(tables), _owners({"10.0.0.3": "C"}))
    assert result.status == "reached"
    assert [h["device"] for h in result.hops] == ["A", "C"]
    assert result.hops[0]["route"]["prefix"] == "10.9.9.0/24"
    assert result.hops[0]["equal_paths"] == 1  # the /16 and the default are not alternatives


def test_a_routing_loop_is_detected() -> None:
    tables = {
        "A": [_route("10.0.0.1/32", "local"), _route("10.9.0.0/16", "static", "10.0.0.2")],
        "B": [_route("10.0.0.2/32", "local"), _route("10.9.0.0/16", "static", "10.0.0.1")],
    }
    owned = {"10.0.0.1": "A", "10.0.0.2": "B"}
    result = trace.walk("A", "10.9.1.1", _reader(tables), _owners(owned))
    assert result.status == "loop"
    assert [h["device"] for h in result.hops] == ["A", "B"]
    assert result.hops[-1]["next_hop_device"] == "A"


def test_the_walk_stops_after_max_hops() -> None:
    count = trace.MAX_HOPS + 5
    tables = {
        f"D{i}": [
            _route(f"10.0.{i}.1/32", "local"),
            _route("10.9.0.0/16", "ospf", f"10.0.{i + 1}.1"),
        ]
        for i in range(count)
    }
    owned = {f"10.0.{i}.1": f"D{i}" for i in range(count)}
    result = trace.walk("D0", "10.9.1.1", _reader(tables), _owners(owned))
    assert result.status == "too_many_hops"
    assert len(result.hops) == trace.MAX_HOPS


def test_traffic_leaving_the_known_devices_is_reported() -> None:
    tables = {"ISP": [_route("0.0.0.0/0", "static", "172.20.10.1")]}
    result = trace.walk("ISP", "10.50.0.1", _reader(tables), _owners({}))
    assert result.status == "left_network"
    assert "towards 172.20.10.1" in result.summary


def test_a_device_that_does_not_answer_stops_the_walk() -> None:
    tables: dict[str, list[dict[str, Any]] | None] = {
        "A": [_route("10.9.0.0/16", "ospf", "10.0.0.2")],
        "B": None,
    }
    result = trace.walk("A", "10.9.1.1", _reader(tables), _owners({"10.0.0.2": "B"}))
    assert result.status == "device_failed"
    assert result.stopped_at == "B"


def test_a_next_hop_the_device_does_not_own_is_flagged() -> None:
    """The graph is a snapshot: if it is stale, the device's own table disagrees."""
    tables = {
        "A": [_route("10.9.0.0/16", "ospf", "10.0.0.2")],
        "B": [_route("10.9.0.0/16", "connected", interface="E0")],  # no local 10.0.0.2/32
    }
    result = trace.walk("A", "10.9.1.1", _reader(tables), _owners({"10.0.0.2": "B"}))
    assert result.status == "reached"
    assert "no local route for 10.0.0.2" in result.hops[1]["note"]


def test_equal_cost_paths_are_counted() -> None:
    tables = {
        "A": [
            _route("10.9.0.0/16", "ospf", "10.0.0.2"),
            _route("10.9.0.0/16", "ospf", "10.0.0.3"),
        ],
        "B": [_route("10.0.0.2/32", "local"), _route("10.9.0.0/16", "connected", interface="E0")],
    }
    result = trace.walk("A", "10.9.1.1", _reader(tables), _owners({"10.0.0.2": "B"}))
    assert result.hops[0]["equal_paths"] == 2
    assert result.hops[0]["next_hop_device"] == "B"


# ---------- through the agent ----------


def test_a_trace_reaches_the_ui_with_its_hops_and_verdict(fault1: NetworkService) -> None:
    events: list[dict[str, Any]] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    payload = fault1.trace_route("192.168.100.0/24", "192.168.200.10").model_dump(mode="json")
    run = Investigation(
        question="Users at TRV (192.168.100.0/24) cannot reach 192.168.200.10. Why?",
        emit=collect,
        tool_servers={"trace_route": "network"},
    )
    call = ToolCall(
        name="trace_route",
        args={"source": "192.168.100.0/24", "destination": "192.168.200.10", "reason": "Follow"},
        id="c1",
    )
    request = ToolCallRequest(tool_call=call, tool=None, state={}, runtime=None)  # type: ignore[arg-type]

    async def handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content=json.dumps(payload), tool_call_id="c1", name="trace_route")

    asyncio.run(AinopsMiddleware(run).awrap_tool_call(request, handler))
    result_event = events[-1]
    assert result_event["device"] == "CORE-SW-TRV"
    assert result_event["health"]["status"] == "problem"
    assert result_event["data"]["status"] == "no_route"
    assert result_event["data"]["hops"][0]["device"] == "CORE-SW-TRV"


# ---------- the samples the frontend tests read ----------

SAMPLES = REPO_ROOT / "fixtures" / "routes" / "samples"
CASES = {
    "healthy": ("healthy", "192.168.100.10", "192.168.200.10"),
    "fault1": ("fault1", "192.168.100.0/24", "192.168.200.10"),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_samples_the_frontend_tests_read_match_the_code(name: str, audit: AuditLog) -> None:
    """After changing trace_route's output: AINOPS_WRITE_SAMPLES=1 pytest -k samples"""
    scenario, source, destination = CASES[name]
    dumped = _service(scenario, audit).trace_route(source, destination).model_dump(mode="json")
    produced = {k: dumped[k] for k in ("device", "site", "summary", "data", "health")}
    path = SAMPLES / f"{name}.json"
    if os.environ.get("AINOPS_WRITE_SAMPLES"):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(produced, indent=2) + "\n")
    assert json.loads(path.read_text(encoding="utf-8")) == produced, "rewrite the samples"
