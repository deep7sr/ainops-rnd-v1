"""Shared fixtures: the network tools against the recorded lab outputs (no device contacted)."""

from pathlib import Path

import pytest
from replay import ReplayExecutor

from ainops.config import REPO_ROOT
from ainops.inventory import load_inventory
from ainops.network.audit import AuditLog
from ainops.network.service import NetworkService, load_commands


@pytest.fixture(autouse=True)
def no_real_neo4j(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never reach the engineer's real Neo4j: any connection attempt fails at once.

    (A test once wrote a made-up case into the real graph.) Tests that need a graph use fakes.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise ConnectionError("tests never use the real Neo4j: use a fake")

    monkeypatch.setattr("neo4j.GraphDatabase.driver", refuse)


@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl")


@pytest.fixture
def service(audit: AuditLog) -> NetworkService:
    return NetworkService(
        inventory=load_inventory(REPO_ROOT / "lab" / "inventory.yaml"),
        executor=ReplayExecutor(REPO_ROOT / "fixtures" / "lab", delay_s=0),
        audit=audit,
        commands=load_commands(),
    )
