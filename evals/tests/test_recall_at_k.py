"""recall@k harness on mixed-script fixtures (G-03)."""

from __future__ import annotations

from evals.harness.recall_at_k import load_fixture, recall_at_k
from evals.harness.recall_at_k import DEFAULT_FIXTURE


def test_recall_perfect() -> None:
    assert recall_at_k(["a", "b"], ["a", "b", "c"], 2) == 1.0


def test_recall_partial() -> None:
    assert recall_at_k(["a", "b"], ["a", "c"], 2) == 0.5


def test_fixture_mean_positive() -> None:
    fixture = load_fixture(DEFAULT_FIXTURE)
    scores = [
        recall_at_k(
            list(case["relevant_chunk_ids"]),
            list(case["retrieved_chunk_ids"]),
            5,
        )
        for case in fixture["cases"]
    ]
    assert sum(scores) / len(scores) >= 0.8
