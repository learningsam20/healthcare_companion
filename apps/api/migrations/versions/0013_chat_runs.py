"""Add chat_runs registry for interrupt/resume.

Revision ID: 0013_chat_runs
Revises: 0012_patient_contact_metadata
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_chat_runs"
down_revision: str | None = "0012_patient_contact_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "chat_runs" in tables:
        return
    op.create_table(
        "chat_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_subject", sa.String(200), nullable=False),
        sa.Column("graph", sa.String(80), nullable=False),
        sa.Column("graph_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("interrupt_type", sa.String(40), nullable=True),
        sa.Column("interrupt_id", sa.String(64), nullable=True),
        sa.Column(
            "interrupt_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "checkpoint",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("result_message_id", sa.Uuid(), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','interrupted','completed','failed','cancelled')",
            name="chat_run_status",
        ),
    )
    op.create_index("ix_chat_runs_session_started", "chat_runs", ["session_id", "started_at"])
    op.create_index("ix_chat_runs_owner_status", "chat_runs", ["owner_subject", "status"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "chat_runs" not in tables:
        return
    op.drop_index("ix_chat_runs_owner_status", table_name="chat_runs")
    op.drop_index("ix_chat_runs_session_started", table_name="chat_runs")
    op.drop_table("chat_runs")
