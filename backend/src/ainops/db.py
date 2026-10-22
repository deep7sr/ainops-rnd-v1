"""Postgres: the system of record (docs/architecture-production.md).

One connection pool per process, opened on first use (like the Neo4j GraphStore) and closed at
shutdown. Queries are plain SQL through psycopg; the tables are made by the migrations in
`migrations/` (Alembic, raw SQL), never by the code that uses them:

    uv run python -m ainops db upgrade     # bring the database to the newest schema
    uv run python -m ainops db status      # which schema it has now

A URL may be written the SQLAlchemy way (postgresql+psycopg://...): both forms are accepted.
"""

from pathlib import Path
from typing import Any

from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def libpq_url(url: str) -> str:
    """The URL as psycopg reads it (postgresql://...)."""
    for prefix in ("postgresql+psycopg://", "postgres+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def database_name(url: str) -> str:
    """The database a URL names (safe to show: no user or password)."""
    return str(conninfo_to_dict(libpq_url(url)).get("dbname") or "")


def sqlalchemy_url(url: str) -> str:
    """The URL as Alembic reads it (postgresql+psycopg://...: SQLAlchemy over psycopg 3)."""
    plain = libpq_url(url)
    for prefix in ("postgresql://", "postgres://"):
        if plain.startswith(prefix):
            return "postgresql+psycopg://" + plain[len(prefix) :]
    return plain


class Database:
    def __init__(self, url: str, max_size: int = 5) -> None:
        # connect_timeout: a closed port answers at once on Linux but waits on Windows.
        self.pool: ConnectionPool[Any] = ConnectionPool(
            libpq_url(url),
            min_size=1,
            max_size=max_size,
            timeout=5,
            kwargs={"connect_timeout": 3, "row_factory": dict_row, "autocommit": True},
            open=True,
        )

    def close(self) -> None:
        self.pool.close()

    def rows(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run one statement (its own transaction) and return its rows, if it has any."""
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchall()) if cursor.description else []

    def schema_version(self) -> str | None:
        """The migration the database is at (None: never migrated)."""
        found = self.rows("SELECT to_regclass('alembic_version') IS NOT NULL AS migrated")
        if not found[0]["migrated"]:
            return None
        rows = self.rows("SELECT version_num FROM alembic_version")
        return str(rows[0]["version_num"]) if rows else None


def setup(admin_password: str, urls: list[str]) -> list[str]:
    """Make the login roles and databases the URLs name, where missing. Returns what it did.

    Connects as the server's admin (user postgres), with the password chosen when the database
    files were made (scripts/start-postgres.ps1). A role that exists gets the URL's password, so
    changing a password in .env and running this again is how a password is changed.
    """
    import psycopg
    from psycopg import sql

    first = conninfo_to_dict(libpq_url(urls[0]))
    done: list[str] = []
    with psycopg.connect(
        host=first.get("host") or "localhost",
        port=first.get("port") or 5432,
        user="postgres",
        password=admin_password,
        dbname="postgres",
        connect_timeout=3,
        autocommit=True,  # CREATE DATABASE cannot run inside a transaction
    ) as admin:
        for url in urls:
            parts = conninfo_to_dict(libpq_url(url))
            user, password, name = parts.get("user"), parts.get("password"), parts.get("dbname")
            if not (user and password and name):
                raise ValueError("each database URL needs a user, a password and a database name")
            role = sql.Identifier(str(user))
            exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [user]).fetchone()
            if not exists:
                admin.execute(sql.SQL("CREATE ROLE {} LOGIN").format(role))
            admin.execute(
                sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(role, sql.Literal(str(password)))
            )
            if not exists:
                done.append(f"role {user} created")
            found = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name]).fetchone()
            if found:
                done.append(f"database {name} already there")
            else:
                admin.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(str(name)), role)
                )
                done.append(f"database {name} created")
    return done


def alembic_config(url: str) -> Any:
    """Alembic's settings, made in code (no alembic.ini): our migrations, this database."""
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    # ConfigParser reads "%" as the start of a variable: a password may contain one.
    config.set_main_option("sqlalchemy.url", sqlalchemy_url(url).replace("%", "%%"))
    return config


def upgrade(url: str) -> None:
    from alembic import command

    command.upgrade(alembic_config(url), "head")


def newest_version() -> str:
    """The newest migration in the code (what `upgrade` brings a database to)."""
    from alembic.script import ScriptDirectory

    head = ScriptDirectory(str(MIGRATIONS)).get_current_head()
    if head is None:
        raise LookupError(f"no migrations in {MIGRATIONS}")
    return head
