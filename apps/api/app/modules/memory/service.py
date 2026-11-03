"""MemoryFacade: durable non-clinical recall/write + provenance sources."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sahyog_common.provenance import SourceRef, SourceType, resolve_sources
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.mem0_client import Mem0Client
from app.modules.memory.backends import (
    DurableHit,
    DurableMemoryBackend,
    Mem0DurableBackend,
    PgvectorDurableBackend,
)
from app.modules.memory.policy import is_sensitive
from app.repositories.models import MemoryPreference

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecallBundle:
    memory_note: str | None = None
    opted_out: bool = False
    hits: list[DurableHit] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    attribution: str | None = None


def conversation_sources(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Cite earlier turns in this session when history informs the reply."""
    prior = [m for m in history if m.get("role") in {"user", "assistant"}]
    if len(prior) < 2:
        return []
    snippet_parts: list[str] = []
    for item in prior[-4:]:
        role = item.get("role", "")
        text = str(item.get("content") or "").strip().replace("\n", " ")
        if not text:
            continue
        snippet_parts.append(f"{role}: {text[:120]}")
    snippet = " | ".join(snippet_parts)[:500] or "Earlier turns in this chat session"
    refs = resolve_sources(
        [
            SourceRef(
                id="conversation:recent",
                type=SourceType.CONVERSATION,
                title="Earlier turns in this chat session",
                locator="C1",
                snippet=snippet,
                metadata={"scope": "session", "turns": str(len(prior))},
            )
        ],
        current_patient_id=None,
    )
    return [r.model_dump(mode="json") for r in refs]


def memory_sources(hits: list[DurableHit]) -> list[dict[str, Any]]:
    refs: list[SourceRef] = []
    for index, hit in enumerate(hits, start=1):
        kind_label = "Remembered preference" if hit.kind == "preference" else "Session memory"
        title = hit.metadata.get("key")
        if title:
            display = f"{kind_label}: {title}"
        else:
            display = f"{kind_label} (not clinical evidence)"
        refs.append(
            SourceRef(
                id=f"memory:{hit.id}",
                type=SourceType.MEMORY,
                title=display[:300],
                locator=f"M{index}",
                snippet=hit.text[:500],
                metadata={
                    "kind": hit.kind,
                    "not_clinical_evidence": "true",
                    **{k: str(v) for k, v in hit.metadata.items() if k in {"key", "session_id"}},
                },
            )
        )
    return [r.model_dump(mode="json") for r in resolve_sources(refs, current_patient_id=None)]


def attribution_footer(hits: list[DurableHit], *, history_cited: bool) -> str | None:
    parts: list[str] = []
    for index, hit in enumerate(hits, start=1):
        label = hit.metadata.get("key") or hit.kind
        parts.append(f"[M{index}] {label}: {hit.text[:100]}")
    if history_cited:
        parts.append("[C1] earlier turns in this chat")
    if not parts:
        return None
    return "Based on remembered context (not clinical evidence): " + "; ".join(parts)


def append_attribution(content: str, attribution: str | None) -> str:
    if not attribution:
        return content
    body = (content or "").rstrip()
    if not body:
        return attribution
    if attribution in body:
        return body
    return f"{body}\n\n— {attribution}"


