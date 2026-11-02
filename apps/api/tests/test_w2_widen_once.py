"""W2 pack behaviour: weak context widens retrieval once, then refuses if still weak."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agents.w2_ask_graph import W2AskGraph


@pytest.mark.asyncio
async def test_weak_context_widens_once_then_answers() -> None:
    calls: list[int] = []
    strong_id = "11111111-2222-4333-8444-555555555555"

    async def retrieve(
        _q: str, _pid: uuid.UUID, *, top_k: int = 6
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        from sahyog_common.provenance import SourceRef, SourceType

        calls.append(top_k)
        if top_k <= 6:
            # One weak hit — forces widen.
            return (
                [
                    {
                        "id": "00000000-0000-4000-8000-000000000001",
                        "title": "Noise",
                        "page": 1,
                        "content": "unrelated text",
                        "score": 0.1,
                    }
                ],
                [],
            )
        return (
            [
                {
                    "id": strong_id,
                    "title": "Labs",
                    "page": 1,
                    "content": "Haemoglobin 12.1",
                    "score": 0.82,
                },
                {
                    "id": "22222222-3333-4444-8555-666666666666",
                    "title": "Labs",
                    "page": 2,
                    "content": "Platelets normal",
                    "score": 0.71,
                },
            ],
            [
                SourceRef(
                    id=strong_id,
                    type=SourceType.DOCUMENT,
                    title="Labs",
                    locator="p1",
                )
            ],
        )

    class _Gateway:
        async def complete(self, **kwargs: Any) -> Any:
            from app.agents.llm_gateway import LlmResult

            return LlmResult(
                content=f"Haemoglobin is 12.1 [{strong_id}].",
                model_alias="test",
                prompt_tokens=1,
                completion_tokens=1,
                gateway_request_id="g",
            )

    settings = MagicMock()
    settings.external_egress_enabled = False
    settings.litellm_base_url = "http://localhost"
    settings.litellm_master_key = ""
    settings.pii_service_url = ""
    graph = W2AskGraph(
        settings=settings,
        models_config={"aliases": {}, "purposes": {"rag_answer": {"alias": "x"}}},
        prompt={"system": "Answer only from excerpts."},
        retrieve=retrieve,
    )
    graph._gateway = _Gateway()  # type: ignore[method-assign]

    result = await graph.run(
        question="What is my haemoglobin?",
        locale="en-IN",
        patient_id=uuid.uuid4(),
    )
    assert calls == [6, 12]
    assert result.metadata.get("widened") is True
    assert result.metadata.get("context_grade") == "ok"
    assert result.metadata.get("status") == "answered"
    assert "12.1" in (result.content or "")


@pytest.mark.asyncio
async def test_weak_context_after_widen_refuses() -> None:
    calls: list[int] = []

    async def retrieve(
        _q: str, _pid: uuid.UUID, *, top_k: int = 6
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        calls.append(top_k)
        return (
            [
                {
                    "id": "00000000-0000-4000-8000-000000000099",
                    "title": "Noise",
                    "page": 1,
                    "content": "still weak",
                    "score": 0.05,
                }
            ],
            [],
        )

    settings = MagicMock()
    settings.external_egress_enabled = False
    settings.litellm_base_url = "http://localhost"
    settings.litellm_master_key = ""
    settings.pii_service_url = ""
    graph = W2AskGraph(
        settings=settings,
        models_config={"aliases": {}, "purposes": {"rag_answer": {"alias": "x"}}},
        prompt={"system": "Answer only from excerpts."},
        retrieve=retrieve,
    )

    result = await graph.run(
        question="What is my haemoglobin?",
        locale="en-IN",
        patient_id=uuid.uuid4(),
    )
    assert calls == [6, 12]
    assert result.metadata.get("widened") is True
    assert result.metadata.get("status") == "no_evidence"
    assert "does not contain a clear answer" in (result.content or "").lower()
