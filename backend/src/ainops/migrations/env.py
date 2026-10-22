"""Alembic's entry point: run the migrations against the database in the settings (db.py).

Migrations are raw SQL (op.execute). There are no SQLAlchemy models, so there is nothing to
autogenerate: a new migration is written by hand, next to the others in versions/.
"""

from alembic import context
from sqlalchemy import create_engine, pool

url = context.config.get_main_option("sqlalchemy.url")
if not url:
    raise RuntimeError("no database URL: run migrations through `ainops db upgrade`")

engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
