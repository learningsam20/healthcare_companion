"""G-06/G-07 contact re-verification helper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scripts.contact_reverification_scan import due_for_reverify


def test_due_when_older_than_max_days() -> None:
    now = datetime(2026, 10, 31, tzinfo=UTC)
    old = now - timedelta(days=200)
    assert due_for_reverify(verified_at=old, verified=True, now=now, max_days=180) is True


def test_not_due_when_recent() -> None:
    now = datetime(2026, 10, 31, tzinfo=UTC)
    recent = now - timedelta(days=30)
    assert due_for_reverify(verified_at=recent, verified=True, now=now, max_days=180) is False


def test_unverified_never_due() -> None:
    now = datetime(2026, 10, 31, tzinfo=UTC)
    assert due_for_reverify(verified_at=None, verified=False, now=now, max_days=180) is False
