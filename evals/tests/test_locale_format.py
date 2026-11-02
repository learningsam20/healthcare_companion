"""G-20 locale format harness."""

from __future__ import annotations

from evals.harness.locale_format import format_currency_inr, format_date_iso


def test_currency_has_rupee() -> None:
    assert "₹" in format_currency_inr(1500.5, "hi-IN")


def test_date_en_in_order() -> None:
    assert format_date_iso("2026-10-31", "en-IN") == "31/10/2026"
