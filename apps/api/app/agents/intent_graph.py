"""Intent router graph.

Safety first: deterministic emergency/red-flag scan, then MCP classify_intent.
Routing is advisory only — W1/W2 still run their own gates.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sahyog_common.context import ExecutionContext
from sahyog_common.red_flags import detect_red_flags

from app.agents.mcp_client import McpToolClient, ToolUnavailable
from app.agents.types import IntentLabel
from app.core.tracing import trace_span

INTENT_MAP: dict[str, IntentLabel] = {
    "emergency": "emergency",
    "book_appointment": "book_appointment",
    "records_question": "records_question",
    "medication_question": "medication_question",
    "nursing_summary": "nursing_summary",
    "appointment_help": "appointment_help",
    "other": "other",
}


class IntentState(TypedDict, total=False):
    text: str
    locale: str
    tool_context: ExecutionContext
    red_flags: list[dict[str, Any]]
    emergency: bool
    intent: IntentLabel
    confidence: float
    engine: str
    clarify: bool
    error: str | None


class IntentGraph:
    VERSION = "intent.v1"

    def __init__(
        self,
        *,
        red_flags_config: dict[str, Any],
        tool_client: McpToolClient,
        confidence_threshold: float = 0.55,
        checkpointer: Any | None = None,
    ) -> None:
        self._red_flags = red_flags_config
        self._tools = tool_client
        self._threshold = confidence_threshold
        self._checkpointer = checkpointer
        self._graph = self._build()

    async def _emergency_scan(self, state: IntentState) -> IntentState:
        with trace_span("intent.emergency_scan", {"locale": state.get("locale")}):
            await self._clinical_red_flags(state)
            try:
                matches = detect_red_flags(
                    state["text"], self._red_flags, state.get("locale") or "en-IN"
                )
            except Exception:  # noqa: BLE001 - fail closed
                return {
                    **state,
                    "emergency": True,
                    "intent": "emergency",
                    "confidence": 1.0,
                    "engine": "red_flag_fail_closed",
                    "red_flags": [{"rule_id": "red_flag_unknown", "severity": "emergency"}],
                    "clarify": False,
                    "error": None,
                }
            payload = [
                {
                    "rule_id": m.rule_id,
                    "severity": m.severity,
                    "guidance": m.guidance,
                }
                for m in matches
            ]
            if any(str(m.severity) == "emergency" for m in matches):
                return {
                    **state,
                    "emergency": True,
                    "intent": "emergency",
                    "confidence": 1.0,
                    "engine": "deterministic_rules",
                    "red_flags": payload,
                    "clarify": False,
                    "error": None,
                }
            return {
                **state,
                "emergency": False,
                "red_flags": payload,
                "error": None,
            }

    async def _clinical_red_flags(self, state: IntentState) -> None:
        """Record the clinical MCP check. Local rules remain the routing decision."""
        try:
            await self._tools.call(
                context=state["tool_context"],
                graph="intent",
                tool="check_red_flags",
                arguments={
                    "text": state["text"],
                    "locale": state.get("locale") or "en-IN",
                },
                timeout_seconds=4.0,
            )
        except ToolUnavailable:
            return

    async def _classify(self, state: IntentState) -> IntentState:
        if state.get("emergency"):
            return state
        with trace_span("intent.classify", {}):
            try:
                result = await self._tools.call(
                    context=state["tool_context"],
                    graph="intent",
                    tool="classify_intent",
                    arguments={"text": state["text"]},
                    timeout_seconds=5.0,
                )
            except ToolUnavailable:
                # Local keyword fallback mirrors mcp-decider so chat still routes.
                result = _local_classify(state["text"])
            raw = str(result.get("intent") or "other")
            intent = INTENT_MAP.get(raw, "other")
            confidence = float(result.get("confidence") or 0.3)
            clarify = confidence < self._threshold and intent not in {
                "emergency",
                "book_appointment",
                "records_question",
            }
            if clarify:
                intent = "clarify"
            return {
                **state,
                "intent": intent,
                "confidence": confidence,
                "engine": str(result.get("engine") or "unknown"),
                "clarify": clarify,
            }

    def _build(self) -> Any:
        graph: StateGraph[IntentState] = StateGraph(IntentState)
        graph.add_node("emergency_scan", self._emergency_scan)
        graph.add_node("classify", self._classify)
        graph.add_edge(START, "emergency_scan")
        graph.add_conditional_edges(
            "emergency_scan",
            lambda s: "end" if s.get("emergency") else "classify",
            {"end": END, "classify": "classify"},
        )
        graph.add_edge("classify", END)
        from app.agents.checkpointer import compile_graph

        return compile_graph(graph, self._checkpointer)

    async def run(
        self,
        *,
        text: str,
        locale: str,
        tool_context: ExecutionContext,
    ) -> IntentState:
        state: IntentState = {
            "text": text,
            "locale": locale,
            "tool_context": tool_context,
        }
        from app.agents.checkpointer import invoke_config

        return await self._graph.ainvoke(
            state, config=invoke_config(checkpoint_ns="intent")
        )


def _local_classify(text: str) -> dict[str, Any]:
    lowered = text.casefold()
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("emergency", ("chest pain", "breathless", "unconscious", "stroke", "bleeding")),
        ("book_appointment", ("book", "appointment", "doctor", "slot", "reschedule")),
        ("records_question", ("report", "lab", "prescription", "document", "test result")),
        ("medication_question", ("medicine", "dose", "tablet", "refill", "pharmacy")),
        ("nursing_summary", ("nursing", "handover", "shift")),
    ]
    for intent, keywords in rules:
        if any(k in lowered for k in keywords):
            return {"engine": "local_fallback", "intent": intent, "confidence": 0.7}
    return {"engine": "local_fallback", "intent": "other", "confidence": 0.35}
