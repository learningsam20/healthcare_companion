"""Typed source provenance and a deterministic resolver.

Nodes emit source references; this module decides whether each is resolved, stale,
missing or forbidden. The model never writes citation status. Memory and general
knowledge are never clinical evidence.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SourceType(StrEnum):
    DOCUMENT = "document"
    TOOL = "tool"
    MEMORY = "memory"
    CONVERSATION = "conversation"
    RULE = "rule"
    GENERAL = "general"


class SourceStatus(StrEnum):
    RESOLVED = "resolved"
    STALE = "stale"
    MISSING = "missing"
    FORBIDDEN = "forbidden"


CLINICAL_EVIDENCE_TYPES = {SourceType.DOCUMENT, SourceType.TOOL, SourceType.RULE}


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=200)
    type: SourceType
    title: str = Field(min_length=1, max_length=300)
    locator: str | None = Field(default=None, max_length=200)
    patient_id: uuid.UUID | None = None
    observed_at: dt.datetime | None = None
    status: SourceStatus = SourceStatus.RESOLVED
    snippet: str | None = Field(default=None, max_length=600)
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def usable_as_evidence(self) -> bool:
        return self.status is SourceStatus.RESOLVED and self.type in CLINICAL_EVIDENCE_TYPES


def resolve_sources(
    refs: list[SourceRef],
    *,
    current_patient_id: uuid.UUID | None,
    now: dt.datetime | None = None,
    stale_after: dt.timedelta = dt.timedelta(hours=24),
    require_locator_for: frozenset[SourceType] = frozenset({SourceType.DOCUMENT, SourceType.TOOL}),
) -> list[SourceRef]:
    """Return deduplicated refs with model-claimed status recomputed.

    A document or tool reference for a different patient is forbidden even if the
    model says it is resolved. Missing locators on evidence-bearing types are missing.
    Memory and general knowledge are never promoted to clinical evidence.
    """

    current_time = now or dt.datetime.now(dt.UTC)
    seen: set[tuple[str, str, str | None]] = set()
    resolved: list[SourceRef] = []
    for ref in refs:
        key = (ref.type.value, ref.id, ref.locator)
        if key in seen:
            continue
        seen.add(key)
        status = SourceStatus.RESOLVED
        if (
            ref.type in {SourceType.DOCUMENT, SourceType.TOOL}
            and ref.patient_id is not None
            and ref.patient_id != current_patient_id
        ):
            status = SourceStatus.FORBIDDEN
        if status is SourceStatus.RESOLVED and ref.type in require_locator_for and not ref.locator:
            status = SourceStatus.MISSING
        if status is SourceStatus.RESOLVED and ref.observed_at is not None:
            observed = ref.observed_at
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=dt.UTC)
            if current_time - observed > stale_after:
                status = SourceStatus.STALE
        resolved.append(ref.model_copy(update={"status": status}))
    return resolved


def has_usable_evidence(refs: list[SourceRef]) -> bool:
    return any(ref.usable_as_evidence for ref in refs)


def forbidden_or_missing(refs: list[SourceRef]) -> list[SourceRef]:
    return [ref for ref in refs if ref.status in {SourceStatus.FORBIDDEN, SourceStatus.MISSING}]
