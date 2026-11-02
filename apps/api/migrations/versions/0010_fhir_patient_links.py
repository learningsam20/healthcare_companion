"""FHIR patient crosswalk for read-only demographics and encounters.

Revision ID: 0010_fhir_patient_links
Revises: 0009_consent_granted_default
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_fhir_patient_links"
down_revision: str | None = "0009_consent_granted_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "fhir_patient_links" in _tables():
        return
    op.create_table(
        "fhir_patient_links",
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("fhir_patient_id", sa.String(120), nullable=False),
        sa.Column("system", sa.String(200), nullable=False, server_default="fhir"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_fhir_patient_links_fhir_id", "fhir_patient_links", ["fhir_patient_id"])


def downgrade() -> None:
    if "fhir_patient_links" in _tables():
        op.drop_index("ix_fhir_patient_links_fhir_id", table_name="fhir_patient_links")
        op.drop_table("fhir_patient_links")
