"""Postgres: the URLs, which database each lab uses, the test guard, and the health report.

The tests marked `postgres` use the real test database (TEST_DATABASE_URL) and run only with
`pytest -m postgres`; the others need no database at all.
"""

from typing import Any

import psycopg
import pytest
from psycopg_pool import ConnectionPool, PoolTimeout
from pydantic import SecretStr

from ainops import db
from ainops.config import Settings

URL = "postgresql+psycopg://ainops:secret@localhost:5432/ainops"


def test_urls_are_read_both_ways() -> None:
    assert db.libpq_url(URL) == "postgresql://ainops:secret@localhost:5432/ainops"
    assert db.sqlalchemy_url("postgresql://u:p@h/x") == "postgresql+psycopg://u:p@h/x"
    assert db.sqlalchemy_url(URL) == URL
    assert db.database_name(URL) == "ainops"


def test_the_simulated_lab_never_uses_the_real_database() -> None:
    real = SecretStr("postgresql://u:p@localhost/ainops")
    sim = SecretStr("postgresql://u:p@localhost/ainops_sim")
    assert Settings(database_url=real, sim_database_url=sim).active_database_url.endswith("/ainops")
    on_sim = Settings(database_url=real, sim_database_url=sim, lab_simulated=True)
    assert on_sim.active_database_url.endswith("/ainops_sim")
    no_sim = Settings(database_url=real, sim_database_url=SecretStr(""), lab_simulated=True)
    with pytest.raises(LookupError, match="SIM_DATABASE_URL"):  # no fall-back to the real one
        _ = no_sim.active_database_url
    with pytest.raises(LookupError, match="DATABASE_URL"):
        _ = Settings(database_url=SecretStr("")).active_database_url


NOT_A_TEST_DB = "postgresql://u:p@127.0.0.1:1/ainops"


@pytest.mark.parametrize("way", ["psycopg.connect", "psycopg.Connection.connect"])
def test_tests_cannot_reach_a_database_that_is_not_a_test_one(way: str) -> None:
    # Looked up at run time: the guard is in place only while the test runs.
    connect = psycopg.connect if way == "psycopg.connect" else psycopg.Connection.connect
    with pytest.raises(ConnectionError, match="only a \\*_test one"):
        connect(NOT_A_TEST_DB)


def test_the_pool_cannot_reach_it_either(caplog: pytest.LogCaptureFixture) -> None:
    # The pool keeps retrying instead of raising: it ends in a timeout, the guard's refusal logged.
    pool: ConnectionPool[Any] = ConnectionPool(NOT_A_TEST_DB, min_size=1, open=False)
    with pytest.raises(PoolTimeout):
        pool.open(wait=True, timeout=1)
    assert "only a *_test one" in caplog.text


def test_the_guard_lets_a_test_database_through() -> None:
    # Port 1: nothing listens, so the real connect runs and fails. It is not the guard's error.
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect("postgresql://u:p@127.0.0.1:1/ainops_test", connect_timeout=1)


def test_the_newest_migration_is_known() -> None:
    assert db.newest_version() == "0001"


class FakeDatabase:
    def __init__(self, version: str | None) -> None:
        self.version = version

    def schema_version(self) -> str | None:
        return self.version


@pytest.mark.parametrize(
    ("version", "ok", "error"),
    [
        ("0001", True, None),
        (None, False, "schema none, code needs 0001: run `ainops db upgrade`"),
    ],
)
def test_health_says_whether_the_schema_is_current(
    monkeypatch: pytest.MonkeyPatch, version: str | None, ok: bool, error: str | None
) -> None:
    from ainops.api import app as module

    monkeypatch.setattr(module, "settings", Settings(database_url=SecretStr(URL)))
    monkeypatch.setattr(module, "database", lambda: FakeDatabase(version))
    status = module._database_status()
    assert (status["ok"], status["name"], status["schema"], status.get("problem")) == (
        ok,
        "ainops",
        version,
        error,
    )


@pytest.mark.postgres
def test_upgrade_makes_the_newest_schema(postgres_url: str) -> None:
    database = db.Database(postgres_url, max_size=1)
    try:
        assert database.schema_version() == db.newest_version()
        columns = database.rows(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'cases'"
        )
        assert {"id", "run_id", "status", "devices", "data"} <= {c["column_name"] for c in columns}
        db.upgrade(postgres_url)  # running it again changes nothing
        assert database.schema_version() == db.newest_version()
    finally:
        database.close()
