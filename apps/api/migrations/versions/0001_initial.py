"""Initial Postgres schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.repositories.models import Base

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT_FUNCTION = """
CREATE OR REPLACE FUNCTION sahyog_audit_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;
"""

AUDIT_TRIGGER = """
CREATE TRIGGER audit_events_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION sahyog_audit_append_only();
"""


def upgrade() -> None:
    bind = op.get_bind()
    for extension in ("vector", "pg_trgm", "pgcrypto", "btree_gin"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
    Base.metadata.create_all(bind=bind)
    op.execute(AUDIT_FUNCTION)
    op.execute(AUDIT_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS sahyog_audit_append_only()")
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
