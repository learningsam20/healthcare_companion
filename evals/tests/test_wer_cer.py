"""G-05 WER/CER helpers (unit math only; no authored clinical evidence)."""

from __future__ import annotations

from evals.harness.wer_cer import cer, wer


def test_wer_identical() -> None:
    assert wer("a b c", "a b c") == 0.0


def test_wer_one_substitution() -> None:
    assert abs(wer("take one tablet", "take one pill") - (1 / 3)) < 1e-9


def test_cer_identical_devanagari() -> None:
    assert cer("पैरासिटामोल", "पैरासिटामोल") == 0.0
