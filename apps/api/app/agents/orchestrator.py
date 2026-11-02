"""Chat multi-agent orchestrator: intent → W1 / W2-ask / conversation / emergency."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sahyog_common.context import ExecutionContext, Role
from sahyog_common.provenance import SourceRef, SourceType
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.appointment_help_graph import AppointmentHelpGraph
from app.agents.conversation_graph import ConversationGraph
from app.agents.intent_graph import IntentGraph
from app.agents.mcp_client import McpToolClient
from app.agents.types import AgentTurnResult, IntentLabel
from app.agents.w1_triage_graph import W1TriageGraph
from app.agents.w2_ask_graph import W2AskGraph
from app.core.services import Services
from app.modules.records.ingest import embed_query
from app.repositories.records import DocumentRepository
from app.repositories.scheduling import AppointmentRepository


class ChatOrchestrator:
    """Routes one chat turn across distinct graphs. Ingest remains a worker job."""

    def __init__(self, services: Services, session: AsyncSession) -> None:
        self._services = services
        self._session = session
        tools = McpToolClient(services.settings)
        checkpointer = getattr(services, "checkpointer", None)
        self.intent = IntentGraph(
            red_flags_config=services.red_flags,
            tool_client=tools,
            checkpointer=checkpointer,
        )
        self.w1 = W1TriageGraph(
            settings=services.settings,
            models_config=services.models_config,
            red_flags_config=services.red_flags,
            specialties=services.specialties if isinstance(services.specialties, dict) else {"specialties": services.specialties},
            triage_prompt=services.prompt("triage"),
            tool_client=tools,
            shortlist=self._shortlist_doctors,
            checkpointer=checkpointer,
        )
        self.appointment_help = AppointmentHelpGraph(session=session, tool_client=tools)
        self.w2 = W2AskGraph(
            settings=services.settings,
            models_config=services.models_config,
            prompt=services.prompt("records_answer"),
            retrieve=self._retrieve_records,
            checkpointer=checkpointer,
        )
        self.conversation = ConversationGraph(
            settings=services.settings,
            models_config=services.models_config,
            prompt=services.prompt("conversation"),
            checkpointer=checkpointer,
        )

    def _tool_context(
        self,
        *,
        subject: str,
        role: str,
        patient_id: uuid.UUID | None,
        locale: str,
        clinic_ids: list[str],
        traffic_class: str,
        trace_id: str | None,
    ) -> ExecutionContext:
        now = int(dt.datetime.now(dt.UTC).timestamp())
        try:
            actor_role = Role(role)
        except ValueError:
            actor_role = Role.PATIENT
        return ExecutionContext(
            actor_subject=subject,
            actor_role=actor_role,
            clinic_ids=tuple(clinic_ids or ()),
            patient_id=patient_id,
            trace_id=(trace_id or uuid.uuid4().hex)[:64],
            locale=locale if locale in {"en-IN", "hi-IN", "mr-IN"} else "en-IN",
            traffic_class="synthetic" if traffic_class == "synthetic" else "real",
            issued_at=now,
            expires_at=now + 120,
        )

    async def _shortlist_doctors(
        self, specialty_code: str, clinic_code: str | None
    ) -> list[dict[str, Any]]:
        rows, _ = await AppointmentRepository(self._session).doctors(
            query=None,
            specialty=specialty_code,
            clinic=clinic_code,
            limit=3,
            offset=0,
        )
        items: list[dict[str, Any]] = []
        clinic_tz = dt.timezone(dt.timedelta(hours=5, minutes=30))
        for row in rows[:3]:
            name = str(row.get("doctor_name") or "")
            clinic = str(row.get("clinic_code") or clinic_code or "BANER")
            next_slot = None
            if name:
                now = dt.datetime.now(clinic_tz)
                booked = await AppointmentRepository(self._session).booked_starts(
                    doctor_name=name,
                    clinic_code=clinic,
                    start=now,
                    end=now + dt.timedelta(days=7),
                )
                cursor = now + dt.timedelta(hours=1)
                minute = 0 if cursor.minute < 30 else 30
                cursor = cursor.replace(minute=minute, second=0, microsecond=0)
                while cursor < now + dt.timedelta(days=7):
                    if cursor.weekday() != 6 and 9 <= cursor.hour < 17 and cursor not in booked:
                        next_slot = cursor.isoformat()
                        break
                    cursor += dt.timedelta(minutes=30)
            no_show_risk = None
            no_show_band = None
            if next_slot:
                try:
                    from app.modules.scheduling.no_show import score_no_show

                    starts = dt.datetime.fromisoformat(next_slot)
                    scored = score_no_show(starts_at=starts, source="assistant")
                    no_show_risk = scored.risk
                    no_show_band = scored.band
                except Exception:  # noqa: BLE001
                    no_show_risk = None
                    no_show_band = None
            items.append(
                {
                    "doctor_name": name,
                    "clinic_code": clinic,
                    "specialty_code": specialty_code,
                    "next_slot": next_slot,
                    # Pack shortlist "risk" tool — advisory heuristic on the offered slot.
                    "no_show_risk": no_show_risk,
                    "no_show_band": no_show_band,
                }
            )
        return items

    async def _retrieve_records(
        self, question: str, patient_id: uuid.UUID, *, top_k: int = 6
    ) -> tuple[list[dict[str, Any]], list[SourceRef]]:
        try:
            embedding = await embed_query(self._services, question)
        except Exception:  # noqa: BLE001
            return [], []
        from app.modules.records.query_expand import expand_query_terms

        from app.core.rls import set_patient_rls

        await set_patient_rls(self._session, patient_id)
        rows = await DocumentRepository(self._session).search(
            patient_id=patient_id,
            embedding=embedding,
            limit=top_k,
            query_text=question,
            query_terms=expand_query_terms(question),
        )
        evidence: list[dict[str, Any]] = []
        refs: list[SourceRef] = []
        for chunk, document, distance in rows:
            score = round(1.0 - float(distance), 4) if distance is not None else None
            evidence.append(
                {
                    "id": str(chunk.id),
                    "title": document.title,
                    "page": chunk.page,
                    "content": chunk.content[:2000],
                    "score": score,
                }
            )
            refs.append(
                SourceRef(
                    id=str(chunk.id),
                    type=SourceType.DOCUMENT,
                    title=document.title,
                    locator=f"page:{chunk.page}" if chunk.page is not None else str(chunk.id),
                    patient_id=patient_id,
                    snippet=chunk.content[:240],
                )
            )
        return evidence, refs

    async def handle_turn(
        self,
        *,
        text: str,
        locale: str,
        history: list[dict[str, str]],
        subject: str,
        role: str,
        patient_id: uuid.UUID | None,
        clinic_ids: list[str],
        traffic_class: str,
        trace_id: str | None,
        thread_id: str | None = None,
    ) -> AgentTurnResult:
        tool_context = self._tool_context(
            subject=subject,
            role=role,
            patient_id=patient_id,
            locale=locale,
            clinic_ids=clinic_ids,
            traffic_class=traffic_class,
            trace_id=trace_id,
        )
        routed = await self.intent.run(text=text, locale=locale, tool_context=tool_context)
        intent: IntentLabel = routed.get("intent") or "other"  # type: ignore[assignment]

        if intent == "emergency" or routed.get("emergency"):
            flags = routed.get("red_flags") or []
            guidance = (
                flags[0].get("guidance")
                if flags
                else "Call 112 or go to the nearest emergency department now."
            )
            return AgentTurnResult(
                content=str(guidance),
                intent="emergency",
                graph=IntentGraph.VERSION,
                sources=[],
                red_flag={
                    "rule_ids": [f.get("rule_id") for f in flags if f.get("rule_id")],
                    "severity": "emergency",
                    "guidance": str(guidance),
                },
                purpose="triage",
                metadata={"engine": routed.get("engine"), "confidence": routed.get("confidence")},
            )

        if intent == "book_appointment":
            clinic = clinic_ids[0] if clinic_ids else None
            return await self.w1.run(
                text=text,
                locale=locale,
                clinic_code=clinic,
                tool_context=tool_context,
                thread_id=thread_id,
            )

        if intent == "appointment_help":
            return await self.appointment_help.run(
                text=text,
                locale=locale,
                patient_id=patient_id,
                tool_context=tool_context,
            )

        if intent in {"records_question", "medication_question"}:
            return await self.w2.run(question=text, locale=locale, patient_id=patient_id)

        if intent == "nursing_summary":
            if not self._services.features.enabled("x01_nursing_summary"):
                return AgentTurnResult(
                    content=(
                        "Nursing shift summaries are not enabled in this environment. "
                        "Ask a clinician to review the chart directly."
                    ),
                    intent="nursing_summary",
                    graph="x01.disabled",
                    sources=[],
                    purpose="conversation",
                )
            draft = await self.w2.run(
                question=(
                    "Produce a brief nursing shift handover summary from the record only. "
                    "Cite chunk IDs. Do not invent vitals or events. Question context: "
                    + text
                ),
                locale=locale,
                patient_id=patient_id,
            )
            draft.intent = "nursing_summary"
            draft.graph = "x01_nursing.v1"
            draft.metadata = {**draft.metadata, "x01": True}
            return draft

        memory_note = ""
        if self._services.features.enabled("memory_preferences"):
            from sqlalchemy import select

            from app.integrations.mem0_client import Mem0Client, Mem0Unavailable
            from app.repositories.models import MemoryPreference

            rows = list(
                await self._session.scalars(
                    select(MemoryPreference).where(MemoryPreference.subject == subject).limit(12)
                )
            )
            opted_out = any(
                row.key == "opt_out" and row.value.lower() in {"1", "true", "yes"} for row in rows
            )
            prefs = [f"{row.key}={row.value}" for row in rows if row.key != "opt_out"]
            if prefs and not opted_out:
                memory_note = "User preferences (allowlisted): " + "; ".join(prefs)
            if not opted_out:
                client = Mem0Client(self._services.settings)
                if client.configured:
                    try:
                        hits = await client.search(user_id=subject, query=text[:240], limit=3)
                        snippets = [
                            str(h.get("memory") or h.get("text") or "").strip()
                            for h in hits
                            if (h.get("memory") or h.get("text"))
                        ]
                        snippets = [s for s in snippets if s][:3]
                        if snippets:
                            extra = "Mem0 recalls: " + " | ".join(snippets)
                            memory_note = f"{memory_note}; {extra}" if memory_note else extra
                    except Mem0Unavailable:
                        pass

        return await self.conversation.run(
            text=text,
            locale=locale,
            history=history,
            intent=intent,
            memory_note=memory_note or None,
        )
