"""Language clarify must not loop after the user already confirmed a locale."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.w1_triage_graph import W1TriageGraph


class _Tools:
    async def call(self, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("tools should not be called in language-detect unit test")


def test_skip_language_clarify_after_user_choice() -> None:
    graph = W1TriageGraph(
        settings=SimpleNamespace(language_detection_enabled=True),
        models_config={"purposes": {}, "aliases": {}},
        red_flags_config={"rules": []},
        specialties={"general_medicine": {"en": "General"}},
        triage_prompt={"system": "x"},
        tool_client=_Tools(),  # type: ignore[arg-type]
        shortlist=lambda *_a, **_k: [],  # type: ignore[arg-type,return-value]
    )
    # Mixed hinglish normally needs clarify; skip flag must suppress it.
    state = graph._detect_language(
        {
            "text": "Mujhe bukhar hai and book doctor please",
            "locale": "hi-IN",
            "skip_language_clarify": True,
        }
    )
    assert state.get("language_needs_clarify") is False
    assert state.get("locale") == "hi-IN"


def test_language_clarify_still_fires_without_skip() -> None:
    graph = W1TriageGraph(
        settings=SimpleNamespace(language_detection_enabled=True),
        models_config={"purposes": {}, "aliases": {}},
        red_flags_config={"rules": []},
        specialties={"general_medicine": {"en": "General"}},
        triage_prompt={"system": "x"},
        tool_client=_Tools(),  # type: ignore[arg-type]
        shortlist=lambda *_a, **_k: [],  # type: ignore[arg-type,return-value]
    )
    state = graph._detect_language(
        {
            "text": "Mujhe bukhar hai and book doctor please",
            "locale": "en-IN",
            "skip_language_clarify": False,
        }
    )
    # Mixed latin hinglish is expected to ask for a language (product behaviour).
    assert "language_needs_clarify" in state
