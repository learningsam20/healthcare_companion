"""Patient data rights: soft-delete marker and audited deletion requests.

Revision ID: 0008_patient_data_rights
Revises: 0007_consent_lifecycle
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_patient_data_rights"
down_revision: str | None = "0007_consent_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "deleted_at" not in _columns("patients"):
        op.add_column("patients", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    if "data_deletion_requests" not in _tables():
        op.create_table(
            "data_deletion_requests",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "patient_id",
                sa.Uuid(),
                sa.ForeignKey("patients.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("requested_by_subject", sa.String(200), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column(
                "requested_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "evidence",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.CheckConstraint(
                "status IN ('pending','processing','completed','failed','cancelled')",
                name="status",
            ),
        )
    for name, columns in (
        ("ix_data_deletion_requests_patient_status", ["patient_id", "status"]),
        ("ix_data_deletion_requests_due", ["status", "scheduled_for"]),
    ):
        if name not in _indexes("data_deletion_requests"):
            op.create_index(name, "data_deletion_requests", columns)


def downgrade() -> None:
    if "data_deletion_requests" in _tables():
        op.drop_table("data_deletion_requests")
    if "deleted_at" in _columns("patients"):
        op.drop_column("patients", "deleted_at")
