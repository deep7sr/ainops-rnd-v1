"""Test data only: an executor that answers from recorded device outputs (fixtures/).

It lives in the tests on purpose: AINOPS itself can only work on the live devices, and the app
code cannot import this. The tests use it to check that the code reads real outputs correctly.
"""

from pathlib import Path

from ainops.inventory import Device
from ainops.network.capture import fixture_path
from ainops.network.executor import DeviceUnreachableError, RawOutput
from ainops.network.executor import _device_error as device_error
from ainops.network.guard import check_command
from ainops.network.redact import redact


class ReplayExecutor:
    mode = "replay"

    def __init__(self, fixtures: Path, delay_s: float = 0) -> None:
        self.fixtures = fixtures

    def run(self, device: Device, command: str) -> RawOutput:
        check_command(command, device.platform)  # the same guard as live
        path = fixture_path(self.fixtures, device.name, command)
        if not path.is_file():
            raise DeviceUnreachableError(f"no recorded output of '{command}' on {device.name}")
        text = redact(path.read_text(encoding="utf-8"))
        return RawOutput(command, text, "replay", 0, device_error(device, text))