class MemoryFacade:
    def __init__(
        self,
        services: Any,
        session: AsyncSession,
        *,
        backend: DurableMemoryBackend | None = None,
    ) -> None:
        self._services = services
        self._session = session
        self._backend = backend or self._build_backend()

    def _build_backend(self) -> DurableMemoryBackend:
        choice = str(getattr(self._services.settings, "memory_backend", "mem0") or "mem0").lower()
        if choice == "pgvector":
            return PgvectorDurableBackend(self._session, self._services)
        return Mem0DurableBackend(Mem0Client(self._services.settings))

    @property
    def enabled(self) -> bool:
        return bool(self._services.features.enabled("memory_preferences"))

    async def _opted_out(self, subject: str) -> bool:
        rows = list(
            await self._session.scalars(
                select(MemoryPreference).where(MemoryPreference.subject == subject).limit(24)
            )
        )
        return any(
            row.key == "opt_out" and row.value.lower() in {"1", "true", "yes"} for row in rows
        )

    async def _preference_rows(self, subject: str) -> list[MemoryPreference]:
        return list(
            await self._session.scalars(
                select(MemoryPreference)
                .where(MemoryPreference.subject == subject)
                .order_by(MemoryPreference.key.asc())
                .limit(24)
            )
        )

    async def recall(
        self,
        *,
        subject: str,
        query: str,
        session_id: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> RecallBundle:
        if not self.enabled:
            hist_sources = conversation_sources(history or [])
            return RecallBundle(
                sources=hist_sources,
                attribution=attribution_footer([], history_cited=bool(hist_sources)),
            )
        if await self._opted_out(subject):
            return RecallBundle(opted_out=True)

        prefs = await self._preference_rows(subject)
        pref_bits = [f"{row.key}={row.value}" for row in prefs if row.key != "opt_out"]
        hits: list[DurableHit] = []

        # Structured prefs as durable hits for citation.
        for row in prefs:
            if row.key == "opt_out":
                continue
            hits.append(
                DurableHit(
                    id=str(row.id),
                    text=f"Preference {row.key}: {row.value}",
                    kind="preference",
                    metadata={"key": row.key, "source": "postgres"},
                )
            )

        semantic = await self._backend.search(
            subject=subject, query=(query or "preferences")[:240], limit=3
        )
        seen = {h.text for h in hits}
        for hit in semantic:
            if hit.text in seen:
                continue
            hits.append(hit)
            seen.add(hit.text)

        if session_id:
            episodic = await self._backend.search(
                subject=subject,
                query=(query or "session")[:240],
                limit=2,
                session_id=session_id,
                kind="episodic",
            )
            for hit in episodic:
                if hit.text in seen:
                    continue
                hits.append(hit)
                seen.add(hit.text)

        hits = hits[:6]
        note_parts: list[str] = []
        if pref_bits:
            note_parts.append("User preferences (allowlisted): " + "; ".join(pref_bits))
        extra = [
            h.text
            for h in hits
            if h.metadata.get("source") != "postgres" or h.kind == "episodic"
        ][:3]
        if extra:
            note_parts.append("Durable recalls: " + " | ".join(extra))
        memory_note = "; ".join(note_parts) if note_parts else None

        mem_sources = memory_sources(hits)
        hist_sources = conversation_sources(history or [])
        attribution = attribution_footer(hits, history_cited=bool(hist_sources))
        return RecallBundle(
            memory_note=memory_note,
            hits=hits,
            sources=[*mem_sources, *hist_sources],
            attribution=attribution,
        )

    async def sync_preference(self, *, subject: str, key: str, value: str) -> None:
        if key == "opt_out" or not self.enabled:
            return
        await self._backend.add(
            subject=subject,
            text=f"Preference {key}: {value}",
            kind="preference",
            metadata={"key": key, "allowlisted": True},
        )

    async def delete_preference(self, *, subject: str, key: str) -> None:
        await self._backend.delete_by_key(subject=subject, key=key)

    async def purge_subject(self, *, subject: str) -> int:
        return await self._backend.purge_subject(subject=subject)

    async def purge_session(self, *, subject: str, session_id: str) -> int:
        return await self._backend.purge_session(subject=subject, session_id=session_id)

    async def remember_session_turn(
        self,
        *,
        subject: str,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        if not self.enabled or await self._opted_out(subject):
            return
        summary = f"Session note: user asked about '{user_text[:120].strip()}'"
        if is_sensitive(summary) or is_sensitive(user_text):
            return
        # Keep episodic non-clinical: strip assistant clinical-looking replies.
        if is_sensitive(assistant_text):
            summary = f"Session note: continued chat about scheduling or preferences ({user_text[:80].strip()})"
            if is_sensitive(summary):
                return
        await self._backend.add(
            subject=subject,
            text=summary[:500],
            kind="episodic",
            session_id=session_id,
            metadata={"session_id": session_id},
        )

    async def search_semantic(self, *, subject: str, query: str, limit: int = 20) -> list[DurableHit]:
        if not self.enabled or await self._opted_out(subject):
            return []
        return await self._backend.search(subject=subject, query=query, limit=limit)
