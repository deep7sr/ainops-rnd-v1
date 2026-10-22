"""Cases: what an investigation found, reviewed by an engineer (cases.py, case_store.py).

`data` holds the whole case as JSON (cases.Case); the other columns are copies for queries:
status for the lists and counts, devices for "cases on these devices" (GIN index, `&&`).
One case per conversation: run_id is unique.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cases (
            id          text PRIMARY KEY,
            run_id      text NOT NULL UNIQUE,
            status      text NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
            made_by     text NOT NULL,
            root_cause  text,
            devices     text[] NOT NULL DEFAULT '{}',
            interfaces  text[] NOT NULL DEFAULT '{}',
            created_at  timestamptz NOT NULL,
            updated_at  timestamptz NOT NULL,
            data        jsonb NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX cases_by_status ON cases (status, updated_at DESC)")
    op.execute("CREATE INDEX cases_by_device ON cases USING gin (devices)")


def downgrade() -> None:
    op.execute("DROP TABLE cases")
