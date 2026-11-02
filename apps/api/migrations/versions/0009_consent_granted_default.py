"""Restore the granted_at server default dropped by the 0007 column upgrade.

Revision ID: 0009_consent_granted_default
Revises: 0008_patient_data_rights
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_consent_granted_default"
down_revision: str | None = "0008_patient_data_rights"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _granted_at_has_default() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns("consents")
    column = next(item for item in columns if item["name"] == "granted_at")
    return column.get("default") is not None


def upgrade() -> None:
    if not _granted_at_has_default():
        op.execute("ALTER TABLE consents ALTER COLUMN granted_at SET DEFAULT now()")


def downgrade() -> None:
    if _granted_at_has_default():
        op.execute("ALTER TABLE consents ALTER COLUMN granted_at DROP DEFAULT")
