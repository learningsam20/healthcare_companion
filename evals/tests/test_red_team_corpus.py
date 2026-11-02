"""Red-team corpus loads with expected refusals (G-10)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "evals" / "red_team" / "cross_patient_idor.json"


def test_red_team_corpus_shape() -> None:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert payload["contains_phi"] is False
    cases = payload["cases"]
    assert len(cases) >= 5
    for case in cases:
        assert case["expected"] in {"refuse", "refuse_or_redact"}
        assert case["reason"]
        assert case["prompt"]
