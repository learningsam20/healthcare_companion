"""Postgres RLS session helpers for documents / document_chunks."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_patient_rls(session: AsyncSession, patient_id: uuid.UUID | None) -> None:
    """Scope DocChunk/Document RLS to a patient for this transaction.

    Empty string clears the GUC so staff/service paths keep full access under the
    permissive policy branch. Call before patient-scoped retrieval.
    """
    value = str(patient_id) if patient_id else ""
    await session.execute(
        text("SELECT set_config('app.patient_id', :pid, true)"),
        {"pid": value},
    )


async def clear_patient_rls(session: AsyncSession) -> None:
    await set_patient_rls(session, None)
