from __future__ import annotations

import datetime as dt
import uuid

from sahyog_common.provenance import (
    SourceRef,
    SourceStatus,
    SourceType,
    forbidden_or_missing,
    has_usable_evidence,
    resolve_sources,
)

PATIENT = uuid.UUID("6f3f7f5e-0d2a-4f45-9a65-2f8f6f2f0c11")
OTHER = uuid.UUID("11111111-2222-3333-4444-555555555555")
NOW = dt.datetime(2026, 10, 25, tzinfo=dt.UTC)


def test_document_with_locator_resolves() -> None:
    ref = SourceRef(
        type=SourceType.DOCUMENT,
        id="doc-1",
        title="Discharge summary",
        patient_id=PATIENT,
        locator="report.pdf#page=2",
        observed_at=NOW,
    )
    resolved = resolve_sources([ref], current_patient_id=PATIENT, now=NOW)[0]
    assert resolved.status is SourceStatus.RESOLVED


def test_document_without_locator_is_missing() -> None:
    ref = SourceRef(
        type=SourceType.DOCUMENT,
        id="doc-1",
        title="Report",
        patient_id=PATIENT,
        observed_at=NOW,
    )
    resolved = resolve_sources([ref], current_patient_id=PATIENT, now=NOW)[0]
    assert resolved.status is SourceStatus.MISSING


def test_document_for_another_patient_is_forbidden() -> None:
    ref = SourceRef(
        type=SourceType.DOCUMENT,
        id="doc-2",
        title="Discharge summary",
        patient_id=OTHER,
        locator="report.pdf#page=1",
        observed_at=NOW,
    )
    resolved = resolve_sources([ref], current_patient_id=PATIENT, now=NOW)[0]
    assert resolved.status is SourceStatus.FORBIDDEN
    assert not has_usable_evidence([resolved])
    assert forbidden_or_missing([resolved])


def test_stale_observation_is_marked_stale() -> None:
    ref = SourceRef(
        type=SourceType.TOOL,
        id="tool-result-1",
        title="Records search",
        patient_id=PATIENT,
        locator="mcp:records:search",
        observed_at=NOW - dt.timedelta(days=5),
    )
    resolved = resolve_sources(
        [ref], current_patient_id=PATIENT, now=NOW, stale_after=dt.timedelta(days=1)
    )[0]
    assert resolved.status is SourceStatus.STALE


def test_memory_and_general_are_never_clinical_evidence() -> None:
    refs = [
        SourceRef(
            type=SourceType.MEMORY,
            id="mem-1",
            title="Language preference",
            locator="preference:language",
        ),
        SourceRef(type=SourceType.GENERAL, id="general-1", title="General guidance"),
    ]
    resolved = resolve_sources(refs, current_patient_id=PATIENT, now=NOW)
    assert all(ref.status is SourceStatus.RESOLVED for ref in resolved)
    assert not has_usable_evidence(resolved)


def test_duplicate_sources_are_collapsed() -> None:
    ref = SourceRef(
        type=SourceType.RULE,
        id="RF-CHEST-PAIN",
        title="Chest pain rule",
        locator="config/red_flags.yaml",
    )
    resolved = resolve_sources([ref, ref], current_patient_id=PATIENT, now=NOW)
    assert len(resolved) == 1


def test_forbidden_source_breaks_usable_evidence() -> None:
    good = SourceRef(
        type=SourceType.DOCUMENT,
        id="doc-3",
        title="Lab report",
        patient_id=PATIENT,
        locator="report.pdf#page=1",
        observed_at=NOW,
    )
    bad = SourceRef(
        type=SourceType.DOCUMENT,
        id="doc-4",
        title="Lab report",
        patient_id=OTHER,
        locator="report.pdf#page=1",
        observed_at=NOW,
    )
    resolved = resolve_sources([good, bad], current_patient_id=PATIENT, now=NOW)
    assert has_usable_evidence(resolved)
    assert [ref.id for ref in forbidden_or_missing(resolved)] == ["doc-4"]
