"""First-party agent_memories table for MEMORY_BACKEND=pgvector.

Revision ID: 0025_agent_memories
Revises: 0024_waitlist_claim_audit_verify
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0025_agent_memories"
down_revision: str | None = "0024_waitlist_claim_audit_verify"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_memories" in inspector.get_table_names():
        return
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('preference','episodic')", name="ck_agent_memories_agent_memory_kind"),
    )
    op.create_index("ix_agent_memories_subject_kind", "agent_memories", ["subject", "kind"])
    op.create_index("ix_agent_memories_session", "agent_memories", ["session_id"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_memories_embedding_hnsw "
        "ON agent_memories USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agent_memories_embedding_hnsw")
    op.drop_index("ix_agent_memories_session", table_name="agent_memories")
    op.drop_index("ix_agent_memories_subject_kind", table_name="agent_memories")
    op.drop_table("agent_memories")
