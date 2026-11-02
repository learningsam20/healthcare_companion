"""Preference memory API — Postgres allowlist + optional self-hosted Mem0 sync."""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from typing import Annotated, Any, Literal

from app.core.db import get_session
from app.core.security import AuthContext, get_auth_context
from app.core.services import Services, get_services
from app.integrations.mem0_client import Mem0Client, Mem0Unavailable
from app.repositories.audit import AuditRepository
from app.repositories.models import MemoryPreference
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sahyog_common.errors import ProblemError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/me/memory", tags=["memory"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ContextDep = Annotated[AuthContext, Depends(get_auth_context)]
ServicesDep = Annotated[Services, Depends(get_services)]

ALLOWED_KEYS = frozenset(
    {
        "preferred_locale",
        "preferred_clinic",
        "preferred_channel",
        "appointment_reminder",
        "ui_density",
        "opt_out",
    }
)

# Preference values must stay non-clinical and free of identifiers before Mem0 sync.
_PII_OR_CLINICAL = re.compile(
    r"("
    r"[\w.+-]+@[\w-]+\.[\w.-]+|"  # email
    r"\b\d{10,12}\b|"  # phone / aadhaar-ish
    r"\b[A-Z]{5}\d{4}[A-Z]\b|"  # PAN
    r"\b(diagnos|prescri|insulin|hiv|cancer|dose|mg\b|tablet|symptom)\b"
    r")",
    re.IGNORECASE,
)


def _reject_if_sensitive(value: str) -> None:
    if _PII_OR_CLINICAL.search(value):
        raise ProblemError(
            422,
            "memory_value_rejected",
            "Value rejected",
            "Preference values cannot contain identifiers or clinical detail.",
        )


class MemoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    value: str
    updated_at: dt.datetime
    source: str = "postgres"


class MemoryUpsert(BaseModel):
    key: Literal[
        "preferred_locale",
        "preferred_clinic",
        "preferred_channel",
        "appointment_reminder",
        "ui_density",
        "opt_out",
    ]
    value: str = Field(min_length=1, max_length=500)


class Mem0MemoryOut(BaseModel):
    id: str
    memory: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def _ensure_enabled(services: Services) -> None:
    if not services.features.enabled("memory_preferences"):
        raise ProblemError(
            403,
            "feature_disabled",
            "Memory unavailable",
            "Preference memory is disabled by configuration.",
        )


async def _sync_mem0_add(services: Services, *, subject: str, key: str, value: str) -> None:
    client = Mem0Client(services.settings)
    if not client.configured or key == "opt_out":
        return
    try:
        await client.add(
            user_id=subject,
            text=f"Preference {key}: {value}",
            metadata={"key": key, "allowlisted": True, "source": "sahyog"},
        )
    except Mem0Unavailable as exc:
        logger.warning(
            "mem0 sync skipped",
            extra={"event": "memory.mem0_sync_failed", "extra_fields": {"reason": str(exc)}},
        )


async def _sync_mem0_delete(services: Services, *, subject: str, key: str) -> None:
    client = Mem0Client(services.settings)
    if not client.configured:
        return
    try:
        rows = await client.list_for_user(user_id=subject)
        for row in rows:
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            memory_id = str(row.get("id") or row.get("memory_id") or "")
            text = str(row.get("memory") or row.get("text") or "")
            matches_key = meta.get("key") == key or f"Preference {key}:" in text
            if memory_id and matches_key:
                await client.delete(memory_id=memory_id)
    except Mem0Unavailable as exc:
        logger.warning(
            "mem0 delete skipped",
            extra={"event": "memory.mem0_delete_failed", "extra_fields": {"reason": str(exc)}},
        )


@router.get("", response_model=list[MemoryItem])
async def list_memory(
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> list[MemoryItem]:
    _ensure_enabled(services)
    rows = await session.scalars(
        select(MemoryPreference)
        .where(MemoryPreference.subject == context.subject)
        .order_by(MemoryPreference.key.asc())
    )
    return [
        MemoryItem.model_validate(row).model_copy(update={"source": "postgres"}) for row in rows
    ]


@router.get("/semantic", response_model=list[Mem0MemoryOut])
async def list_semantic_memory(
    context: ContextDep,
    services: ServicesDep,
    q: str = "preferences",
) -> list[Mem0MemoryOut]:
    """Search self-hosted Mem0 for this subject (empty if Mem0 is down/unconfigured)."""
    _ensure_enabled(services)
    client = Mem0Client(services.settings)
    if not client.configured:
        return []
    try:
        rows = await client.search(user_id=context.subject, query=q, limit=20)
    except Mem0Unavailable:
        return []
    out: list[Mem0MemoryOut] = []
    for row in rows:
        mid = str(row.get("id") or row.get("memory_id") or "")
        text = str(row.get("memory") or row.get("text") or row.get("data") or "")
        if not text:
            continue
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        out.append(Mem0MemoryOut(id=mid or text[:32], memory=text, metadata=meta))
    return out


@router.put("", response_model=MemoryItem)
async def upsert_memory(
    body: MemoryUpsert,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> MemoryItem:
    _ensure_enabled(services)
    if body.key not in ALLOWED_KEYS:
        raise ProblemError(
            422, "key_not_allowed", "Key not allowed", "That preference key is not permitted."
        )
    _reject_if_sensitive(body.value.strip())
    existing = await session.scalar(
        select(MemoryPreference).where(
            MemoryPreference.subject == context.subject,
            MemoryPreference.key == body.key,
        )
    )
    if existing is None:
        existing = MemoryPreference(
            subject=context.subject, key=body.key, value=body.value.strip()
        )
        session.add(existing)
    else:
        existing.value = body.value.strip()
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="memory.upserted",
        resource_type="memory_preference",
        resource_id=body.key,
        metadata={"key": body.key},
    )
    await session.commit()
    await session.refresh(existing)
    await _sync_mem0_add(
        services, subject=context.subject, key=body.key, value=existing.value
    )
    return MemoryItem.model_validate(existing).model_copy(update={"source": "postgres"})


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    key: str,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> None:
    _ensure_enabled(services)
    row = await session.scalar(
        select(MemoryPreference).where(
            MemoryPreference.subject == context.subject,
            MemoryPreference.key == key,
        )
    )
    if row is None:
        return
    await session.delete(row)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="memory.deleted",
        resource_type="memory_preference",
        resource_id=key,
        metadata={"key": key},
    )
    await session.commit()
    await _sync_mem0_delete(services, subject=context.subject, key=key)


@router.post("/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_memory(
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> None:
    """Forget all preference rows for the subject (opt-out / right to be forgotten)."""
    _ensure_enabled(services)
    rows = list(
        await session.scalars(
            select(MemoryPreference).where(MemoryPreference.subject == context.subject)
        )
    )
    for row in rows:
        key = row.key
        await session.delete(row)
        await _sync_mem0_delete(services, subject=context.subject, key=key)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="memory.purged",
        resource_type="memory_preference",
        resource_id=context.subject,
        metadata={"count": len(rows), "provenance": "not_clinical_evidence"},
    )
    await session.commit()
