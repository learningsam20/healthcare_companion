"""Allow partial reconciliation status when some calls remain unmatched.

Revision ID: 0006_reconciliation_partial
Revises: 0005_gap_closure
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_reconciliation_partial"
down_revision: str | None = "0005_gap_closure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_spend_reconciliations_status"


def upgrade() -> None:
    op.execute(f"ALTER TABLE spend_reconciliations DROP CONSTRAINT {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE spend_reconciliations ADD CONSTRAINT {CONSTRAINT} "
        "CHECK (status IN ('matched','partial','variance','insufficient_data'))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE spend_reconciliations DROP CONSTRAINT {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE spend_reconciliations ADD CONSTRAINT {CONSTRAINT} "
        "CHECK (status IN ('matched','variance','insufficient_data'))"
    )
