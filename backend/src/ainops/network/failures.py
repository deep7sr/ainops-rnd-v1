"""What kind of failure a network tool reported, from its message (an MCP tool error is only text).

The messages below are the ones the network tools raise; `failure_kind` reads them back. The UI
marks a device "did not answer" only for UNREACHABLE: a request the tool turned down (a bad
address, an unknown device) says nothing about the device.
"""

from typing import Literal

FailureKind = Literal["unreachable", "rejected", "blocked", "request"]

UNREACHABLE = "did not answer on the console"
REJECTED = "rejected the command"
BLOCKED = "safety check refused the command"


def failure_kind(message: str) -> FailureKind:
    """unreachable: the device did not answer. rejected: it answered with an error. blocked: the
    command guard stopped it before the device. request: the tool could not do what was asked."""
    if UNREACHABLE in message:
        return "unreachable"
    if REJECTED in message:
        return "rejected"
    if BLOCKED in message:
        return "blocked"
    return "request"
