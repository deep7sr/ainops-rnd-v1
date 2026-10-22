"""Shared fixtures: the network tools against the recorded lab outputs (no device contacted)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from replay import ReplayExecutor

from ainops.config import REPO_ROOT, get_settings
from ainops.db import database_name, libpq_url, upgrade
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


@pytest.fixture(autouse=True)
def only_test_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never reach the real Postgres either: only a database whose name ends in "_test".

    Every way in goes through psycopg's connect (the pool, Alembic through SQLAlchemy, a plain
    psycopg.connect), so that is where the name is checked. The opt-in tests that use a real
    database (`pytest -m postgres`) get TEST_DATABASE_URL through the `postgres_url` fixture.
    """
    real = psycopg.Connection.connect

    def guarded(conninfo: str = "", **kwargs: Any) -> Any:
        name = str(conninfo_to_dict(conninfo, **kwargs).get("dbname") or "")
        if not name.endswith("_test"):
            raise ConnectionError(f"tests never use the database '{name}': only a *_test one")
        return real(conninfo, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "connect", staticmethod(guarded))
    monkeypatch.setattr(psycopg, "connect", guarded)


@pytest.fixture
def postgres_url() -> Iterator[str]:
    """TEST_DATABASE_URL, emptied and brought to the newest schema (only for `-m postgres`)."""
    url = get_settings().test_database_url.get_secret_value()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set in the repo-root .env")
    if not database_name(url).endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must name a database ending in _test")
    with psycopg.connect(libpq_url(url), autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    upgrade(url)
    yield url


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
