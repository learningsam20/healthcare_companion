"""Scan verdicts, gateway reconciliation, analytics snapshots and insights.

Revision ID: 0005_gap_closure
Revises: 0004_synthetic_audit_reset
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.repositories.models import Base

revision: str = "0005_gap_closure"
down_revision: str | None = "0004_synthetic_audit_reset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = [
    "gateway_spend_logs",
    "spend_reconciliations",
    "analytics_snapshots",
    "insights",
    "job_runs",
]


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> bool:
    if column.name in _columns(table):
        return False
    op.add_column(table, column)
    return True


def _create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    added_document_status = _add_column_if_missing(
        "documents",
        sa.Column("scan_status", sa.String(20), nullable=False, server_default="pending"),
    )
    _add_column_if_missing("documents", sa.Column("scan_engine", sa.String(60), nullable=True))
    _add_column_if_missing(
        "documents", sa.Column("scan_engine_version", sa.String(120), nullable=True)
    )
    _add_column_if_missing(
        "documents", sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_column_if_missing("documents", sa.Column("quarantine_key", sa.String(400), nullable=True))
    if added_document_status:
        op.execute(
            "UPDATE documents SET scan_status = 'unavailable', scan_engine = 'pre_scan_upgrade'"
        )

    added_transcript_status = _add_column_if_missing(
        "transcripts",
        sa.Column("scan_status", sa.String(20), nullable=False, server_default="pending"),
    )
    _add_column_if_missing("transcripts", sa.Column("scan_engine", sa.String(60), nullable=True))
    _add_column_if_missing(
        "transcripts", sa.Column("scan_engine_version", sa.String(120), nullable=True)
    )
    _add_column_if_missing(
        "transcripts", sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True)
    )
    if added_transcript_status:
        op.execute(
            "UPDATE transcripts SET scan_status = 'unavailable', scan_engine = 'pre_scan_upgrade'"
        )

    _add_column_if_missing(
        "usage_records", sa.Column("gateway_request_id", sa.String(200), nullable=True)
    )
    _create_index_if_missing(
        "ix_usage_records_gateway_request",
        "usage_records",
        ["gateway_request_id"],
    )

    _add_column_if_missing("scribe_runs", sa.Column("trace_id", sa.String(64), nullable=True))

    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in NEW_TABLES],
        checkfirst=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in reversed(NEW_TABLES)],
        checkfirst=True,
    )
    op.drop_column("scribe_runs", "trace_id")
    op.drop_index("ix_usage_records_gateway_request", table_name="usage_records")
    op.drop_column("usage_records", "gateway_request_id")
    op.drop_column("transcripts", "scanned_at")
    op.drop_column("transcripts", "scan_engine_version")
    op.drop_column("transcripts", "scan_engine")
    op.drop_column("transcripts", "scan_status")
    op.drop_column("documents", "quarantine_key")
    op.drop_column("documents", "scanned_at")
    op.drop_column("documents", "scan_engine_version")
    op.drop_column("documents", "scan_engine")
    op.drop_column("documents", "scan_status")
