"""AINOPS diagnoses only from the live devices: no setting, module or side effect brings back
answers from saved outputs. Recorded outputs are test data, captured on purpose."""

from pathlib import Path
from typing import Any

import pytest
from test_live_executor import DEVICE, FakeSession

from ainops.config import REPO_ROOT, Settings
from ainops.network import server
from ainops.network.capture import CapturingExecutor, fixture_path, tools_for
from ainops.network.executor import LiveExecutor, RawOutput


def test_there_is_no_setting_to_answer_from_saved_outputs() -> None:
    settings = Settings()
    assert not hasattr(settings, "lab_executor")
    assert not hasattr(settings, "fixtures_dir")


def test_the_network_server_always_uses_the_live_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.settings, "lab_eve_host", "eve.test")

    class Graph:  # stands in for Neo4j (tests never use the real one)
        def __init__(self, *args: object) -> None:
            pass

        def owner_of_ip(self, address: str) -> list[dict[str, Any]]:
            return []

        def ospf_peers(self, device: str | None = None) -> list[dict[str, Any]]:
            return []

        def links(self, device: str | None = None) -> list[dict[str, Any]]:
            return [{"a": "X"}]

    monkeypatch.setattr(server, "GraphStore", Graph)
    service = server.build_service()
    assert isinstance(service.executor, LiveExecutor)
    # The graph lookups are wired in (get_firewall_zones names each port's cable from it).
    assert service.cabling is not None and service.cabling("FWL-MAA") == [{"a": "X"}]


def test_without_the_lab_address_the_server_does_not_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.settings, "lab_eve_host", "")
    with pytest.raises(SystemExit, match="only works live"):
        server.build_service()


def test_no_app_code_can_answer_from_saved_outputs() -> None:
    app = REPO_ROOT / "backend" / "src" / "ainops"
    offenders = [
        str(path.relative_to(app))
        for path in app.rglob("*.py")
        if "ReplayExecutor" in path.read_text(encoding="utf-8")
        or "fixtures/lab" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_working_live_writes_nothing_to_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_writes(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the live executor wrote a file")

    monkeypatch.setattr(Path, "write_text", no_writes)
    monkeypatch.setattr(Path, "mkdir", no_writes)
    executor = LiveExecutor("eve.test")
    executor._connect = lambda device: FakeSession()  # type: ignore[method-assign]
    assert executor.run(DEVICE, "show ip interface").source == "live"


# ---------- capture: test data made on purpose ----------


class Inner:
    def run(self, device: Any, command: str) -> RawOutput:
        return RawOutput(command, f"output of {command}", "live", 5, None)

    def close(self) -> None:
        pass


def test_a_capture_saves_each_output_where_the_tests_look(tmp_path: Path) -> None:
    folder = tmp_path / "fault1"
    capture = CapturingExecutor(Inner(), folder)  # type: ignore[arg-type]
    raw = capture.run(DEVICE, "show ip ospf neighbor")
    saved = fixture_path(folder, DEVICE.name, "show ip ospf neighbor")
    assert saved.read_text(encoding="utf-8") == "output of show ip ospf neighbor"
    assert raw.source == "live"


def test_a_capture_never_overwrites_existing_test_data(tmp_path: Path) -> None:
    (tmp_path / "healthy").mkdir()
    with pytest.raises(FileExistsError, match="already exists"):
        CapturingExecutor(Inner(), tmp_path / "healthy")  # type: ignore[arg-type]


def test_a_capture_reads_what_each_platform_supports() -> None:
    assert "get_firewall_zones" in tools_for("juniper_junos")
    assert "get_routing_protocols" in tools_for("cisco_ios")
    assert "get_routing_protocols" not in tools_for("juniper_junos")
