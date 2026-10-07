"""Shared fixtures: the network tools against the recorded lab outputs (no device contacted)."""

from pathlib import Path

import pytest
from replay import ReplayExecutor

from ainops.config import REPO_ROOT
from ainops.inventory import load_inventory
from ainops.network.audit import AuditLog
from ainops.network.service import NetworkService, load_commands


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
