"""Add notify_email and slack_user_id to patients.

Revision ID: 0012_patient_contact_metadata
Revises: 0011_stock_items
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_patient_contact_metadata"
down_revision: str | None = "0011_stock_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("patients")}
    if "notify_email" not in columns:
        op.add_column("patients", sa.Column("notify_email", sa.String(320), nullable=True))
    if "slack_user_id" not in columns:
        op.add_column("patients", sa.Column("slack_user_id", sa.String(40), nullable=True))


def downgrade() -> None:
    columns = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("patients")}
    if "slack_user_id" in columns:
        op.drop_column("patients", "slack_user_id")
    if "notify_email" in columns:
        op.drop_column("patients", "notify_email")
