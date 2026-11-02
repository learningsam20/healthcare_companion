"""G-47: grounded-ask stream drips tokens after retrieve; foreign citations replace the draft."""

from __future__ import annotations

import uuid
from typing import Any, AsyncIterator
from unittest.mock import MagicMock

import pytest

from app.agents.llm_gateway import LlmResult
from app.agents.types import AgentTurnResult
from app.agents.w2_ask_graph import W2AskGraph

FOREIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class _FakeGateway:
    async def stream(self, **kwargs: Any) -> AsyncIterator[str | LlmResult]:
        draft = f"Haemoglobin is normal [{FOREIGN_ID}]."
        yield "Haemoglobin is "
        yield f"normal [{FOREIGN_ID}]."
        yield LlmResult(
            content=draft,
            model_alias="test-model",
            prompt_tokens=10,
            completion_tokens=5,
            gateway_request_id="gw-test",
        )


@pytest.mark.asyncio
async def test_stream_replaces_foreign_citation_draft_after_drip() -> None:
    evidence_id = "11111111-2222-4333-8444-555555555555"

    async def retrieve(
        _q: str, _pid: uuid.UUID, *, top_k: int = 6
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        from sahyog_common.provenance import SourceRef, SourceType

        _ = top_k
        return (
            [
                {
                    "id": evidence_id,
                    "title": "Labs",
                    "page": 1,
                    "content": "Haemoglobin 12.1",
                    "score": 0.9,
                },
                {
                    "id": "22222222-3333-4444-8555-666666666666",
                    "title": "Labs",
                    "page": 2,
                    "content": "Platelets normal",
                    "score": 0.8,
                },
            ],
            [
                SourceRef(
                    id=evidence_id,
                    type=SourceType.DOCUMENT,
                    title="Labs",
                    locator="p1",
                )
            ],
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
    graph._gateway = _FakeGateway()  # type: ignore[method-assign]

    patient_id = uuid.uuid4()
    pieces: list[str | AgentTurnResult] = []
    async for item in graph.stream(
        question="What is my haemoglobin?",
        locale="en-IN",
        patient_id=patient_id,
    ):
        pieces.append(item)

    tokens = [p for p in pieces if isinstance(p, str)]
    finals = [p for p in pieces if isinstance(p, AgentTurnResult)]
    assert tokens, "expected token drip after retrieve"
    assert len(finals) == 1
    assert finals[0].metadata.get("status") == "citation_failed"
    assert finals[0].metadata.get("grounded") is False
    assert "could not verify citations" in (finals[0].content or "").lower()
    assert FOREIGN_ID not in (finals[0].content or "")
