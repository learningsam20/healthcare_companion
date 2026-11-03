"""MemoryFacade recall provenance and attribution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.memory.backends import DurableHit
from app.modules.memory.service import (
    MemoryFacade,
    append_attribution,
    attribution_footer,
    conversation_sources,
    memory_sources,
)


def test_memory_sources_use_m_locators() -> None:
    hits = [
        DurableHit(
            id="1",
            text="Preference preferred_clinic: BANER",
            kind="preference",
            metadata={"key": "preferred_clinic"},
        )
    ]
    sources = memory_sources(hits)
    assert sources[0]["type"] == "memory"
    assert sources[0]["locator"] == "M1"
    assert "BANER" in (sources[0].get("snippet") or "")
    assert sources[0]["metadata"]["not_clinical_evidence"] == "true"


def test_conversation_sources_cite_history() -> None:
    history = [
        {"role": "user", "content": "I prefer Baner"},
        {"role": "assistant", "content": "Noted"},
        {"role": "user", "content": "Book again"},
    ]
    sources = conversation_sources(history)
    assert len(sources) == 1
    assert sources[0]["type"] == "conversation"
    assert sources[0]["locator"] == "C1"


def test_attribution_footer_and_append() -> None:
    hits = [
        DurableHit(id="1", text="Preference preferred_clinic: BANER", kind="preference", metadata={"key": "preferred_clinic"})
    ]
    footer = attribution_footer(hits, history_cited=True)
    assert footer is not None
    assert "[M1]" in footer
    assert "[C1]" in footer
    body = append_attribution("Sure, Baner works.", footer)
    assert body.startswith("Sure, Baner works.")
    assert "Based on remembered context" in body


@pytest.mark.asyncio
async def test_facade_disabled_still_cites_history() -> None:
    features = SimpleNamespace(enabled=lambda _key: False)
    services = SimpleNamespace(features=features, settings=SimpleNamespace(memory_backend="mem0"))
    facade = MemoryFacade(services, session=SimpleNamespace(), backend=SimpleNamespace())
    bundle = await facade.recall(
        subject="u1",
        query="hello",
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    assert bundle.memory_note is None
    assert any(s["type"] == "conversation" for s in bundle.sources)
