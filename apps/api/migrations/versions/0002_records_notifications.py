"""Records, notifications, scribe and review tables.

Revision ID: 0002_records_notifications
Revises: 0001_initial
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.repositories.models import Base

revision: str = "0002_records_notifications"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = [
    "document_chunks",
    "documents",
    "medications",
    "notification_deliveries",
    "notifications",
    "review_tasks",
    "encounters",
    "transcripts",
    "transcript_turns",
    "scribe_runs",
    "scribe_drafts",
    "scribe_sources",
    "clinical_notes",
    "clinical_note_versions",
    "note_sources",
    "stock_reservations",
    "contact_channels",
    "memory_preferences",
]


def upgrade() -> None:
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
        tables=[
            Base.metadata.tables[name]
            for name in [
                "memory_preferences",
                "contact_channels",
                "stock_reservations",
                "note_sources",
                "clinical_note_versions",
                "clinical_notes",
                "scribe_sources",
                "scribe_drafts",
                "scribe_runs",
                "transcript_turns",
                "transcripts",
                "encounters",
                "review_tasks",
                "notification_deliveries",
                "notifications",
                "medications",
                "document_chunks",
                "documents",
            ]
        ],
        checkfirst=True,
    )
