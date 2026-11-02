"""Add chat_feedback and trigram indexes for hybrid retrieval.

Revision ID: 0014_chat_feedback_trgm
Revises: 0013_chat_runs
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_chat_feedback_trgm"
down_revision: str | None = "0013_chat_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "chat_feedback" not in tables:
        op.create_table(
            "chat_feedback",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "message_id",
                sa.Uuid(),
                sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_subject", sa.String(200), nullable=False),
            sa.Column("rating", sa.String(20), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("review_task_id", sa.Uuid(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "rating IN ('up','down','helpful','not_helpful')",
                name="chat_feedback_rating",
            ),
            sa.UniqueConstraint("message_id", "user_subject", name="uq_chat_feedback_message_user"),
        )
        op.create_index("ix_chat_feedback_user", "chat_feedback", ["user_subject"])
        op.create_index("ix_chat_feedback_message", "chat_feedback", ["message_id"])

    # Trigram indexes for hybrid lexical recall (pg_trgm already installed in 0001).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_content_trgm "
        "ON document_chunks USING gin (content gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_title_trgm "
        "ON documents USING gin (title gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_trgm")
    op.drop_table("chat_feedback")
