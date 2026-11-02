"""Pharmacy stock_items inventory and stock_imports evidence.

Revision ID: 0011_stock_items
Revises: 0010_fhir_patient_links
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_stock_items"
down_revision: str | None = "0010_fhir_patient_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "stock_items" not in _tables():
        op.create_table(
            "stock_items",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("sku", sa.String(80), nullable=False),
            sa.Column("drug_name", sa.String(200), nullable=False),
            sa.Column("form", sa.String(80), nullable=False, server_default=""),
            sa.Column("strength", sa.String(80), nullable=False, server_default=""),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("clinic_code", sa.String(40), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source", sa.String(80), nullable=False, server_default="demo-stock"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_stock_items_clinic_name", "stock_items", ["clinic_code", "drug_name"])
        op.create_index(
            "uq_stock_items_clinic_sku", "stock_items", ["clinic_code", "sku"], unique=True
        )

    if "stock_imports" not in _tables():
        op.create_table(
            "stock_imports",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("source", sa.String(80), nullable=False),
            sa.Column("file_hash", sa.String(64), nullable=False),
            sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="succeeded"),
            sa.Column("errors", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_stock_imports_created", "stock_imports", ["created_at"])


def downgrade() -> None:
    if "stock_imports" in _tables():
        op.drop_index("ix_stock_imports_created", table_name="stock_imports")
        op.drop_table("stock_imports")
    if "stock_items" in _tables():
        op.drop_index("uq_stock_items_clinic_sku", table_name="stock_items")
        op.drop_index("ix_stock_items_clinic_name", table_name="stock_items")
        op.drop_table("stock_items")
