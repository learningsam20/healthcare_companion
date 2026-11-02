"""Consent lifecycle: grantor, purpose, granted_at, revoked_at and audit linkage.

Revision ID: 0007_consent_lifecycle
Revises: 0006_reconciliation_partial
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_consent_lifecycle"
down_revision: str | None = "0006_reconciliation_partial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> bool:
    if column.name in _columns(table):
        return False
    op.add_column(table, column)
    return True


def upgrade() -> None:
    added_grantor = _add_column_if_missing(
        "consents", sa.Column("grantor_subject", sa.String(200), nullable=True)
    )
    added_purpose = _add_column_if_missing(
        "consents", sa.Column("purpose", sa.String(200), nullable=True)
    )
    added_granted_at = _add_column_if_missing(
        "consents", sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_column_if_missing(
        "consents", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
    )

    if added_grantor or added_purpose or added_granted_at:
        op.execute(
            "UPDATE consents SET grantor_subject = COALESCE(grantor_subject, 'system:seed'), "
            "purpose = COALESCE(purpose, 'care'), "
            "granted_at = COALESCE(granted_at, created_at)"
        )
    for column, added in (
        ("grantor_subject", added_grantor),
        ("purpose", added_purpose),
        ("granted_at", added_granted_at),
    ):
        if added:
            if column == "granted_at":
                op.alter_column(
                    "consents", column, nullable=False, server_default=sa.func.now()
                )
            else:
                op.alter_column("consents", column, nullable=False)

    _add_column_if_missing("audit_events", sa.Column("consent_id", sa.Uuid(), nullable=True))
    if "ix_audit_events_consent_created" not in _indexes("audit_events"):
        op.create_index(
            "ix_audit_events_consent_created",
            "audit_events",
            ["consent_id", "created_at"],
        )


def downgrade() -> None:
    if "ix_audit_events_consent_created" in _indexes("audit_events"):
        op.drop_index("ix_audit_events_consent_created", table_name="audit_events")
    if "consent_id" in _columns("audit_events"):
        op.drop_column("audit_events", "consent_id")
    for column in ("revoked_at", "granted_at", "purpose", "grantor_subject"):
        if column in _columns("consents"):
            op.drop_column("consents", column)
