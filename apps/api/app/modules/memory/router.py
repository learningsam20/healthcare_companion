"""Preference memory API — Postgres allowlist + durable backend sync."""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Annotated, Any, Literal

from app.core.db import get_session
from app.core.security import AuthContext, get_auth_context
from app.core.services import Services, get_services
from app.modules.memory.policy import ALLOWED_KEYS as ALLOWED_KEYS
from app.modules.memory.policy import reject_if_sensitive
from app.modules.memory.service import MemoryFacade
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

# Re-export for tests that import from router.
_reject_if_sensitive = reject_if_sensitive


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
    session: SessionDep,
    q: str = "preferences",
) -> list[Mem0MemoryOut]:
    """Search durable memory for this subject (empty if backend down/unconfigured)."""
    _ensure_enabled(services)
    hits = await MemoryFacade(services, session).search_semantic(
        subject=context.subject, query=q, limit=20
    )
    return [
        Mem0MemoryOut(id=hit.id, memory=hit.text, metadata=hit.metadata) for hit in hits if hit.text
    ]


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
    reject_if_sensitive(body.value.strip())
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
    await MemoryFacade(services, session).sync_preference(
        subject=context.subject, key=body.key, value=existing.value
    )
    await session.commit()
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
    await MemoryFacade(services, session).delete_preference(subject=context.subject, key=key)
    await session.commit()


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
        await session.delete(row)
    purged = await MemoryFacade(services, session).purge_subject(subject=context.subject)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="memory.purged",
        resource_type="memory_preference",
        resource_id=context.subject,
        metadata={
            "count": len(rows),
            "durable_purged": purged,
            "provenance": "not_clinical_evidence",
        },
    )
    await session.commit()
