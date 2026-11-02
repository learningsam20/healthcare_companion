"""Allow the synthetic-cohort reset to remove its own audit rows.

The audit table stays append-only for application paths. A transaction-scoped
setting may name the synthetic patient IDs and subjects being erased; only rows
that match that scope can be deleted. Every other delete or update still raises.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_synthetic_audit_reset"
down_revision: str | None = "0003_eval_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPED_FUNCTION = """
CREATE OR REPLACE FUNCTION sahyog_audit_append_only()
RETURNS trigger AS $$
DECLARE
    scope jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        scope := NULLIF(current_setting('sahyog.synthetic_reset_scope', true), '')::jsonb;
        IF scope IS NOT NULL AND (
            (
                OLD.patient_id IS NOT NULL
                AND OLD.patient_id::text IN (
                    SELECT jsonb_array_elements_text(scope->'patient_ids')
                )
            )
            OR OLD.actor_subject IN (
                SELECT jsonb_array_elements_text(scope->'subjects')
            )
        ) THEN
            RETURN OLD;
        END IF;
    END IF;
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;
"""

STRICT_FUNCTION = """
CREATE OR REPLACE FUNCTION sahyog_audit_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(SCOPED_FUNCTION)


def downgrade() -> None:
    op.execute(STRICT_FUNCTION)
