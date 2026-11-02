"""Evaluation run and metric result tables.

Revision ID: 0003_eval_runs
Revises: 0002_records_notifications
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.repositories.models import Base

revision: str = "0003_eval_runs"
down_revision: str | None = "0002_records_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ["eval_runs", "eval_metric_results"]


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
        tables=[Base.metadata.tables[name] for name in reversed(NEW_TABLES)],
        checkfirst=True,
    )
