"""General conversation graph for non-workflow intents (clarify / other)."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sahyog_common.provenance import SourceRef, SourceType, resolve_sources

LANGUAGE_NAMES = {"en-IN": "English", "hi-IN": "Hindi", "mr-IN": "Marathi"}

from app.agents.llm_gateway import ExternalEgressBlocked, LlmGateway, LlmGatewayError
from app.agents.types import AgentTurnResult, IntentLabel
from app.core.tracing import trace_span


class ConversationState(TypedDict, total=False):
    text: str
    locale: str
    history: list[dict[str, str]]
    intent: IntentLabel
    memory_note: str | None
    reply: str
    sources: list[dict[str, Any]]
    model_alias: str | None
    prompt_tokens: int
    completion_tokens: int
    gateway_request_id: str | None
    error: str | None


class ConversationGraph:
    VERSION = "conversation.v1"

    def __init__(
        self,
        *,
        settings: Any,
        models_config: dict[str, Any],
        prompt: dict[str, Any],
        checkpointer: Any | None = None,
    ) -> None:
        self._gateway = LlmGateway(settings, models_config)
        self._prompt = prompt
        self._checkpointer = checkpointer
        self._graph = self._build()

    async def _reply(self, state: ConversationState) -> ConversationState:
        with trace_span("conversation.reply", {"intent": state.get("intent")}):
            if state.get("intent") == "clarify":
                return {
                    **state,
                    "reply": (
                        "I can help with booking a doctor, questions about your uploaded records, "
                        "or general clinic guidance. Which of those do you need?"
                    ),
                    "sources": [],
                    "model_alias": None,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "error": None,
                }
            language = state.get("locale") or "en-IN"
            messages = [
                {"role": "system", "content": str(self._prompt.get("system", ""))},
                {
                    "role": "system",
                    "content": (
                        f"Reply in {LANGUAGE_NAMES.get(language, 'English')}. "
                        "Do not diagnose, prescribe, or invent clinic data. "
                        "If the user needs booking or records, say so briefly."
                    ),
                },
            ]
            if state.get("memory_note"):
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"{state['memory_note']}. Use only for tone/routing; "
                            "never invent clinical facts from preferences."
                        ),
                    }
                )
            for item in (state.get("history") or [])[-12:]:
                if item.get("role") in {"user", "assistant"}:
                    messages.append(
                        {"role": item["role"], "content": item.get("content", "")[:4000]}
                    )
            try:
                result = await self._gateway.complete(
                    purpose="conversation", messages=messages
                )
            except ExternalEgressBlocked:
                return {
                    **state,
                    "error": "egress_blocked",
                    "reply": "The assistant route is blocked by privacy policy right now.",
                }
            except LlmGatewayError:
                return {
                    **state,
                    "error": "gateway_unavailable",
                    "reply": "The assistant is temporarily unavailable. Your message was saved.",
                }
            sources = [
                s.model_dump(mode="json")
                for s in resolve_sources(
                    [
                        SourceRef(
                            id=f"model:{result.model_alias}",
                            type=SourceType.GENERAL,
                            title="General assistant response — not clinical evidence",
                            locator=f"model:{result.model_alias}",
                        )
                    ],
                    current_patient_id=None,
                )
            ]
            return {
                **state,
                "reply": result.content,
                "sources": sources,
                "model_alias": result.model_alias,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "gateway_request_id": result.gateway_request_id,
                "error": None,
            }

    def _build(self) -> Any:
        graph: StateGraph[ConversationState] = StateGraph(ConversationState)
        graph.add_node("reply", self._reply)
        graph.add_edge(START, "reply")
        graph.add_edge("reply", END)
        from app.agents.checkpointer import compile_graph

        return compile_graph(graph, self._checkpointer)

    async def run(
        self,
        *,
        text: str,
        locale: str,
        history: list[dict[str, str]],
        intent: IntentLabel,
        memory_note: str | None = None,
    ) -> AgentTurnResult:
        from app.agents.checkpointer import invoke_config

        result = await self._graph.ainvoke(
            {
                "text": text,
                "locale": locale,
                "history": history,
                "intent": intent,
                "memory_note": memory_note,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            },
            config=invoke_config(checkpoint_ns="conversation"),
        )
        return AgentTurnResult(
            content=str(result.get("reply") or ""),
            intent=intent,
            graph=self.VERSION,
            sources=list(result.get("sources") or []),
            model_alias=result.get("model_alias"),
            prompt_tokens=int(result.get("prompt_tokens") or 0),
            completion_tokens=int(result.get("completion_tokens") or 0),
            gateway_request_id=result.get("gateway_request_id"),
            purpose="conversation",
            metadata={"error": result.get("error")},
        )
