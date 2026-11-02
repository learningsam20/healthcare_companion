"""W1 triage + discrete slot shortlist graph.

Red-flag rules are authoritative. Specialty is chosen from the closed catalogue and
surfaced for user confirmation. Doctor/slot shortlists come from scheduling tools —
never invented by the model. Chat resumes via a slot_choice interrupt (specific starts_at).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sahyog_common.context import ExecutionContext
from sahyog_common.i18n import detect_locale
from sahyog_common.provenance import SourceRef, SourceType, resolve_sources
from sahyog_common.red_flags import detect_red_flags

from app.agents.booking_prefs import (
    CLINIC_TZ,
    format_slot_label,
    parse_preferred_starts_at,
    rank_slots_near_preference,
)
from app.agents.llm_gateway import LlmGateway, LlmGatewayError
from app.agents.mcp_client import McpToolClient, ToolUnavailable
from app.agents.types import AgentTurnResult
from app.core.tracing import trace_span

ShortlistFn = Callable[[str, str | None], Awaitable[list[dict[str, Any]]]]


class W1State(TypedDict, total=False):
    text: str
    locale: str
    clinic_code: str | None
    tool_context: ExecutionContext
    red_flags: list[dict[str, Any]]
    emergency: bool
    specialty_code: str | None
    specialty_label: str | None
    specialty_confidence: float | None
    specialty_needs_clarify: bool
    specialty_options: list[dict[str, Any]]
    preferred_starts_at: str | None
    candidates: list[dict[str, Any]]
    interrupt_payload: dict[str, Any]
    user_choice: dict[str, Any]
    durable_interrupt: bool
    reply: str
    sources: list[dict[str, Any]]
    model_alias: str | None
    prompt_tokens: int
    completion_tokens: int
    gateway_request_id: str | None
    error: str | None
    language_detection: dict[str, Any]
    language_needs_clarify: bool


class W1TriageGraph:
    VERSION = "w1_triage.v1"

    def __init__(
        self,
        *,
        settings: Any,
        models_config: dict[str, Any],
        red_flags_config: dict[str, Any],
        specialties: dict[str, Any],
        triage_prompt: dict[str, Any],
        tool_client: McpToolClient,
        shortlist: ShortlistFn,
        checkpointer: Any | None = None,
    ) -> None:
        self._settings = settings
        self._gateway = LlmGateway(settings, models_config)
        self._red_flags = red_flags_config
        self._specialties = {
            str(item["code"]): item for item in specialties.get("specialties", [])
        }
        self._prompt = triage_prompt
        self._tools = tool_client
        self._shortlist = shortlist
        self._checkpointer = checkpointer
        self._graph = self._build()

    def _safety(self, state: W1State) -> W1State:
        with trace_span("w1.safety", {}):
            try:
                matches = detect_red_flags(
                    state["text"], self._red_flags, state.get("locale") or "en-IN"
                )
            except Exception:  # noqa: BLE001
                guidance = (
                    "We could not complete safety screening. Call 112 or go to the nearest "
                    "emergency department now."
                )
                return {
                    **state,
                    "emergency": True,
                    "red_flags": [{"rule_id": "red_flag_unknown", "severity": "emergency", "guidance": guidance}],
                    "reply": guidance,
                    "sources": [],
                    "error": "red_flag_unknown",
                }
            payload = [
                {
                    "rule_id": m.rule_id,
                    "severity": m.severity,
                    "guidance": m.guidance,
                    "name": m.name,
                }
                for m in matches
            ]
            if any(m.severity == "emergency" for m in matches):
                guidance = next(m.guidance for m in matches if m.severity == "emergency")
                return {
                    **state,
                    "emergency": True,
                    "red_flags": payload,
                    "reply": guidance,
                    "sources": [
                        s.model_dump(mode="json")
                        for s in resolve_sources(
                            [
                                SourceRef(
                                    id=m.rule_id,
                                    type=SourceType.RULE,
                                    title=m.name,
                                    locator=m.rule_id,
                                )
                                for m in matches
                            ],
                            current_patient_id=None,
                        )
                    ],
                    "error": None,
                }
            return {**state, "emergency": False, "red_flags": payload, "error": None}

    def _detect_language(self, state: W1State) -> W1State:
        if state.get("emergency"):
            return state
        enabled = bool(getattr(self._settings, "language_detection_enabled", True))
        if not enabled:
            return {
                **state,
                "language_detection": {"enabled": False},
                "language_needs_clarify": False,
            }
        with trace_span("w1.language_detect", {}):
            fallback = state.get("locale") or "en-IN"
            detected = detect_locale(state["text"], fallback=fallback)
            payload = {
                "enabled": True,
                "locale": detected.locale,
                "confidence": detected.confidence,
                "scripts": sorted(detected.scripts),
                "mixed": detected.mixed,
                "needs_clarify": detected.needs_clarify,
            }
            if detected.needs_clarify:
                options = [
                    {"locale": "en-IN", "label": "English", "code": "en-IN"},
                    {"locale": "hi-IN", "label": "हिन्दी (Hindi)", "code": "hi-IN"},
                    {"locale": "mr-IN", "label": "मराठी (Marathi)", "code": "mr-IN"},
                ]
                lines = [
                    "I want to make sure I reply in the right language.",
                    "Please choose one:",
                ]
                for index, item in enumerate(options, start=1):
                    lines.append(f"{index}. {item['label']}")
                lines.append("Tap a language to continue, or Cancel and restate.")
                return {
                    **state,
                    # Keep session locale until the patient confirms — do not guess.
                    "locale": fallback,
                    "language_detection": payload,
                    "language_needs_clarify": True,
                    "candidates": [
                        {
                            "locale": item["locale"],
                            "label": item["label"],
                            "specialty_code": None,
                        }
                        for item in options
                    ],
                    "reply": "\n".join(lines),
                }
            return {
                **state,
                "locale": detected.locale,
                "language_detection": payload,
                "language_needs_clarify": False,
            }

    async def _match_specialty(self, state: W1State) -> W1State:
        if state.get("emergency") or state.get("language_needs_clarify"):
            return state
        with trace_span("w1.match_specialty", {}):
            catalogue = [
                {"code": code, "label": item.get("en", code)}
                for code, item in self._specialties.items()
            ]
            # Prefer MCP catalogue when available
            try:
                catalog = await self._tools.call(
                    context=state["tool_context"],
                    graph="triage",
                    tool="get_specialty_catalogue",
                    arguments={},
                    timeout_seconds=5.0,
                )
                if isinstance(catalog.get("specialties"), list) and catalog["specialties"]:
                    catalogue = [
                        {
                            "code": str(item.get("code")),
                            "label": str(item.get("en") or item.get("code")),
                        }
                        for item in catalog["specialties"]
                        if item.get("code")
                    ]
            except ToolUnavailable:
                pass

            codes = {item["code"] for item in catalogue}
            clarify_below = float(
                (self._prompt.get("safety") or {}).get("clarify_specialty_below") or 0.6
            )
            messages = [
                {
                    "role": "system",
                    "content": str(self._prompt.get("system", "")),
                },
                {
                    "role": "user",
                    "content": (
                        "Select exactly one specialty code from this closed catalogue for the "
                        "user's concern. Reply with JSON only: "
                        '{"specialty_code":"...","confidence":0-1,"reason":"..."}\n'
                        f"Catalogue: {json.dumps(catalogue, ensure_ascii=False)}\n"
                        f"Locale: {state.get('locale')}\n"
                        f"Concern: {state['text']}"
                    ),
                },
            ]
            try:
                result = await self._gateway.complete(
                    purpose="triage",
                    messages=messages,
                    max_tokens=200,
                    temperature=0.0,
                )
            except LlmGatewayError:
                return {
                    **state,
                    "specialty_code": None,
                    "specialty_label": None,
                    "specialty_confidence": 0.0,
                    "specialty_needs_clarify": True,
                    "specialty_options": catalogue[:6],
                    "model_alias": None,
                    "error": "specialty_model_unavailable",
                    "reply": (
                        "I could not confidently match a specialty. "
                        "Please choose one from the options, or ask the front desk."
                    ),
                }
            code, confidence = _extract_specialty_with_confidence(result.content, codes)
            if code is None:
                code = "general_medicine"
                confidence = min(confidence, 0.4)
            label = next(
                (item["label"] for item in catalogue if item["code"] == code),
                code,
            )
            needs_clarify = confidence < clarify_below
            options = catalogue[:6]
            if needs_clarify:
                # Put the model suggestion first when present.
                options = sorted(
                    catalogue,
                    key=lambda item: 0 if item["code"] == code else 1,
                )[:6]
            return {
                **state,
                "specialty_code": code,
                "specialty_label": label,
                "specialty_confidence": confidence,
                "specialty_needs_clarify": needs_clarify,
                "specialty_options": options if needs_clarify else [],
                "model_alias": result.model_alias,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "gateway_request_id": result.gateway_request_id,
                "reply": (
                    f"I'm only {confidence:.0%} sure this is **{label}**. "
                    "Please confirm a specialty before I check open slots."
                    if needs_clarify
                    else None
                ),
            }

    async def _shortlist_doctors(self, state: W1State) -> W1State:
        if state.get("emergency"):
            return state
        if state.get("language_needs_clarify"):
            # Candidates + reply already set by detect_language.
            return state
        if state.get("specialty_needs_clarify"):
            options = state.get("specialty_options") or []
            lines = [
                state.get("reply")
                or "Please confirm which specialty you need before I check availability."
            ]
            for index, item in enumerate(options[:6], start=1):
                lines.append(f"{index}. {item.get('label') or item.get('code')}")
            lines.append("Tap a specialty to continue, or Cancel and restate your concern.")
            return {
                **state,
                "candidates": [
                    {
                        "specialty_code": item.get("code"),
                        "specialty_label": item.get("label") or item.get("code"),
                        "label": str(item.get("label") or item.get("code")),
                    }
                    for item in options[:6]
                ],
                "reply": "\n".join(lines),
            }
        with trace_span("w1.shortlist", {"specialty": state.get("specialty_code")}):
            specialty = state.get("specialty_code") or "general_medicine"
            specialty_label = state.get("specialty_label") or specialty
            preferred = parse_preferred_starts_at(state["text"])
            preferred_iso = preferred.isoformat() if preferred else None
            try:
                result = await self._tools.call(
                    context=state["tool_context"],
                    graph="triage",
                    tool="search_doctors",
                    arguments={
                        "specialty_code": specialty,
                        "clinic_code": state.get("clinic_code"),
                        "limit": 3,
                    },
                    timeout_seconds=8.0,
                )
                doctors = list(result.get("doctors") or result.get("items") or [])
            except ToolUnavailable:
                doctors = await self._shortlist(specialty, state.get("clinic_code"))

            slot_pool: list[dict[str, Any]] = []
            for doctor in doctors[:3]:
                name = str(doctor.get("doctor_name") or doctor.get("name") or "").strip()
                clinic = str(
                    doctor.get("clinic_code") or doctor.get("clinic") or state.get("clinic_code") or ""
                ).strip()
                if not name or not clinic:
                    continue
                doctor_specialty = str(doctor.get("specialty_code") or specialty)
                slots = await self._availability_slots(
                    state=state,
                    doctor_name=name,
                    clinic_code=clinic,
                    specialty_code=doctor_specialty,
                )
                if not slots:
                    # Fall back to a single verified next_slot from search, if present.
                    next_raw = doctor.get("next_slot") or doctor.get("next_available")
                    if next_raw:
                        slots = [
                            {
                                "starts_at": next_raw,
                                "doctor_name": name,
                                "clinic_code": clinic,
                                "specialty_code": doctor_specialty,
                                "duration_minutes": 20,
                            }
                        ]
                slot_pool.extend(slots)

            ranked = rank_slots_near_preference(slot_pool, preferred, limit=6)
            now = dt.datetime.now(CLINIC_TZ)
            candidates: list[dict[str, Any]] = []
            for slot in ranked:
                starts_raw = slot.get("starts_at")
                if isinstance(starts_raw, dt.datetime):
                    starts = starts_raw if starts_raw.tzinfo else starts_raw.replace(tzinfo=CLINIC_TZ)
                    starts_iso = starts.astimezone(CLINIC_TZ).isoformat()
                else:
                    starts_iso = str(starts_raw)
                    try:
                        starts = dt.datetime.fromisoformat(starts_iso.replace("Z", "+00:00"))
                        if starts.tzinfo is None:
                            starts = starts.replace(tzinfo=CLINIC_TZ)
                        else:
                            starts = starts.astimezone(CLINIC_TZ)
                        starts_iso = starts.isoformat()
                    except ValueError:
                        continue
                name = str(slot.get("doctor_name") or "Doctor")
                clinic = str(slot.get("clinic_code") or "")
                candidates.append(
                    {
                        "doctor_name": name,
                        "clinic_code": clinic,
                        "specialty_code": str(slot.get("specialty_code") or specialty),
                        "starts_at": starts_iso,
                        "duration_minutes": int(slot.get("duration_minutes") or 20),
                        "label": format_slot_label(
                            doctor_name=name,
                            clinic_code=clinic or "clinic",
                            starts_at=starts,
                            now=now,
                        ),
                    }
                )

            sources = resolve_sources(
                [
                    SourceRef(
                        id=f"scheduling:{specialty}",
                        type=SourceType.TOOL,
                        title="Clinic scheduling availability",
                        locator=f"specialty:{specialty}",
                        metadata={"system": "scheduling"},
                    )
                ],
                current_patient_id=None,
            )

            lines = [
                f"Suggested specialty: **{specialty_label}** "
                f"(`{specialty}`). Cancel if that is wrong, then restate your concern.",
            ]
            if preferred is not None:
                pref_label = preferred.strftime("%a %d %b, %I:%M %p").lstrip("0")
                exact = any(
                    abs(
                        (
                            dt.datetime.fromisoformat(c["starts_at"].replace("Z", "+00:00")).astimezone(
                                CLINIC_TZ
                            )
                            - preferred
                        ).total_seconds()
                    )
                    < 60
                    for c in candidates
                )
                if exact:
                    lines.append(f"Checking availability around **{pref_label}** (clinic timezone).")
                else:
                    lines.append(
                        f"**{pref_label}** is not free (or outside clinic hours). "
                        "Nearest open slots from scheduling:"
                    )
            else:
                lines.append("Pick a specific open slot below (clinic hours are 09:00–17:00 IST).")

            if not candidates:
                lines.append(
                    "No open slots were returned for that specialty. "
                    "Try another day or ask the front desk."
                )
            else:
                lines.append("Available slots (not a full-day window — choose one to book):")
                for index, candidate in enumerate(candidates, start=1):
                    lines.append(f"{index}. {candidate['label']}")
                lines.append("Tap a slot to hold and confirm. I will not invent a time.")
            reply = "\n".join(lines)
            return {
                **state,
                "preferred_starts_at": preferred_iso,
                "candidates": candidates,
                "reply": reply,
                "sources": [s.model_dump(mode="json") for s in sources],
            }

    async def _availability_slots(
        self,
        *,
        state: W1State,
        doctor_name: str,
        clinic_code: str,
        specialty_code: str,
    ) -> list[dict[str, Any]]:
        try:
            result = await self._tools.call(
                context=state["tool_context"],
                graph="triage",
                tool="get_availability",
                arguments={
                    "doctor_name": doctor_name,
                    "clinic_code": clinic_code,
                    "specialty_code": specialty_code,
                    "days": 7,
                },
                timeout_seconds=8.0,
            )
        except ToolUnavailable:
            return []
        slots = result.get("slots") if isinstance(result, dict) else None
        if not isinstance(slots, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in slots:
            if not isinstance(item, dict) or not item.get("starts_at"):
                continue
            normalized.append(
                {
                    "starts_at": item["starts_at"],
                    "doctor_name": item.get("doctor_name") or doctor_name,
                    "clinic_code": item.get("clinic_code") or clinic_code,
                    "specialty_code": item.get("specialty_code") or specialty_code,
                    "duration_minutes": int(item.get("duration_minutes") or 20),
                }
            )
        return normalized

    def _await_human(self, state: W1State) -> W1State:
        """Durable pause via LangGraph interrupt() when a checkpointer is present (G-46)."""
        if state.get("emergency") or not state.get("candidates"):
            return state
        if state.get("language_needs_clarify"):
            interrupt_type = "language_choice"
        elif state.get("specialty_needs_clarify"):
            interrupt_type = "specialty_choice"
        else:
            interrupt_type = "slot_choice"
        payload = {
            "type": interrupt_type,
            "candidates": state.get("candidates") or [],
            "specialty_code": state.get("specialty_code"),
            "specialty_label": state.get("specialty_label"),
            "preferred_starts_at": state.get("preferred_starts_at"),
            "reply": state.get("reply"),
        }
        if self._checkpointer is None:
            return {**state, "interrupt_payload": payload, "durable_interrupt": False}
        choice = interrupt(payload)
        return {
            **state,
            "interrupt_payload": payload,
            "user_choice": choice if isinstance(choice, dict) else {"value": choice},
            "durable_interrupt": True,
        }

    def _finalize_choice(self, state: W1State) -> W1State:
        if state.get("emergency"):
            return state
        choice = state.get("user_choice") or {}
        if not choice:
            return state
        # Persist the human decision on state for chat resume / booking.
        return {
            **state,
            "reply": state.get("reply")
            or "Thanks — applying your choice now.",
            "user_choice": choice,
        }

    def _build(self) -> Any:
        graph: StateGraph[W1State] = StateGraph(W1State)
        graph.add_node("safety", self._safety)
        graph.add_node("detect_language", self._detect_language)
        graph.add_node("match_specialty", self._match_specialty)
        graph.add_node("shortlist", self._shortlist_doctors)
        graph.add_node("await_human", self._await_human)
        graph.add_node("finalize_choice", self._finalize_choice)
        graph.add_edge(START, "safety")
        graph.add_conditional_edges(
            "safety",
            lambda s: "end" if s.get("emergency") else "language",
            {"end": END, "language": "detect_language"},
        )
        graph.add_conditional_edges(
            "detect_language",
            lambda s: "shortlist" if s.get("language_needs_clarify") else "match",
            {"shortlist": "shortlist", "match": "match_specialty"},
        )
        graph.add_edge("match_specialty", "shortlist")
        graph.add_conditional_edges(
            "shortlist",
            lambda s: "await" if s.get("candidates") else "end",
            {"await": "await_human", "end": END},
        )
        graph.add_edge("await_human", "finalize_choice")
        graph.add_edge("finalize_choice", END)
        from app.agents.checkpointer import compile_graph

        return compile_graph(graph, self._checkpointer)

    def _to_result(self, result: dict[str, Any], *, thread_id: str | None) -> AgentTurnResult:
        red = None
        if result.get("emergency") and result.get("red_flags"):
            first = result["red_flags"][0]
            red = {
                "rule_ids": [item["rule_id"] for item in result["red_flags"]],
                "severity": first.get("severity", "emergency"),
                "guidance": result.get("reply") or first.get("guidance", ""),
            }
        interrupts = result.get("__interrupt__") or []
        interrupt_type = None
        candidates = list(result.get("candidates") or [])
        if interrupts:
            payload = getattr(interrupts[0], "value", None) or {}
            if isinstance(payload, dict):
                interrupt_type = str(payload.get("type") or "slot_choice")
                candidates = list(payload.get("candidates") or candidates)
                if payload.get("reply"):
                    result = {**result, "reply": payload["reply"]}
        elif result.get("candidates") and not result.get("user_choice"):
            if result.get("language_needs_clarify"):
                interrupt_type = "language_choice"
            elif result.get("specialty_needs_clarify"):
                interrupt_type = "specialty_choice"
            else:
                interrupt_type = "slot_choice"
        return AgentTurnResult(
            content=str(result.get("reply") or "Please contact the front desk for help booking."),
            intent="emergency" if result.get("emergency") else "book_appointment",
            graph=self.VERSION,
            sources=list(result.get("sources") or []),
            red_flag=red,
            model_alias=result.get("model_alias"),
            prompt_tokens=int(result.get("prompt_tokens") or 0),
            completion_tokens=int(result.get("completion_tokens") or 0),
            gateway_request_id=result.get("gateway_request_id"),
            purpose="triage",
            metadata={
                "specialty_code": result.get("specialty_code"),
                "specialty_label": result.get("specialty_label"),
                "specialty_confidence": result.get("specialty_confidence"),
                "preferred_starts_at": result.get("preferred_starts_at"),
                "candidates": candidates,
                "interrupt_type": interrupt_type,
                "thread_id": thread_id,
                "durable_interrupt": bool(interrupts) or bool(result.get("durable_interrupt")),
                "user_choice": result.get("user_choice"),
                "language_detection": result.get("language_detection"),
                "locale": result.get("locale"),
                "graph_interrupt_ids": [
                    getattr(item, "id", None) for item in interrupts if getattr(item, "id", None)
                ],
            },
        )

    async def run(
        self,
        *,
        text: str,
        locale: str,
        clinic_code: str | None,
        tool_context: ExecutionContext,
        thread_id: str | None = None,
    ) -> AgentTurnResult:
        state: W1State = {
            "text": text,
            "locale": locale,
            "clinic_code": clinic_code,
            "tool_context": tool_context,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
        from app.agents.checkpointer import invoke_config

        tid = thread_id or str(uuid.uuid4())
        result = await self._graph.ainvoke(
            state, config=invoke_config(thread_id=tid, checkpoint_ns="w1_triage")
        )
        return self._to_result(result, thread_id=tid)

    async def resume(
        self,
        *,
        thread_id: str,
        resume_value: dict[str, Any],
    ) -> AgentTurnResult:
        """Resume a durable LangGraph interrupt with the user's typed choice (G-46)."""
        from app.agents.checkpointer import invoke_config

        result = await self._graph.ainvoke(
            Command(resume=resume_value),
            config=invoke_config(thread_id=thread_id, checkpoint_ns="w1_triage"),
        )
        return self._to_result(result, thread_id=thread_id)


def _extract_specialty_with_confidence(
    content: str, codes: set[str]
) -> tuple[str | None, float]:
    confidence = 0.0
    try:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if match:
            payload = json.loads(match.group(0))
            code = str(payload.get("specialty_code", "")).strip()
            try:
                confidence = float(payload.get("confidence", 0))
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
            if code in codes:
                return code, confidence
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    for code in codes:
        if code in content:
            return code, max(confidence, 0.55)
    return None, confidence
