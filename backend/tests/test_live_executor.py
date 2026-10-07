"""Live executor session handling, with fake console sessions (no device is contacted)."""

from pathlib import Path
from typing import Any

import pytest

from ainops.inventory import Device
from ainops.network.executor import IDLE_REFRESH_S, DeviceUnreachableError, LiveExecutor
from ainops.network.guard import CommandRefusedError

DEVICE = Device(
    name="CORE-SW-TRV",
    site="TRV",
    role="core",
    platform="cisco_ios",
    port=32769,
)


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """Records what the executor does to a console session. `fail` makes send_command time out."""

    RETURN = "\n"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []
        self.remote_conn = FakeConnection()
        self.prompt_waiting = True

    def send_command(self, command: str, read_timeout: float) -> str:
        self.calls.append(f"send:{command}")
        if self.fail:
            raise TimeoutError("Pattern not detected")  # what a "--More--" pager looks like
        return "FastEthernet0/0 is up, line protocol is up"

    def clear_buffer(self) -> None:
        self.calls.append("clear_buffer")

    def find_prompt(self) -> str:
        self.calls.append("find_prompt")
        self.prompt_waiting = False  # read and consumed
        return "CORE-SW-TRV>"

    def write_channel(self, text: str) -> None:
        self.calls.append(f"write:{text!r}")
        if text == self.RETURN:
            self.prompt_waiting = True

    def session_preparation(self) -> None:
        self.calls.append("session_preparation")
        if not self.prompt_waiting:  # like Junos: it waits for a prompt without sending anything
            raise TimeoutError("Pattern not detected: '[%>$#]'")

    def disconnect(self) -> None:
        self.calls.append("disconnect")  # types "exit": must never happen on a broken session


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def make_executor(
    tmp_path: Path, clock: Clock, sessions: list[FakeSession]
) -> tuple[LiveExecutor, list[FakeSession]]:
    """A LiveExecutor that connects to `sessions` in order; returns the ones handed out."""
    executor = LiveExecutor("eve.test")
    executor._clock = clock
    handed_out: list[FakeSession] = []

    def connect(device: Device) -> Any:
        session = sessions.pop(0)
        handed_out.append(session)
        return session

    executor._connect = connect  # type: ignore[method-assign]
    return executor, handed_out


def test_session_is_reused_without_refresh_when_recently_used(tmp_path: Path, clock: Clock) -> None:
    executor, handed_out = make_executor(tmp_path, clock, [FakeSession()])
    executor.run(DEVICE, "show ip interface")
    clock.now += IDLE_REFRESH_S - 1
    executor.run(DEVICE, "show ip interface")
    assert len(handed_out) == 1
    assert handed_out[0].calls == ["send:show ip interface", "send:show ip interface"]


def test_idle_session_is_woken_and_prepared_again_before_the_command(
    tmp_path: Path, clock: Clock
) -> None:
    executor, handed_out = make_executor(tmp_path, clock, [FakeSession()])
    executor.run(DEVICE, "show ip interface")
    clock.now += IDLE_REFRESH_S + 1  # the console may have logged out (exec-timeout)
    result = executor.run(DEVICE, "show ip interface")
    assert result.text.startswith("FastEthernet0/0 is up")
    assert len(handed_out) == 1  # same session, no reconnect needed
    # Wake with a bare RETURN, then no-paging etc., and only then the command.
    assert handed_out[0].calls[1:] == [
        "clear_buffer",
        "find_prompt",
        "write:'\\n'",
        "session_preparation",
        "send:show ip interface",
    ]


def test_idle_time_counts_from_the_last_command(tmp_path: Path, clock: Clock) -> None:
    executor, handed_out = make_executor(tmp_path, clock, [FakeSession()])
    for _ in range(3):  # regular use keeps the session fresh
        executor.run(DEVICE, "show ip interface")
        clock.now += IDLE_REFRESH_S - 1
    assert "session_preparation" not in handed_out[0].calls


def test_broken_session_is_closed_without_typing_and_retried_once(
    tmp_path: Path, clock: Clock
) -> None:
    executor, handed_out = make_executor(tmp_path, clock, [FakeSession(fail=True), FakeSession()])
    result = executor.run(DEVICE, "show ip interface")
    assert result.text.startswith("FastEthernet0/0 is up")
    broken, fresh = handed_out
    assert broken.remote_conn.closed
    assert "disconnect" not in broken.calls  # "exit" into a pager becomes "xit" + a DNS lookup
    assert fresh.calls == ["send:show ip interface"]


def test_failed_wake_up_falls_back_to_a_fresh_connection(tmp_path: Path, clock: Clock) -> None:
    stale = FakeSession()
    executor, handed_out = make_executor(tmp_path, clock, [stale, FakeSession()])
    executor.run(DEVICE, "show ip interface")

    def no_prompt() -> None:
        raise TimeoutError("Pattern not detected: 'terminal width 511'")

    stale.session_preparation = no_prompt  # type: ignore[method-assign]
    clock.now += IDLE_REFRESH_S + 1
    result = executor.run(DEVICE, "show ip interface")
    assert result.source == "live"
    assert len(handed_out) == 2
    assert stale.remote_conn.closed


def test_device_that_never_answers_fails_after_one_retry(tmp_path: Path, clock: Clock) -> None:
    executor, handed_out = make_executor(
        tmp_path, clock, [FakeSession(fail=True), FakeSession(fail=True), FakeSession()]
    )
    with pytest.raises(DeviceUnreachableError, match="CORE-SW-TRV did not answer"):
        executor.run(DEVICE, "show ip interface")
    assert len(handed_out) == 2  # one retry, no more
    assert all(s.remote_conn.closed and "disconnect" not in s.calls for s in handed_out)


def test_the_guard_still_runs_before_any_session_is_used(tmp_path: Path, clock: Clock) -> None:
    executor, handed_out = make_executor(tmp_path, clock, [FakeSession()])
    with pytest.raises(CommandRefusedError):
        executor.run(DEVICE, "configure terminal")
    assert handed_out == []
