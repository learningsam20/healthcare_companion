"""Unit coverage for audit hash-chain verification."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.audit import AuditRepository, _canonical_payload
from app.scheduler import WorkerSettings as SchedulerWorkerSettings


def test_scheduler_registers_audit_verify_cron() -> None:
    names = {fn.__name__ for fn in SchedulerWorkerSettings.functions}
    assert "audit_verify_job" in names
    cron_names = {job.coroutine.__name__ for job in SchedulerWorkerSettings.cron_jobs}
    assert "audit_verify_job" in cron_names


def test_expected_hash_matches_append_digest() -> None:
    session = MagicMock()
    session.info = {}
    repo = AuditRepository(session)
    event = repo.append(
        actor_subject="user:a",
        actor_role="admin",
        action="test.action",
        resource_type="test",
        resource_id="1",
        metadata={"k": "v"},
    )
    assert event.event_hash == AuditRepository.expected_hash(event)
    assert event.prev_hash is None or event.prev_hash == ""


@pytest.mark.asyncio
async def test_verify_chain_detects_digest_mismatch() -> None:
    good = SimpleNamespace(
        id=uuid.uuid4(),
        actor_subject="user:a",
        actor_role="admin",
        action="ok",
        resource_type="x",
        resource_id="1",
        patient_id=None,
        consent_id=None,
        trace_id=None,
        event_metadata={},
        prev_hash=None,
        event_hash=None,
        created_at=None,
    )
    good.event_hash = AuditRepository.expected_hash(good)  # type: ignore[arg-type]

    bad = SimpleNamespace(
        id=uuid.uuid4(),
        actor_subject="user:b",
        actor_role="admin",
        action="tampered",
        resource_type="x",
        resource_id="2",
        patient_id=None,
        consent_id=None,
        trace_id=None,
        event_metadata={},
        prev_hash=good.event_hash,
        event_hash="0" * 64,
        created_at=None,
    )

    session = MagicMock()
    session.info = {}

    async def _scalars(stmt: Any) -> Any:  # noqa: ARG001
        # First page returns both rows; second empty.
        if not hasattr(_scalars, "called"):
            _scalars.called = True  # type: ignore[attr-defined]
            return [good, bad]
        return []

    session.scalars = AsyncMock(side_effect=_scalars)
    repo = AuditRepository(session)
    result = await repo.verify_chain(batch_size=10)
    assert result["status"] == "broken"
    assert result["checked"] == 2
    assert result["broken_count"] >= 1
    assert any("digest_mismatch" in row["issues"] for row in result["broken"])


@pytest.mark.asyncio
async def test_verify_chain_reports_prev_hash_gap_without_calling_it_broken() -> None:
    first = SimpleNamespace(
        id=uuid.uuid4(),
        actor_subject="user:a",
        actor_role="admin",
        action="ok",
        resource_type="x",
        resource_id="1",
        patient_id=None,
        consent_id=None,
        trace_id=None,
        event_metadata={},
        prev_hash=None,
        event_hash=None,
        created_at=None,
    )
    first.event_hash = AuditRepository.expected_hash(first)  # type: ignore[arg-type]
    second = SimpleNamespace(
        id=uuid.uuid4(),
        actor_subject="user:b",
        actor_role="admin",
        action="patients.listed",
        resource_type="x",
        resource_id="2",
        patient_id=None,
        consent_id=None,
        trace_id=None,
        event_metadata={},
        prev_hash=None,
        event_hash=None,
        created_at=None,
    )
    second.event_hash = AuditRepository.expected_hash(second)  # type: ignore[arg-type]

    session = MagicMock()
    session.info = {}
    pages = [[first, second], []]

    async def _scalars(stmt: Any) -> Any:  # noqa: ARG001
        return pages.pop(0) if pages else []

    session.scalars = AsyncMock(side_effect=_scalars)
    result = await AuditRepository(session).verify_chain(batch_size=10)
    assert result["status"] == "gapped"
    assert result["broken_count"] == 0
    assert result["gap_count"] == 1
    assert result["gaps"][0]["issues"] == ["prev_hash_gap"]
    assert result["gaps"][0]["stored_hash"] == result["gaps"][0]["expected_hash"]


def test_canonical_payload_stable() -> None:
    a = _canonical_payload(
        actor_subject="a",
        actor_role="admin",
        action="x",
        resource_type="y",
        resource_id=None,
        patient_id=None,
        consent_id=None,
        trace_id=None,
        metadata={"b": 1, "a": 2},
        prev_hash=None,
    )
    b = _canonical_payload(
        actor_subject="a",
        actor_role="admin",
        action="x",
        resource_type="y",
        resource_id=None,
        patient_id=None,
        consent_id=None,
        trace_id=None,
        metadata={"a": 2, "b": 1},
        prev_hash="",
    )
    assert a == b
