"""Appointment help — list / cancel / reschedule via scheduling data + MCP (G-45).

Patients can refer to appointments by ordinal ("cancel 1"), doctor name, or UUID.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sahyog_common.context import ExecutionContext

from app.agents.booking_prefs import parse_preferred_starts_at
from app.agents.mcp_client import McpToolClient, ToolUnavailable
from app.agents.types import AgentTurnResult
from app.repositories.scheduling import AppointmentRepository

CLINIC_TZ = ZoneInfo("Asia/Kolkata")
UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    flags=re.I,
)
ORDINAL_WORDS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
}


class AppointmentHelpGraph:
    VERSION = "appointment_help.v2"

    def __init__(self, *, session: Any, tool_client: McpToolClient) -> None:
        self._session = session
        self._tools = tool_client

    async def run(
        self,
        *,
        text: str,
        locale: str,
        patient_id: uuid.UUID | None,
        tool_context: ExecutionContext,
    ) -> AgentTurnResult:
        if patient_id is None:
            return AgentTurnResult(
                content=(
                    "I can manage appointments for a linked patient record. "
                    "Open Appointments or ask the front desk."
                ),
                intent="appointment_help",
                graph=self.VERSION,
                sources=[],
                purpose="conversation",
            )

        repo = AppointmentRepository(self._session)
        now = dt.datetime.now(CLINIC_TZ)
        rows, _ = await repo.list_grid(
            query=None,
            status=None,
            specialty=None,
            clinic=None,
            patient_id=patient_id,
            clinic_scope=(),
            starts_after=now - dt.timedelta(days=1),
            starts_before=now + dt.timedelta(days=60),
            sort="starts_at",
            descending=False,
            limit=10,
            offset=0,
        )
        upcoming = [r for r in rows if r.status in {"held", "confirmed"}]
        wants_cancel = bool(re.search(r"\b(cancel|cancelled|canceled)\b", text, flags=re.I))
        wants_reschedule = bool(
            re.search(r"\b(reschedule|move|change)\b", text, flags=re.I)
        ) and not wants_cancel

        if wants_cancel:
            chosen = _resolve_appointment(text, upcoming)
            if chosen is None:
                return self._list_result(
                    upcoming,
                    patient_id,
                    preface=(
                        "Which appointment should I cancel? Reply with a number "
                        "(for example: cancel 1) or the doctor's name."
                    ),
                )
            return await self._cancel(chosen.id, tool_context)

        if wants_reschedule:
            chosen = _resolve_appointment(text, upcoming)
            if chosen is None:
                return self._list_result(
                    upcoming,
                    patient_id,
                    preface=(
                        "Which appointment should I reschedule? Reply with a number "
                        "(for example: reschedule 1 tomorrow 3 pm)."
                    ),
                )
            preferred = parse_preferred_starts_at(text, now=now)
            if preferred is None:
                return AgentTurnResult(
                    content=(
                        f"To reschedule **{chosen.doctor_name}** "
                        f"({chosen.starts_at.astimezone(CLINIC_TZ).strftime('%a %d %b, %I:%M %p').lstrip('0')}), "
                        "tell me the new time (for example: tomorrow 3 pm)."
                    ),
                    intent="appointment_help",
                    graph=self.VERSION,
                    sources=[],
                    purpose="conversation",
                    metadata={
                        "action": "reschedule_needs_time",
                        "appointment_id": str(chosen.id),
                        "candidates": [_candidate(chosen, 1)],
                    },
                )
            return await self._reschedule(chosen.id, preferred, tool_context)

        if not upcoming:
            return AgentTurnResult(
                content=(
                    "You have no upcoming held/confirmed appointments in the next 60 days. "
                    "Say you want to book, or open Appointments."
                ),
                intent="appointment_help",
                graph=self.VERSION,
                sources=[],
                purpose="conversation",
            )

        return self._list_result(upcoming, patient_id)

    def _list_result(
        self,
        upcoming: list[Any],
        patient_id: uuid.UUID,
        *,
        preface: str | None = None,
    ) -> AgentTurnResult:
        lines = [
            preface
            or "Here are your upcoming appointments (from scheduling — not invented):",
        ]
        candidates = []
        for index, row in enumerate(upcoming, start=1):
            local = row.starts_at.astimezone(CLINIC_TZ)
            label = (
                f"{row.doctor_name} · {row.clinic_code} · "
                f"{local.strftime('%a %d %b, %I:%M %p').lstrip('0')} · {row.status}"
            )
            lines.append(f"{index}. {label}")
            candidates.append(_candidate(row, index))
        lines.append(
            "To cancel: say `cancel 1` (or the doctor name). "
            "To reschedule: say `reschedule 1 tomorrow 3 pm`."
        )
        return AgentTurnResult(
            content="\n".join(lines),
            intent="appointment_help",
            graph=self.VERSION,
            sources=[
                {
                    "id": "scheduling:patient_upcoming",
                    "type": "tool",
                    "title": "Patient appointments",
                    "locator": str(patient_id),
                    "metadata": {"system": "scheduling"},
                }
            ],
            purpose="conversation",
            metadata={
                "count": len(upcoming),
                "candidates": candidates,
                "interrupt_type": "appointment_action" if upcoming else None,
            },
        )

    async def _cancel(self, appt_id: uuid.UUID, tool_context: ExecutionContext) -> AgentTurnResult:
        try:
            result = await self._tools.call(
                context=tool_context,
                graph="appointment_help",
                tool="cancel_appointment",
                arguments={"appointment_id": str(appt_id)},
                timeout_seconds=15.0,
            )
            appt = result.get("appointment") or {}
            return AgentTurnResult(
                content=(
                    f"Cancelled your appointment "
                    f"(status={appt.get('status', 'cancelled')})."
                ),
                intent="appointment_help",
                graph=self.VERSION,
                sources=[
                    {
                        "id": f"scheduling:{appt_id}",
                        "type": "tool",
                        "title": "Scheduling cancel",
                        "locator": str(appt_id),
                        "metadata": {"system": "scheduling", "via": "mcp"},
                    }
                ],
                purpose="conversation",
                metadata={"action": "cancel", "appointment_id": str(appt_id)},
            )
        except (ToolUnavailable, ValueError) as exc:
            return AgentTurnResult(
                content=f"Could not cancel that appointment via scheduling: {exc}",
                intent="appointment_help",
                graph=self.VERSION,
                sources=[],
                purpose="conversation",
                metadata={"error": "cancel_failed"},
            )

    async def _reschedule(
        self,
        appt_id: uuid.UUID,
        preferred: dt.datetime,
        tool_context: ExecutionContext,
    ) -> AgentTurnResult:
        try:
            result = await self._tools.call(
                context=tool_context,
                graph="appointment_help",
                tool="reschedule_appointment",
                arguments={
                    "appointment_id": str(appt_id),
                    "starts_at": preferred.isoformat(),
                },
                timeout_seconds=15.0,
            )
            appt = result.get("appointment") or {}
            return AgentTurnResult(
                content=(
                    f"Rescheduled to "
                    f"{preferred.strftime('%a %d %b, %I:%M %p').lstrip('0')} "
                    f"(status={appt.get('status', 'confirmed')})."
                ),
                intent="appointment_help",
                graph=self.VERSION,
                sources=[
                    {
                        "id": f"scheduling:{appt_id}",
                        "type": "tool",
                        "title": "Scheduling reschedule",
                        "locator": str(appt_id),
                        "metadata": {"system": "scheduling", "via": "mcp"},
                    }
                ],
                purpose="conversation",
                metadata={"action": "reschedule", "appointment_id": str(appt_id)},
            )
        except (ToolUnavailable, ValueError) as exc:
            return AgentTurnResult(
                content=f"Could not reschedule via scheduling: {exc}",
                intent="appointment_help",
                graph=self.VERSION,
                sources=[],
                purpose="conversation",
                metadata={"error": "reschedule_failed"},
            )


def _candidate(row: Any, index: int) -> dict[str, Any]:
    local = row.starts_at.astimezone(CLINIC_TZ)
    return {
        "index": index,
        "appointment_id": str(row.id),
        "doctor_name": row.doctor_name,
        "clinic_code": row.clinic_code,
        "starts_at": row.starts_at.isoformat(),
        "status": row.status,
        "label": (
            f"{row.doctor_name} · {local.strftime('%a %d %b, %I:%M %p').lstrip('0')}"
        ),
    }


def _resolve_appointment(text: str, upcoming: list[Any]) -> Any | None:
    if not upcoming:
        return None
    uuid_match = UUID_RE.search(text)
    if uuid_match:
        target = uuid_match.group(1).lower()
        for row in upcoming:
            if str(row.id).lower() == target:
                return row
    lower = text.lower()
    for word, index in ORDINAL_WORDS.items():
        if re.search(rf"\b{word}\b", lower) and 1 <= index <= len(upcoming):
            return upcoming[index - 1]
    num = re.search(r"\b(?:cancel|reschedule|move|change)\s*(?:#|number\s*)?(\d{1,2})\b", lower)
    if not num:
        num = re.search(r"\b(\d{1,2})\b", lower)
    if num:
        index = int(num.group(1))
        if 1 <= index <= len(upcoming):
            return upcoming[index - 1]
    for row in upcoming:
        name = str(row.doctor_name or "").lower().strip()
        if name and name in lower:
            return row
        # Match last token of doctor name ("rao" in "Dr Rao")
        parts = [p for p in re.split(r"\s+", name) if len(p) > 2]
        if parts and parts[-1] in lower:
            return row
    return None
