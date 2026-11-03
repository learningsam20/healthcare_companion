from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import AuditEvent

SORT_COLUMNS = {
    "created_at": AuditEvent.created_at,
    "action": AuditEvent.action,
    "actor_role": AuditEvent.actor_role,
}

_UNSET: object = object()


def _canonical_payload(
    *,
    actor_subject: str,
    actor_role: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    patient_id: uuid.UUID | None,
    consent_id: uuid.UUID | None,
    trace_id: str | None,
    metadata: dict[str, Any],
    prev_hash: str | None,
) -> str:
    body = {
        "actor_subject": actor_subject,
        "actor_role": actor_role,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "patient_id": str(patient_id) if patient_id else None,
        "consent_id": str(consent_id) if consent_id else None,
        "trace_id": trace_id,
        "metadata": metadata or {},
        "prev_hash": prev_hash or "",
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._pending_prev: str | None | object = _UNSET

    def append(
        self,
        *,
        actor_subject: str,
        actor_role: str,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        patient_id: uuid.UUID | None = None,
        consent_id: uuid.UUID | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        prev_hash: str | None = None,
    ) -> AuditEvent:
        """Append an audit row with a hash-chained digest (ADR-14).

        Chains within a repository instance; cross-request tip continuity is best-effort
        when callers pass ``prev_hash`` explicitly.
        """
        meta = metadata or {}
        tip = prev_hash
        if tip is None and self._pending_prev is not _UNSET:
            tip = self._pending_prev  # type: ignore[assignment]
        if tip is None:
            tip = self._session.info.get("audit_tip")
        tip = tip or ""
        digest = hashlib.sha256(
            _canonical_payload(
                actor_subject=actor_subject,
                actor_role=actor_role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                patient_id=patient_id,
                consent_id=consent_id,
                trace_id=trace_id,
                metadata=meta,
                prev_hash=tip or None,
            ).encode("utf-8")
        ).hexdigest()
        event = AuditEvent(
            actor_subject=actor_subject,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            patient_id=patient_id,
            consent_id=consent_id,
            trace_id=trace_id,
            event_metadata=meta,
            prev_hash=tip or None,
            event_hash=digest,
        )
        self._session.add(event)
        self._pending_prev = digest
        self._session.info["audit_tip"] = digest
        return event

    async def list_events(
        self,
        *,
        query: str | None,
        action: str | None,
        actor_role: str | None,
        start: dt.datetime | None,
        end: dt.datetime | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[AuditEvent], int]:
        conditions = []
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    AuditEvent.action.ilike(pattern),
                    AuditEvent.resource_type.ilike(pattern),
                    AuditEvent.resource_id.ilike(pattern),
                    AuditEvent.actor_subject.ilike(pattern),
                )
            )
        if action:
            conditions.append(AuditEvent.action == action)
        if actor_role:
            conditions.append(AuditEvent.actor_role == actor_role)
        if start:
            conditions.append(AuditEvent.created_at >= start)
        if end:
            conditions.append(AuditEvent.created_at <= end)
        column = SORT_COLUMNS.get(sort, AuditEvent.created_at)
        order = column.desc() if descending else column.asc()
        total = await self._session.scalar(
            select(func.count()).select_from(AuditEvent).where(*conditions)
        )
        rows = await self._session.scalars(
            select(AuditEvent)
            .where(*conditions)
            .order_by(order, AuditEvent.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    @staticmethod
    def expected_hash(event: AuditEvent) -> str:
        return hashlib.sha256(
            _canonical_payload(
                actor_subject=event.actor_subject,
                actor_role=event.actor_role,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                patient_id=event.patient_id,
                consent_id=event.consent_id,
                trace_id=event.trace_id,
                metadata=event.event_metadata or {},
                prev_hash=event.prev_hash,
            ).encode("utf-8")
        ).hexdigest()

    async def verify_chain(self, *, batch_size: int = 500) -> dict[str, Any]:
        """Walk audit_events in order and verify per-row hash digests + tip continuity."""
        checked = 0
        unhashed = 0
        digest_count = 0
        gap_count = 0
        broken: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        tip: str | None = None
        offset = 0
        while True:
            rows = list(
                await self._session.scalars(
                    select(AuditEvent)
                    .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
                    .limit(batch_size)
                    .offset(offset)
                )
            )
            if not rows:
                break
            for event in rows:
                checked += 1
                if not event.event_hash:
                    unhashed += 1
                    tip = tip  # tip unchanged across legacy null digests
                    continue
                expected = self.expected_hash(event)
                issues: list[str] = []
                if event.event_hash != expected:
                    issues.append("digest_mismatch")
                if tip is not None:
                    expected_prev = tip
                    actual_prev = event.prev_hash or ""
                    if actual_prev != expected_prev:
                        issues.append("prev_hash_gap")
                elif event.prev_hash:
                    # First hashed event should have empty/null prev unless seeded.
                    pass
                if issues:
                    sample = {
                        "id": str(event.id),
                        "created_at": event.created_at.isoformat() if event.created_at else None,
                        "action": event.action,
                        "issues": issues,
                        "stored_hash": event.event_hash,
                        "expected_hash": expected,
                        "stored_prev": event.prev_hash,
                        "expected_prev": tip,
                    }
                    if "digest_mismatch" in issues:
                        digest_count += 1
                        if len(broken) < 20:
                            broken.append(sample)
                    elif "prev_hash_gap" in issues:
                        # A valid digest with a missing link is a gap, not tampering.
                        gap_count += 1
                        if len(gaps) < 20:
                            gaps.append(sample)
                tip = event.event_hash
            offset += len(rows)
            if len(rows) < batch_size:
                break
        if checked == 0:
            status = "empty"
        elif digest_count:
            status = "broken"
        elif gap_count:
            status = "gapped"
        elif unhashed == checked:
            status = "unhashed"
        else:
            status = "ok"
        return {
            "status": status,
            "checked": checked,
            "unhashed": unhashed,
            "broken_count": digest_count,
            "broken": broken,
            "gap_count": gap_count,
            "gaps": gaps,
            "tip_hash": tip,
            "verified_at": dt.datetime.now(dt.UTC).isoformat(),
        }
