"""Schedule search date tokens used by appointment grid `q`."""

from __future__ import annotations

import datetime as dt

from app.repositories.scheduling import parse_schedule_query_date


def test_parse_iso_and_day_first_dates() -> None:
    assert parse_schedule_query_date("2026-11-04") == dt.date(2026, 11, 4)
    assert parse_schedule_query_date("04/11/2026") == dt.date(2026, 11, 4)
    assert parse_schedule_query_date("04-11-2026") == dt.date(2026, 11, 4)
    assert parse_schedule_query_date("4 Nov 2026") == dt.date(2026, 11, 4)


def test_parse_rejects_partial_or_names() -> None:
    assert parse_schedule_query_date("Priya") is None
    assert parse_schedule_query_date("11") is None
    assert parse_schedule_query_date("") is None
