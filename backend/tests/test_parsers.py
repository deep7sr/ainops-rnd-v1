"""Parsers: Cisco from the recorded lab outputs; Junos from small hand-written JSON samples in the
documented `| display json` shape (to be checked again against live vSRX output)."""

import json
from typing import Any

from ainops.network import parsers


def _j(value: str) -> list[dict[str, str]]:
    return [{"data": value}]


def test_junos_interfaces_keep_useful_ones_with_addresses() -> None:
    document: dict[str, Any] = {
        "interface-information": [
            {
                "physical-interface": [
                    {
                        "name": _j("ge-0/0/0"),
                        "admin-status": _j("up"),
                        "oper-status": _j("down"),
                        "logical-interface": [
                            {
                                "name": _j("ge-0/0/0.0"),
                                "address-family": [
                                    {
                                        "address-family-name": _j("inet"),
                                        "interface-address": [{"ifa-local": _j("10.10.7.2/24")}],
                                    }
                                ],
                            }
                        ],
                    },
                    {"name": _j("gr-0/0/0"), "admin-status": _j("up"), "oper-status": _j("up")},
                    {"name": _j("ge-0/0/1"), "admin-status": _j("down"), "oper-status": _j("down")},
                ]
            }
        ]
    }
    text = json.dumps(document) + "\n\nroot@FWL-MAA> "  # the CLI prompt after the JSON
    rows = parsers.interfaces("juniper_junos", text)
    assert [r["name"] for r in rows] == ["ge-0/0/0", "ge-0/0/1"]
    assert rows[0]["status"] == "down" and rows[0]["ipv4"] == ["10.10.7.2/24"]
    assert rows[1]["status"] == "admin-down"


def test_junos_ping() -> None:
    text = (
        "PING 10.10.6.2 (10.10.6.2): 56 data bytes\n!!!!!\n--- 10.10.6.2 ping statistics ---\n"
        "5 packets transmitted, 4 packets received, 20% packet loss\n"
        "round-trip min/avg/max/stddev = 1.1/2.5/4.0/0.9 ms\n"
    )
    assert parsers.ping("juniper_junos", text) == {
        "sent": 5,
        "received": 4,
        "success_percent": 80,
        "avg_rtt_ms": 2.5,
        "replies": None,  # five "!" but four replies: marks that disagree are not trusted
    }
    assert parsers.ping("juniper_junos", text.replace("!!!!!", ".!!!!"))["replies"] == ".!!!!"


def cisco_ping(marks: str, received: int) -> str:
    return (
        "Type escape sequence to abort.\n"
        "Sending 5, 100-byte ICMP Echos to 10.10.4.1, timeout is 2 seconds:\n"
        f"{marks}\n"
        f"Success rate is {received * 20} percent ({received}/5), "
        "round-trip min/avg/max = 12/16/28 ms"
    )


def test_cisco_ping_keeps_the_reply_marks_in_order() -> None:
    result = parsers.ping("cisco_ios", cisco_ping(".!!!!", 4))
    assert result["replies"] == ".!!!!"
    assert (result["sent"], result["received"]) == (5, 4)
    assert parsers.ping("cisco_ios", cisco_ping("!!U!!", 4))["replies"] == "!!U!!"


def test_cisco_ping_marks_are_not_trusted_when_missing_or_wrong() -> None:
    assert parsers.ping("cisco_ios", cisco_ping("", 4))["replies"] is None
    assert parsers.ping("cisco_ios", cisco_ping(".!!!", 3))["replies"] is None  # 4 marks, 5 sent
    assert parsers.ping("cisco_ios", cisco_ping("!!!!!", 4))["replies"] is None  # 5 "!", 4 replies


def test_junos_policies() -> None:
    document = {
        "security-policies": [
            {
                "security-context": [
                    {
                        "context-information": [
                            {
                                "source-zone-name": _j("trust"),
                                "destination-zone-name": _j("untrust"),
                            }
                        ],
                        "policies": [
                            {
                                "policy-information": [
                                    {
                                        "policy-name": _j("block-lan"),
                                        "policy-action": [{"action-type": _j("deny")}],
                                        "source-addresses": [
                                            {"source-address": [{"address-name": _j("any")}]}
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        ]
    }
    rows = parsers.firewall_policies(json.dumps(document))
    assert rows[0]["from_zone"] == "trust" and rows[0]["action"] == "deny"
    assert rows[0]["sources"] == ["any"]


def test_matching_routes_prefers_the_most_specific() -> None:
    rows = [
        {"prefix": "0.0.0.0/0", "protocol": "static"},
        {"prefix": "10.10.0.0/16", "protocol": "ospf"},
        {"prefix": "10.10.4.0/24", "protocol": "connected"},
        {"prefix": "192.168.1.0/24", "protocol": "ospf"},
    ]
    matches = parsers.matching_routes(rows, "10.10.4.7")
    assert [m["prefix"] for m in matches] == ["10.10.4.0/24", "10.10.0.0/16", "0.0.0.0/0"]


def test_empty_listing_means_none_found() -> None:
    assert parsers.ospf_neighbors("cisco_ios", "") == []


def test_interface_names() -> None:
    assert parsers.cisco_interface("Fas 2/0") == "FastEthernet2/0"
    assert parsers.short_interface("FastEthernet2/0") == "Fa2/0"
    assert parsers.short_interface("GigabitEthernet0/1") == "Gi0/1"


def test_cisco_logs_keep_only_messages() -> None:
    text = (
        "Syslog logging: enabled\n  Buffer logging: level debugging\n\nLog Buffer (8192 bytes):\n"
        "*Sep 30 10:00:01.123: %LINK-3-UPDOWN: Interface FastEthernet2/0, changed state to down\n"
        "*Sep 30 10:00:02.456: %OSPF-5-ADJCHG: Process 1, Nbr 10.10.4.1 on FastEthernet2/0 "
        "from FULL to DOWN, Neighbor Down: Interface down or detached\n"
    )
    lines = parsers.logs("cisco_ios", text, limit=10)
    assert len(lines) == 2 and "%OSPF-5-ADJCHG" in lines[1]


def test_junos_internal_loopback_units_are_skipped() -> None:
    document = {
        "interface-information": [
            {
                "physical-interface": [
                    {
                        "name": _j("lo0"),
                        "admin-status": _j("up"),
                        "oper-status": _j("up"),
                        "logical-interface": [
                            {
                                "name": _j(unit),
                                "address-family": [
                                    {
                                        "address-family-name": _j("inet"),
                                        "interface-address": [{"ifa-local": _j(address)}],
                                    }
                                ],
                            }
                            for unit, address in [
                                ("lo0.0", "10.255.0.1/32"),
                                ("lo0.16384", "127.0.0.1"),
                                ("lo0.16385", "128.0.0.1"),
                            ]
                        ],
                    }
                ]
            }
        ]
    }
    rows = parsers.interfaces("juniper_junos", json.dumps(document))
    assert rows[0]["ipv4"] == ["10.255.0.1/32"]
