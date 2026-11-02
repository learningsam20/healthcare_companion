"""Wave F: chat title_source, message safety, handoff SLA fields.

Revision ID: 0021_wave_f_titles_sla_safety
Revises: 0020_appointment_source
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_wave_f_titles_sla_safety"
down_revision: str | None = "0020_appointment_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    chat_cols = {c["name"] for c in sa.inspect(bind).get_columns("chat_sessions")}
    if "title_source" not in chat_cols:
        op.add_column(
            "chat_sessions",
            sa.Column("title_source", sa.String(20), server_default="system", nullable=False),
        )
    op.execute(
        """
        DO $$ BEGIN
          ALTER TABLE chat_sessions
            ADD CONSTRAINT ck_chat_sessions_title_source
            CHECK (title_source IN ('system', 'user'));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    # Sessions created with a non-placeholder title were user-named.
    op.execute(
        """
        UPDATE chat_sessions
        SET title_source = 'user'
        WHERE title NOT IN ('New conversation', 'New chat', '')
          AND title_source = 'system'
          AND created_at = updated_at
        """
    )

    msg_cols = {c["name"] for c in sa.inspect(bind).get_columns("chat_messages")}
    if "safety" not in msg_cols:
        op.add_column(
            "chat_messages",
            sa.Column(
                "safety",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )

    handoff_cols = {c["name"] for c in sa.inspect(bind).get_columns("handoffs")}
    additions = {
        "priority": sa.Column("priority", sa.String(20), server_default="normal", nullable=False),
        "sla_due_at": sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
        "notified_at": sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        "delivery_status": sa.Column(
            "delivery_status", sa.String(40), server_default="pending", nullable=False
        ),
        "rule_ids": sa.Column(
            "rule_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        "overdue_alerted_at": sa.Column(
            "overdue_alerted_at", sa.DateTime(timezone=True), nullable=True
        ),
    }
    for name, column in additions.items():
        if name not in handoff_cols:
            op.add_column("handoffs", column)

    op.execute(
        """
        DO $$ BEGIN
          ALTER TABLE handoffs
            ADD CONSTRAINT ck_handoffs_priority
            CHECK (priority IN ('normal', 'urgent', 'emergency'));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          ALTER TABLE handoffs
            ADD CONSTRAINT ck_handoffs_delivery_status
            CHECK (delivery_status IN (
              'pending', 'queued', 'sent', 'partial', 'failed', 'skipped'
            ));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    existing_indexes = {i["name"] for i in sa.inspect(bind).get_indexes("handoffs")}
    if "ix_handoffs_sla_due" not in existing_indexes:
        op.create_index("ix_handoffs_sla_due", "handoffs", ["status", "sla_due_at"])


def downgrade() -> None:
    op.drop_index("ix_handoffs_sla_due", table_name="handoffs")
    for col in (
        "overdue_alerted_at",
        "rule_ids",
        "delivery_status",
        "notified_at",
        "sla_due_at",
        "priority",
    ):
        op.drop_column("handoffs", col)
    op.execute("ALTER TABLE handoffs DROP CONSTRAINT IF EXISTS ck_handoffs_priority")
    op.execute("ALTER TABLE handoffs DROP CONSTRAINT IF EXISTS ck_handoffs_delivery_status")
    op.drop_column("chat_messages", "safety")
    op.execute("ALTER TABLE chat_sessions DROP CONSTRAINT IF EXISTS ck_chat_sessions_title_source")
    op.drop_column("chat_sessions", "title_source")
