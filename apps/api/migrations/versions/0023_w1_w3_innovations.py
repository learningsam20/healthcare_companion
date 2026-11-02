"""W1–W3 innovation columns: no-show risk, clarify count, chunk quarantine,
scribe review metrics, audit hash chain, clinical note immutability triggers, RLS.

Revision ID: 0023_w1_w3_innovations
Revises: 0022_handoff_mtta
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_w1_w3_innovations"
down_revision: str | None = "0022_handoff_mtta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    appt_cols = {c["name"] for c in inspector.get_columns("appointments")}
    if "no_show_risk" not in appt_cols:
        op.add_column("appointments", sa.Column("no_show_risk", sa.Float(), nullable=True))
    if "no_show_band" not in appt_cols:
        op.add_column(
            "appointments",
            sa.Column("no_show_band", sa.String(length=20), nullable=True),
        )
    if "waitlist_suggested" not in appt_cols:
        op.add_column(
            "appointments",
            sa.Column("waitlist_suggested", sa.Boolean(), nullable=False, server_default="false"),
        )
    if "confirm_by_reply" not in appt_cols:
        op.add_column(
            "appointments",
            sa.Column("confirm_by_reply", sa.Boolean(), nullable=False, server_default="false"),
        )
    if not _has_index(inspector, "appointments", "ix_appointments_no_show_band"):
        op.create_index(
            "ix_appointments_no_show_band",
            "appointments",
            ["no_show_band"],
            unique=False,
        )

    chat_cols = {c["name"] for c in inspector.get_columns("chat_sessions")}
    if "specialty_clarify_count" not in chat_cols:
        op.add_column(
            "chat_sessions",
            sa.Column("specialty_clarify_count", sa.Integer(), nullable=False, server_default="0"),
        )

    chunk_cols = {c["name"] for c in inspector.get_columns("document_chunks")}
    if "quarantine_tag" not in chunk_cols:
        op.add_column(
            "document_chunks",
            sa.Column("quarantine_tag", sa.String(length=40), nullable=True),
        )
    if "retrieval_allowed" not in chunk_cols:
        op.add_column(
            "document_chunks",
            sa.Column(
                "retrieval_allowed",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
        )
    if not _has_index(inspector, "document_chunks", "ix_document_chunks_retrieval"):
        op.create_index(
            "ix_document_chunks_retrieval",
            "document_chunks",
            ["patient_id", "retrieval_allowed"],
            unique=False,
        )

    run_cols = {c["name"] for c in inspector.get_columns("scribe_runs")}
    if "review_seconds" not in run_cols:
        op.add_column("scribe_runs", sa.Column("review_seconds", sa.Float(), nullable=True))
    if "edit_distance" not in run_cols:
        op.add_column(
            "scribe_runs",
            sa.Column("edit_distance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )

    version_cols = {c["name"] for c in inspector.get_columns("clinical_note_versions")}
    if "prev_content_hash" not in version_cols:
        op.add_column(
            "clinical_note_versions",
            sa.Column("prev_content_hash", sa.String(length=64), nullable=True),
        )

    audit_cols = {c["name"] for c in inspector.get_columns("audit_events")}
    if "prev_hash" not in audit_cols:
        op.add_column("audit_events", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    if "event_hash" not in audit_cols:
        op.add_column("audit_events", sa.Column("event_hash", sa.String(length=64), nullable=True))
    if not _has_index(inspector, "audit_events", "ix_audit_events_event_hash"):
        op.create_index(
            "ix_audit_events_event_hash",
            "audit_events",
            ["event_hash"],
            unique=False,
        )

    # Clinical note versions: block UPDATE/DELETE (immutability).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sahyog_note_version_immutable() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'clinical_note_versions are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_clinical_note_versions_immutable ON clinical_note_versions")
    op.execute(
        """
        CREATE TRIGGER trg_clinical_note_versions_immutable
        BEFORE UPDATE OR DELETE ON clinical_note_versions
        FOR EACH ROW EXECUTE FUNCTION sahyog_note_version_immutable();
        """
    )

    # Clinical notes: refuse hard deletes (corrections amend via new versions).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sahyog_clinical_note_no_delete() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'clinical_notes cannot be deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_clinical_notes_no_delete ON clinical_notes")
    op.execute(
        """
        CREATE TRIGGER trg_clinical_notes_no_delete
        BEFORE DELETE ON clinical_notes
        FOR EACH ROW EXECUTE FUNCTION sahyog_clinical_note_no_delete();
        """
    )

    # Row-level security on documents / document_chunks (defence in depth).
    # Application sets: SET LOCAL app.patient_id = '<uuid>' (empty = staff/service bypass).
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS documents_patient_scope ON documents")
    op.execute("DROP POLICY IF EXISTS document_chunks_patient_scope ON document_chunks")
    op.execute(
        """
        CREATE POLICY documents_patient_scope ON documents
        FOR ALL
        USING (
          current_setting('app.patient_id', true) IS NULL
          OR current_setting('app.patient_id', true) = ''
          OR patient_id::text = current_setting('app.patient_id', true)
        )
        WITH CHECK (
          current_setting('app.patient_id', true) IS NULL
          OR current_setting('app.patient_id', true) = ''
          OR patient_id::text = current_setting('app.patient_id', true)
        )
        """
    )
    op.execute(
        """
        CREATE POLICY document_chunks_patient_scope ON document_chunks
        FOR ALL
        USING (
          current_setting('app.patient_id', true) IS NULL
          OR current_setting('app.patient_id', true) = ''
          OR patient_id::text = current_setting('app.patient_id', true)
        )
        WITH CHECK (
          current_setting('app.patient_id', true) IS NULL
          OR current_setting('app.patient_id', true) = ''
          OR patient_id::text = current_setting('app.patient_id', true)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS document_chunks_patient_scope ON document_chunks")
    op.execute("DROP POLICY IF EXISTS documents_patient_scope ON documents")
    op.execute("ALTER TABLE document_chunks NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_chunks DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TRIGGER IF EXISTS trg_clinical_notes_no_delete ON clinical_notes")
    op.execute("DROP FUNCTION IF EXISTS sahyog_clinical_note_no_delete()")
    op.execute("DROP TRIGGER IF EXISTS trg_clinical_note_versions_immutable ON clinical_note_versions")
    op.execute("DROP FUNCTION IF EXISTS sahyog_note_version_immutable()")
    op.drop_index("ix_audit_events_event_hash", table_name="audit_events")
    op.drop_column("audit_events", "event_hash")
    op.drop_column("audit_events", "prev_hash")
    op.drop_column("clinical_note_versions", "prev_content_hash")
    op.drop_column("scribe_runs", "edit_distance")
    op.drop_column("scribe_runs", "review_seconds")
    op.drop_index("ix_document_chunks_retrieval", table_name="document_chunks")
    op.drop_column("document_chunks", "retrieval_allowed")
    op.drop_column("document_chunks", "quarantine_tag")
    op.drop_column("chat_sessions", "specialty_clarify_count")
    op.drop_index("ix_appointments_no_show_band", table_name="appointments")
    op.drop_column("appointments", "confirm_by_reply")
    op.drop_column("appointments", "waitlist_suggested")
    op.drop_column("appointments", "no_show_band")
    op.drop_column("appointments", "no_show_risk")
