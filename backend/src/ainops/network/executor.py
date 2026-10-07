"""Running a guarded command on a device, live (Netmiko over the EVE-NG console).

AINOPS only ever answers from the real devices: there is no mode that answers from saved outputs,
and nothing is written to disk while it works. (Recorded outputs exist only as test data under
fixtures/, captured on purpose with `ainops capture`, see network/capture.py.)

One open session per device is kept and reused: logging in to a lab console takes 3-10 s, so
reusing the session makes the agent's many small checks fast. A lock per device makes sure only
one command runs on a console at a time (a console cannot be shared).

An idle console logs out (Cisco: exec-timeout, 10 min in the lab). The next command wakes it in a
new EXEC session that has lost our settings, so long output stops at "--More--" and the command
times out. A session idle for longer than IDLE_REFRESH_S is therefore prepared again (prompt, no
paging) before it is used. A broken session is closed without typing anything: "exit" sent into a
"--More--" pager arrives as "xit", which the router tries to resolve as a host name for ~20 s.
"""

import contextlib
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from ainops.config import device_credentials
from ainops.inventory import Device
from ainops.network.guard import check_command
from ainops.network.redact import redact

# Output that means the device rejected the command.
_DEVICE_ERRORS = {
    "cisco_ios": ("% Invalid input", "% Incomplete command", "% Ambiguous command"),
    "juniper_junos": ("syntax error", "unknown command", "error: "),
}


# Well under the lab's 10 min console exec-timeout: after this long idle, prepare the session again.
IDLE_REFRESH_S = 240


class DeviceUnreachableError(Exception):
    """The device could not be reached or the session broke."""


@dataclass(frozen=True)
class RawOutput:
    command: str
    text: str  # redacted
    source: str  # "live" (only tests replay recorded outputs)
    duration_ms: int
    device_error: str | None  # the device's error line, if it rejected the command


class Executor(Protocol):
    mode: str

    def run(self, device: Device, command: str) -> RawOutput: ...


def _device_error(device: Device, text: str) -> str | None:
    for marker in _DEVICE_ERRORS[device.platform]:
        for line in text.splitlines():
            if marker in line:
                return line.strip()[:200]
    return None


class LiveExecutor:
    mode = "live"

    def __init__(self, eve_host: str) -> None:
        if not eve_host:
            raise ValueError("LAB_EVE_HOST is not set: live mode needs the EVE-NG address")
        self.eve_host = eve_host
        self._sessions: dict[str, Any] = {}
        self._last_used: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._clock = time.monotonic  # replaced in tests

    def _lock(self, device: Device) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(device.name, threading.Lock())

    def _connect(self, device: Device) -> Any:
        from netmiko import ConnectHandler

        username, password = ("", "")
        if device.credential_ref:
            username, password = device_credentials(device.credential_ref)
        return ConnectHandler(
            device_type=f"{device.platform}_telnet",
            host=self.eve_host,
            port=device.port,
            username=username,
            password=password,
            conn_timeout=30,
            auth_timeout=30,
            banner_timeout=30,
            fast_cli=False,
        )

    def _session(self, device: Device) -> Any:
        session = self._sessions.get(device.name)
        if session is None:
            session = self._connect(device)
            self._sessions[device.name] = session
        elif self._clock() - self._last_used.get(device.name, 0.0) > IDLE_REFRESH_S:
            # The console may have logged out meanwhile: wake it with a bare RETURN first (a
            # logged-out Cisco console drops everything typed before RETURN), then re-apply
            # no-paging etc. find_prompt() consumes the prompt and Junos preparation starts by
            # waiting for one (20 s timeout), so one more RETURN leaves a fresh prompt waiting.
            session.clear_buffer()
            session.find_prompt()
            session.write_channel(session.RETURN)
            session.session_preparation()
        return session

    def _drop(self, device: Device) -> None:
        self._last_used.pop(device.name, None)
        session = self._sessions.pop(device.name, None)
        if session is not None:
            # Close the connection only. disconnect() would type "exit" into a console in an
            # unknown state (see the module docstring).
            with contextlib.suppress(Exception):  # the session is broken anyway
                session.remote_conn.close()

    def run(self, device: Device, command: str) -> RawOutput:
        check_command(command, device.platform)
        with self._lock(device):
            started = time.monotonic()
            output = None
            for attempt in (1, 2):  # a stale console session gets one fresh reconnect
                try:
                    session = self._session(device)
                    output = str(session.send_command(command, read_timeout=60))
                    self._last_used[device.name] = self._clock()
                    break
                except Exception as error:  # noqa: BLE001 - Netmiko raises many types
                    self._drop(device)
                    if attempt == 2:
                        raise DeviceUnreachableError(
                            f"{device.name} did not answer on the console ({type(error).__name__})"
                        ) from error
            duration_ms = int((time.monotonic() - started) * 1000)
        text = redact(output or "")
        return RawOutput(command, text, "live", duration_ms, _device_error(device, text))

    def close(self) -> None:
        for name in list(self._sessions):
            session = self._sessions.pop(name)
            with contextlib.suppress(Exception):
                session.disconnect()
