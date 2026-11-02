"""W2 ask graph: scope → retrieve → grade/widen once → answer → validate citations.

Ingest stays in the worker. This graph only answers from patient-scoped evidence.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Awaitable
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from sahyog_common.provenance import SourceRef, resolve_sources

from app.agents.llm_gateway import LlmGateway, LlmGatewayError, LlmResult
from app.agents.types import AgentTurnResult
from app.core.tracing import trace_span

DEFAULT_TOP_K = 6
WIDEN_TOP_K = 12
WEAK_MIN_HITS = 2
WEAK_MIN_BEST_SCORE = 0.25


class RetrieveFn(Protocol):
    async def __call__(
        self,
        question: str,
        patient_id: uuid.UUID,
        *,
        top_k: int = DEFAULT_TOP_K,
    ) -> tuple[list[dict[str, Any]], list[SourceRef]]: ...


class W2State(TypedDict, total=False):
    question: str
    locale: str
    patient_id: uuid.UUID | None
    evidence: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    draft: str
    reply: str
    status: str
    grounded: bool
    model_alias: str | None
    prompt_tokens: int
    completion_tokens: int
    gateway_request_id: str | None
    error: str | None
    retrieve_top_k: int
    widened: bool
    context_grade: str
    foreign_citation_ids: list[str]
    allowed_citation_ids: list[str]


def _best_score(evidence: list[dict[str, Any]]) -> float:
    scores = [float(item.get("score") or 0.0) for item in evidence]
    return max(scores) if scores else 0.0


def _is_weak(evidence: list[dict[str, Any]]) -> bool:
    if not evidence:
        return True
    if len(evidence) < WEAK_MIN_HITS:
        return True
    # Scores are optional (unit doubles may omit them); length alone then decides.
    if any("score" in item for item in evidence):
        return _best_score(evidence) < WEAK_MIN_BEST_SCORE
    return False


class W2AskGraph:
    VERSION = "w2_ask.v2"

    def __init__(
        self,
        *,
        settings: Any,
        models_config: dict[str, Any],
        prompt: dict[str, Any],
        retrieve: RetrieveFn,
        checkpointer: Any | None = None,
    ) -> None:
        self._gateway = LlmGateway(settings, models_config)
        self._prompt = prompt
        self._retrieve = retrieve
        self._checkpointer = checkpointer
        self._graph = self._build()

    def _scope(self, state: W2State) -> W2State:
        with trace_span("w2.scope", {}):
            q = state["question"].casefold()
            if any(
                term in q
                for term in ("diagnose", "diagnosis", "prescribe", "increase dose", "stop taking")
            ):
                return {
                    **state,
                    "status": "refused",
                    "grounded": True,
                    "reply": (
                        "I can't diagnose, change a dose, or tell you to stop a medicine. "
                        "Please ask your doctor. I can help find what is written in your record."
                    ),
                    "sources": [],
                    "error": None,
                }
            if state.get("patient_id") is None:
                return {
                    **state,
                    "status": "no_patient",
                    "grounded": True,
                    "reply": (
                        "No patient record is linked to this chat. Link your account or activate "
                        "a care context, then ask again."
                    ),
                    "sources": [],
                    "error": None,
                }
            return {
                **state,
                "status": "scoped",
                "error": None,
                "retrieve_top_k": int(state.get("retrieve_top_k") or DEFAULT_TOP_K),
                "widened": False,
            }

    async def _retrieve_node(self, state: W2State) -> W2State:
        if state.get("status") not in {None, "scoped", "widen"}:
            return state
        top_k = int(state.get("retrieve_top_k") or DEFAULT_TOP_K)
        with trace_span("w2.retrieve", {"top_k": top_k, "widened": bool(state.get("widened"))}):
            patient_id = state["patient_id"]
            assert patient_id is not None
            evidence, source_refs = await self._retrieve(
                state["question"], patient_id, top_k=top_k
            )
            sources = [
                s.model_dump(mode="json")
                for s in resolve_sources(source_refs, current_patient_id=patient_id)
            ]
            if not evidence:
                return {
                    **state,
                    "evidence": [],
                    "sources": [],
                    "status": "no_evidence",
                    "grounded": True,
                    "context_grade": "empty",
                    "reply": (
                        "I could not find this in the linked record. If you expected a report here, "
                        "ask the clinic to upload it, or ask your doctor."
                    ),
                }
            return {
                **state,
                "evidence": evidence,
                "sources": sources,
                "status": "retrieved",
            }

    def _grade_context(self, state: W2State) -> W2State:
        if state.get("status") != "retrieved":
            return state
        evidence = list(state.get("evidence") or [])
        weak = _is_weak(evidence)
        with trace_span(
            "w2.grade_context",
            {
                "hits": len(evidence),
                "best_score": round(_best_score(evidence), 4),
                "weak": weak,
                "widened": bool(state.get("widened")),
            },
        ):
            if weak and not state.get("widened"):
                return {
                    **state,
                    "status": "widen",
                    "widened": True,
                    "retrieve_top_k": WIDEN_TOP_K,
                    "context_grade": "weak",
                }
            if weak:
                return {
                    **state,
                    "evidence": [],
                    "sources": [],
                    "status": "no_evidence",
                    "grounded": True,
                    "context_grade": "weak_after_widen",
                    "reply": (
                        "The record does not contain a clear answer to that question. "
                        "Please ask your doctor, or upload the relevant report if it is missing."
                    ),
                }
            return {**state, "status": "retrieved", "context_grade": "ok"}

    async def _answer(self, state: W2State) -> W2State:
        if state.get("status") != "retrieved":
            return state
        with trace_span("w2.answer", {"evidence": len(state.get("evidence") or [])}):
            excerpts = "\n\n".join(
                f"[{item['id']}] {item.get('title', 'document')} "
                f"(page {item.get('page') or 'n/a'}):\n{item['content']}"
                for item in state["evidence"]
            )
            messages = [
                {"role": "system", "content": str(self._prompt.get("system", ""))},
                {
                    "role": "user",
                    "content": (
                        f"Language: {state.get('locale')}\n"
                        f"Question: {state['question']}\n\n"
                        f"Patient-scoped record excerpts:\n{excerpts}"
                    ),
                },
            ]
            try:
                result = await self._gateway.complete(
                    purpose="rag_answer",
                    messages=messages,
                    max_tokens=800,
                    temperature=0.1,
                )
            except LlmGatewayError:
                return {
                    **state,
                    "status": "model_unavailable",
                    "grounded": True,
                    "reply": (
                        "The answer model is unavailable. Your question was not answered from "
                        "general knowledge. Please try again shortly or ask your doctor."
                    ),
                    "model_alias": None,
                }
            return {
                **state,
                "draft": result.content,
                "model_alias": result.model_alias,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "gateway_request_id": result.gateway_request_id,
                "status": "drafted",
            }

    def _validate(self, state: W2State) -> W2State:
        if state.get("status") != "drafted":
            return state
        with trace_span("w2.validate", {}):
            draft = state.get("draft") or ""
            allowed_ids = {str(item["id"]) for item in state.get("evidence") or []}
            cited = set(re.findall(r"\[([0-9a-fA-F-]{36})\]", draft))
            foreign = cited - allowed_ids
            if foreign:
                return {
                    **state,
                    "status": "citation_failed",
                    "grounded": False,
                    "foreign_citation_ids": sorted(foreign),
                    "allowed_citation_ids": sorted(allowed_ids),
                    "reply": (
                        "I could not verify citations against your record, so I will not show that "
                        "draft. Please rephrase the question or ask your doctor."
                    ),
                    "sources": [],
                }
            return {
                **state,
                "status": "answered",
                "grounded": True,
                "reply": draft,
            }

    def _build(self) -> Any:
        graph: StateGraph[W2State] = StateGraph(W2State)
        graph.add_node("scope", self._scope)
        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("grade", self._grade_context)
        graph.add_node("answer", self._answer)
        graph.add_node("validate", self._validate)
        graph.add_edge(START, "scope")
        graph.add_conditional_edges(
            "scope",
            lambda s: "end" if s.get("status") in {"refused", "no_patient"} else "retrieve",
            {"end": END, "retrieve": "retrieve"},
        )
        graph.add_conditional_edges(
            "retrieve",
            lambda s: "end" if s.get("status") == "no_evidence" else "grade",
            {"end": END, "grade": "grade"},
        )
        graph.add_conditional_edges(
            "grade",
            lambda s: (
                "end"
                if s.get("status") == "no_evidence"
                else "retrieve"
                if s.get("status") == "widen"
                else "answer"
            ),
            {"end": END, "retrieve": "retrieve", "answer": "answer"},
        )
        graph.add_edge("answer", "validate")
        graph.add_edge("validate", END)
        from app.agents.checkpointer import compile_graph

        return compile_graph(graph, self._checkpointer)

    def _to_result(self, result: dict[str, Any], *, patient_id: uuid.UUID | None) -> AgentTurnResult:
        return AgentTurnResult(
            content=str(result.get("reply") or "No answer produced."),
            intent="records_question",
            graph=self.VERSION,
            sources=list(result.get("sources") or []),
            model_alias=result.get("model_alias"),
            prompt_tokens=int(result.get("prompt_tokens") or 0),
            completion_tokens=int(result.get("completion_tokens") or 0),
            gateway_request_id=result.get("gateway_request_id"),
            purpose="rag_answer",
            patient_id=patient_id,
            metadata={
                "status": result.get("status"),
                "grounded": result.get("grounded", True),
                "foreign_citation_ids": result.get("foreign_citation_ids") or [],
                "allowed_citation_ids": result.get("allowed_citation_ids") or [],
                "widened": bool(result.get("widened")),
                "context_grade": result.get("context_grade"),
            },
        )

    async def _prepare_evidence(self, state: W2State) -> W2State:
        """Shared retrieve → grade → optional widen path for run/stream."""
        state = await self._retrieve_node(state)
        if state.get("status") != "retrieved":
            return state
        state = self._grade_context(state)
        if state.get("status") == "widen":
            state = await self._retrieve_node(state)
            if state.get("status") != "retrieved":
                return state
            state = self._grade_context(state)
        return state

    async def run(
        self,
        *,
        question: str,
        locale: str,
        patient_id: uuid.UUID | None,
    ) -> AgentTurnResult:
        state: W2State = {
            "question": question,
            "locale": locale,
            "patient_id": patient_id,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
        from app.agents.checkpointer import invoke_config

        result = await self._graph.ainvoke(
            state,
            config=invoke_config(
                thread_id=str(patient_id) if patient_id else None,
                checkpoint_ns="w2_ask",
            ),
        )
        return self._to_result(result, patient_id=patient_id)

    async def stream(
        self,
        *,
        question: str,
        locale: str,
        patient_id: uuid.UUID | None,
    ) -> AsyncIterator[str | AgentTurnResult]:
        """Retrieve + grade/widen + cite-check; stream tokens only after evidence exists."""
        state: W2State = {
            "question": question,
            "locale": locale,
            "patient_id": patient_id,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
        state = self._scope(state)
        if state.get("status") in {"refused", "no_patient"}:
            yield self._to_result(state, patient_id=patient_id)
            return
        state = await self._prepare_evidence(state)
        if state.get("status") != "retrieved":
            yield self._to_result(state, patient_id=patient_id)
            return

        excerpts = "\n\n".join(
            f"[{item['id']}] {item.get('title', 'document')} "
            f"(page {item.get('page') or 'n/a'}):\n{item['content']}"
            for item in state["evidence"]
        )
        messages = [
            {"role": "system", "content": str(self._prompt.get("system", ""))},
            {
                "role": "user",
                "content": (
                    f"Language: {locale}\n"
                    f"Question: {question}\n\n"
                    f"Patient-scoped record excerpts:\n{excerpts}"
                ),
            },
        ]
        draft = ""
        try:
            async for piece in self._gateway.stream(
                purpose="rag_answer",
                messages=messages,
                max_tokens=800,
                temperature=0.1,
            ):
                if isinstance(piece, LlmResult):
                    draft = piece.content or draft
                    state = {
                        **state,
                        "draft": draft,
                        "model_alias": piece.model_alias,
                        "prompt_tokens": piece.prompt_tokens,
                        "completion_tokens": piece.completion_tokens,
                        "gateway_request_id": piece.gateway_request_id,
                        "status": "drafted",
                    }
                else:
                    draft += piece
                    yield piece
        except LlmGatewayError:
            state = {
                **state,
                "status": "model_unavailable",
                "grounded": True,
                "reply": (
                    "The answer model is unavailable. Your question was not answered from "
                    "general knowledge. Please try again shortly or ask your doctor."
                ),
                "model_alias": None,
            }
            yield self._to_result(state, patient_id=patient_id)
            return

        state = {**state, "draft": draft, "status": "drafted"}
        state = self._validate(state)
        yield self._to_result(state, patient_id=patient_id)
