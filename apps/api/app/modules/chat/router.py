from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import uuid
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sahyog_common.context import ExecutionContext
from sahyog_common.context import Role as CtxRole
from sahyog_common.errors import ProblemError
from sahyog_common.i18n import normalize_locale
from sahyog_common.provenance import SourceRef, SourceType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp_client import McpToolClient, ToolUnavailable
from app.agents.orchestrator import ChatOrchestrator
from app.core.db import get_session
from app.modules.chat.titleing import maybe_auto_title
from app.modules.handoffs.service import create_staff_handoff
from app.core.pagination import GridMeta, GridResponse
from app.core.security import AuthContext, get_auth_context
from app.core.services import Services, get_services
from app.modules.chat.schemas import (
    ChatRunOut,
    FeedbackCreate,
    FeedbackOut,
    HeldAppointmentOut,
    InterruptOut,
    MessageCreate,
    MessageOut,
    RedFlagOut,
    ResumeRequest,
    SendResult,
    SessionCreate,
    SessionOut,
    SessionUpdate,
    StopResult,
)
from app.modules.notifications.service import NotificationService
from app.modules.records.schemas import ChunkOut
from app.repositories.records import DocumentRepository
from app.repositories.audit import AuditRepository
from app.repositories.chat import ChatRepository
from app.repositories.chat_runs import ChatRunRepository
from app.repositories.models import ChatFeedback, ReviewTask
from app.repositories.patients import PatientRepository
from app.repositories.scheduling import AppointmentRepository
from app.repositories.usage import UsageRepository

logger = logging.getLogger(__name__)
CLINIC_TZ = ZoneInfo("Asia/Kolkata")
CHOICE_TTL_SECONDS = 120
HOLD_TTL_SECONDS = 120

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ContextDep = Annotated[AuthContext, Depends(get_auth_context)]
ServicesDep = Annotated[Services, Depends(get_services)]


def _source_refs(raw: list[dict]) -> list[SourceRef]:
    refs: list[SourceRef] = []
    for item in raw:
        try:
            refs.append(SourceRef.model_validate(item))
        except Exception:  # noqa: BLE001 - drop malformed provenance rather than fail the turn
            continue
    return refs


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _ensure_chat_enabled(services: Services) -> None:
    if not services.features.enabled("chat_sessions"):
        raise ProblemError(
            403, "feature_disabled", "Chat unavailable", "Chat is disabled by configuration."
        )


def _session_out(chat) -> SessionOut:  # type: ignore[no-untyped-def]
    return SessionOut.model_validate(chat)


def _message_out(message) -> MessageOut:  # type: ignore[no-untyped-def]
    return MessageOut.model_validate(message)


def _choice_expires_at(now: dt.datetime | None = None) -> str:
    base = now or dt.datetime.now(dt.UTC)
    return (base + dt.timedelta(seconds=CHOICE_TTL_SECONDS)).isoformat()


def _held_appointment_out(appointment) -> HeldAppointmentOut:  # type: ignore[no-untyped-def]
    created = appointment.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=dt.UTC)
    return HeldAppointmentOut(
        id=appointment.id,
        doctor_name=appointment.doctor_name,
        clinic_code=appointment.clinic_code,
        specialty_code=appointment.specialty_code,
        starts_at=appointment.starts_at,
        duration_minutes=appointment.duration_minutes,
        status=appointment.status,
        source=getattr(appointment, "source", "assistant") or "assistant",
        hold_expires_at=created + dt.timedelta(seconds=HOLD_TTL_SECONDS),
    )


async def _transcript_excerpt(repo: ChatRepository, session_id: uuid.UUID, *, limit: int = 12) -> str:
    rows = await repo.list_messages(session_id)
    lines: list[str] = []
    for message in rows[-limit:]:
        if message.role not in {"user", "assistant"}:
            continue
        snippet = (message.content or "").replace("\n", " ").strip()[:240]
        lines.append(f"{message.role}: {snippet}")
    return "\n".join(lines)[:1800]


async def _maybe_specialty_clarify_handoff(
    *,
    session: AsyncSession,
    services: Services,
    chat: Any,
    context: AuthContext,
    repo: ChatRepository,
    turn: Any,
    language: str,
    trace_id: str | None,
) -> dict[str, Any] | None:
    """FR-W1-07 / G-40: second specialty low-confidence → front desk with transcript."""
    if turn.metadata.get("interrupt_type") != "specialty_choice":
        return None
    count = int(getattr(chat, "specialty_clarify_count", 0) or 0) + 1
    chat.specialty_clarify_count = count
    if count < 2:
        return None
    clinic = (list(context.clinic_ids) or ["BANER"])[0]
    transcript = await _transcript_excerpt(repo, chat.id)
    handoff = await create_staff_handoff(
        session,
        services,
        patient_id=chat.patient_id,
        created_by_subject=context.subject,
        actor_role=context.primary_role.value,
        clinic_code=str(clinic),
        reason="specialty_clarify_exhausted",
        notes=(
            f"Second low-confidence specialty match. session={chat.id}\n"
            f"suggested={turn.metadata.get('specialty_code')}\n"
            f"confidence={turn.metadata.get('specialty_confidence')}\n"
            f"--- transcript ---\n{transcript}"
        )[:3900],
        resource_type="chat_session",
        resource_id=str(chat.id),
        rule_ids=["specialty_clarify_below"],
        priority="normal",
        trace_id=trace_id,
        consent_id=context.consent_id,
        locale=language,
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="chat.specialty_clarify_handoff",
        resource_type="chat_session",
        resource_id=str(chat.id),
        patient_id=chat.patient_id,
        consent_id=context.consent_id,
        trace_id=trace_id,
        metadata={
            "clarify_count": count,
            "handoff_id": str(handoff.id),
            "specialty_code": turn.metadata.get("specialty_code"),
            "specialty_confidence": turn.metadata.get("specialty_confidence"),
        },
    )
    return {
        "handoff_id": str(handoff.id),
        "clarify_count": count,
        "content": (
            "I still cannot confidently match a specialty, so I've opened a front-desk ticket "
            f"(`{handoff.id}`) with this conversation. A staff member will help you book — "
            "I will not guess a specialty."
        ),
    }


async def _record_citation_failure(
    *,
    session: AsyncSession,
    context: AuthContext,
    chat: Any,
    turn: Any,
    trace_id: str | None,
) -> None:
    """Package citation failures as audit + safety incident (W2 innovation)."""
    from app.repositories.models import SafetyIncident

    foreign = [str(x) for x in (turn.metadata.get("foreign_citation_ids") or []) if x]
    allowed = [str(x) for x in (turn.metadata.get("allowed_citation_ids") or []) if x]
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="safety.citation_failed",
        resource_type="chat_session",
        resource_id=str(chat.id),
        patient_id=chat.patient_id,
        consent_id=context.consent_id,
        trace_id=trace_id,
        metadata={
            "graph": turn.graph,
            "status": turn.metadata.get("status"),
            "grounded": turn.metadata.get("grounded"),
            "model_alias": turn.model_alias,
            "trace_id": trace_id,
            "foreign_citation_ids": foreign[:20],
            "allowed_citation_ids": allowed[:40],
        },
    )
    session.add(
        SafetyIncident(
            patient_id=chat.patient_id,
            reported_by_subject=context.subject,
            severity="medium",
            category="citation_failure",
            title="Grounded-ask citation validation failed",
            detail=(
                f"session={chat.id}; graph={turn.graph}; trace={trace_id or 'n/a'}; "
                f"foreign_ids={','.join(foreign[:8]) or 'n/a'}; "
                f"allowed_count={len(allowed)}; "
                "foreign or unverifiable citation IDs blocked the answer."
            )[:2000],
            status="open",
            linked_resource_type="chat_session",
            linked_resource_id=str(chat.id),
        )
    )


async def _patient_scope(
    context: AuthContext,
    session: AsyncSession,
) -> uuid.UUID | None:
    if context.primary_role.value == "patient":
        if context.patient_id is None:
            raise ProblemError(
                409,
                "account_not_linked",
                "Account not linked",
                "This account is not linked to a patient record. Contact the clinic.",
            )
        patients = PatientRepository(session)
        if not await patients.exists(context.patient_id):
            raise ProblemError(
                409,
                "account_not_linked",
                "Account not linked",
                "This account is not linked to a patient record. Contact the clinic.",
            )
        return context.patient_id
    if context.primary_role.value == "caregiver":
        if context.patient_id is None:
            raise ProblemError(
                403,
                "consent_required",
                "Consent required",
                "No patient is linked to this caregiver account.",
            )
        patients = PatientRepository(session)
        allowed = await patients.active_consent(
            caregiver_subject=context.subject,
            patient_id=context.patient_id,
            scope="chat",
            consent_id=context.consent_id,
        )
        if not allowed:
            raise ProblemError(
                403,
                "consent_required",
                "Consent required",
                "The patient has not granted active chat consent to this caregiver.",
            )
        return context.patient_id
    return None


@router.get("/sessions")
async def list_sessions(
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[Literal["updated_at", "created_at", "title"], Query()] = "updated_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> GridResponse[SessionOut]:
    _ensure_chat_enabled(services)
    repo = ChatRepository(session)
    rows, total = await repo.list_sessions(
        owner_subject=context.subject,
        query=q,
        sort=sort,
        descending=order == "desc",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return GridResponse[SessionOut](
        items=[_session_out(row) for row in rows],
        meta=GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    request: Request,
    body: SessionCreate,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> SessionOut:
    _ensure_chat_enabled(services)
    patient_id = await _patient_scope(context, session)
    title = (body.title or "").strip() or "New conversation"
    locale = body.locale or normalize_locale(context.locale)
    repo = ChatRepository(session)
    chat = await repo.create_session(
        owner_subject=context.subject,
        owner_role=context.primary_role.value,
        patient_id=patient_id,
        title=title[:80],
        locale=locale,
        traffic_class=context.traffic_class,
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="chat.session_created",
        resource_type="chat_session",
        resource_id=str(chat.id),
        patient_id=patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    await session.refresh(chat)
    return _session_out(chat)


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> SessionOut:
    _ensure_chat_enabled(services)
    chat = await ChatRepository(session).get_owned(session_id, context.subject)
    if chat is None:
        raise ProblemError(404, "session_not_found", "Session not found", "No such chat session.")
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="chat.session_viewed",
        resource_type="chat_session",
        resource_id=str(chat.id),
        patient_id=chat.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    return _session_out(chat)


@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: uuid.UUID,
    body: SessionUpdate,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> SessionOut:
    _ensure_chat_enabled(services)
    repo = ChatRepository(session)
    chat = await repo.get_owned(session_id, context.subject)
    if chat is None:
        raise ProblemError(404, "session_not_found", "Session not found", "No such chat session.")
    title = body.title.strip()
    if not title:
        raise ProblemError(422, "title_required", "Title required", "Provide a non-empty title.")
    chat.title = title[:80]
    chat.title_source = "user"
    await repo.touch(chat)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="session.renamed",
        resource_type="chat_session",
        resource_id=str(chat.id),
        patient_id=chat.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"title": chat.title},
    )
    await session.commit()
    await session.refresh(chat)
    return _session_out(chat)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> Response:
    _ensure_chat_enabled(services)
    chat = await ChatRepository(session).get_owned(session_id, context.subject)
    if chat is None:
        raise ProblemError(404, "session_not_found", "Session not found", "No such chat session.")
    cancelled = await ChatRunRepository(session).cancel_active_runs(session_id)
    await ChatRepository(session).soft_delete(chat)
    from app.modules.memory.service import MemoryFacade

    durable_purged = await MemoryFacade(services, session).purge_session(
        subject=context.subject, session_id=str(chat.id)
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="chat.session_deleted",
        resource_type="chat_session",
        resource_id=str(chat.id),
        patient_id=chat.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"cancelled_runs": cancelled, "durable_memory_purged": durable_purged},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> list[MessageOut]:
    _ensure_chat_enabled(services)
    repo = ChatRepository(session)
    chat = await repo.get_owned(session_id, context.subject)
    if chat is None:
        raise ProblemError(404, "session_not_found", "Session not found", "No such chat session.")
    messages = await repo.list_messages(session_id)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="chat.messages_viewed",
        resource_type="chat_session",
        resource_id=str(chat.id),
        patient_id=chat.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"message_count": len(messages)},
    )
    await session.commit()
    return [_message_out(message) for message in messages]


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_message(
    session_id: uuid.UUID,
    body: MessageCreate,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> SendResult:
    _ensure_chat_enabled(services)
    repo = ChatRepository(session)
    chat = await repo.get_owned(session_id, context.subject)
    if chat is None:
        raise ProblemError(404, "session_not_found", "Session not found", "No such chat session.")
    language = body.language or normalize_locale(chat.locale)
    trace_id = _trace(request)
    user_message = await repo.add_message(
        session_id=chat.id,
        role="user",
        content=body.content,
        language=language,
        trace_id=trace_id,
    )
    audit = AuditRepository(session)
    audit.append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="chat.message_sent",
        resource_type="chat_session",
        resource_id=str(chat.id),
        patient_id=chat.patient_id,
        consent_id=context.consent_id,
        trace_id=trace_id,
        metadata={"language": language},
    )
    await repo.touch(chat)
    await session.commit()

    history_rows = await repo.list_messages(chat.id)
    history = [
        {"role": message.role, "content": message.content}
        for message in history_rows
        if message.role in {"user", "assistant"}
    ]
    # Pre-allocate a run id so W1 can use a durable LangGraph thread_id (G-46).
    runs = ChatRunRepository(session)
    provisional = await runs.create(
        session_id=chat.id,
        owner_subject=context.subject,
        graph="pending",
        graph_version="pending",
        status="running",
        trace_id=trace_id,
        checkpoint={"user_message_id": str(user_message.id), "user_text": body.content},
    )
    thread_id = f"w1:{provisional.id}"
    provisional.checkpoint = {**(provisional.checkpoint or {}), "thread_id": thread_id}
    await session.flush()
    orchestrator = ChatOrchestrator(services, session)
    from app.core.tracing import current_trace
    from app.modules.memory.service import MemoryFacade

    collector = current_trace()
    if collector is not None:
        collector.session_id = str(chat.id)
        collector.user_id = context.subject

    from app.core.security import doctor_schedule_name

    turn = await orchestrator.handle_turn(
        text=body.content,
        locale=language,
        history=history,
        subject=context.subject,
        role=context.primary_role.value,
        patient_id=chat.patient_id,
        clinic_ids=list(context.clinic_ids),
        traffic_class=context.traffic_class,
        trace_id=trace_id,
        thread_id=thread_id,
        chat_session_id=str(chat.id),
        fixed_doctor_name=doctor_schedule_name(context),
    )
    if turn.metadata.get("error") == "egress_blocked":
        blocked = await repo.add_message(
            session_id=chat.id,
            role="assistant",
            content=(
                "The assistant reply was blocked by privacy policy "
                "(external model route unavailable for this content)."
            ),
            language=language,
            sources=[],
            safety={"blocked": True, "code": "egress_blocked"},
            trace_id=trace_id,
        )
        await runs.complete(
            provisional,
            status="failed",
            error_code="egress_blocked",
            result_message_id=blocked.id,
        )
        audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="chat.reply_blocked",
            resource_type="chat_session",
            resource_id=str(chat.id),
            patient_id=chat.patient_id,
            trace_id=trace_id,
            metadata={"reason": "external_egress_blocked", "run_id": str(provisional.id)},
        )
        await session.commit()
        raise ProblemError(
            503,
            "egress_blocked",
            "Assistant unavailable",
            "The configured model route is blocked by privacy policy.",
        )
    if turn.metadata.get("error") == "gateway_unavailable":
        blocked = await repo.add_message(
            session_id=chat.id,
            role="assistant",
            content=(
                "The assistant is temporarily unavailable. "
                "Your message was saved; try again shortly."
            ),
            language=language,
            sources=[],
            safety={"blocked": True, "code": "gateway_unavailable"},
            trace_id=trace_id,
        )
        await runs.complete(
            provisional,
            status="failed",
            error_code="gateway_unavailable",
            result_message_id=blocked.id,
        )
        audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="chat.reply_failed",
            resource_type="chat_session",
            resource_id=str(chat.id),
            patient_id=chat.patient_id,
            trace_id=trace_id,
            metadata={"reason": "gateway_unavailable", "run_id": str(provisional.id)},
        )
        await session.commit()
        raise ProblemError(
            503,
            "gateway_unavailable",
            "Assistant unavailable",
            "The model gateway is unavailable. Your message was saved; try again shortly.",
        )

    safety_payload: dict[str, Any] = {}
    if turn.metadata.get("status") == "citation_failed":
        await _record_citation_failure(
            session=session,
            context=context,
            chat=chat,
            turn=turn,
            trace_id=trace_id,
        )
        safety_payload = {
            "citation_failed": True,
            "grounded": False,
            "status": "citation_failed",
            "trace_id": trace_id,
            "foreign_citation_ids": turn.metadata.get("foreign_citation_ids") or [],
        }
    if turn.intent == "emergency":
        audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="safety.red_flag_triggered",
            resource_type="chat_session",
            resource_id=str(chat.id),
            patient_id=chat.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={
                "rule_ids": (turn.red_flag or {}).get("rule_ids", []),
                "severity": (turn.red_flag or {}).get("severity"),
                "graph": turn.graph,
            },
        )
        # FR-W1-04: emergency desk ticket + 2-minute SLA paging (Wave F).
        handoff_note = ""
        try:
            clinic = (list(context.clinic_ids) or ["BANER"])[0]
            rule_ids = [str(r) for r in ((turn.red_flag or {}).get("rule_ids") or []) if r]
            handoff = await create_staff_handoff(
                session,
                services,
                patient_id=chat.patient_id,
                created_by_subject=context.subject,
                actor_role=context.primary_role.value,
                clinic_code=str(clinic),
                reason="emergency_red_flag",
                notes=(
                    f"Chat red-flag triage. rules={','.join(rule_ids) or 'unknown'}; "
                    f"session={chat.id}"
                )[:500],
                resource_type="chat_session",
                resource_id=str(chat.id),
                rule_ids=rule_ids,
                priority="emergency",
                trace_id=trace_id,
                consent_id=context.consent_id,
                locale=language,
            )
            handoff_note = (
                f"\n\nAn emergency desk ticket was opened (`{handoff.id}`), "
                "SLA call-within-2-minutes. Staff will follow clinic protocol; "
                "this message does not confirm a phone callback."
            )
            safety_payload = {
                "red_flag": True,
                "rule_ids": rule_ids,
                "severity": str((turn.red_flag or {}).get("severity") or "emergency"),
                "guidance": str((turn.red_flag or {}).get("guidance") or turn.content),
                "handoff_id": str(handoff.id),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("emergency handoff create failed", exc_info=exc)
            handoff_note = (
                "\n\nWe could not open an automatic desk ticket. "
                "Call 112 or go to the nearest emergency department now; "
                "do not wait for a callback."
            )
            safety_payload = {
                "red_flag": True,
                "rule_ids": [str(r) for r in ((turn.red_flag or {}).get("rule_ids") or []) if r],
                "severity": "emergency",
                "guidance": str((turn.red_flag or {}).get("guidance") or turn.content),
                "handoff_failed": True,
            }
        turn_content = f"{turn.content.rstrip()}{handoff_note}"
    else:
        turn_content = turn.content

    assistant = await repo.add_message(
        session_id=chat.id,
        role="assistant",
        content=turn_content,
        language=language,
        sources=_source_refs(turn.sources),
        safety=safety_payload,
        trace_id=trace_id,
        model_alias=turn.model_alias,
    )
    try:
        await MemoryFacade(services, session).remember_session_turn(
            subject=context.subject,
            session_id=str(chat.id),
            user_text=body.content,
            assistant_text=turn_content,
        )
    except Exception:  # noqa: BLE001 - memory write must not fail the turn
        logger.debug("session episodic memory write skipped", exc_info=True)
    if turn.model_alias and (turn.prompt_tokens or turn.completion_tokens):
        await UsageRepository(session).record(
            purpose=turn.purpose,
            model_alias=turn.model_alias,
            prompt_tokens=turn.prompt_tokens,
            completion_tokens=turn.completion_tokens,
            cost_usd=services.model_cost(
                turn.model_alias, turn.prompt_tokens, turn.completion_tokens
            ),
            trace_id=trace_id,
            session_id=chat.id,
            traffic_class=chat.traffic_class,
            gateway_request_id=turn.gateway_request_id,
        )

    # Persist detected locale only when confident and not waiting on language_choice.
    lang_meta = turn.metadata.get("language_detection") or {}
    if (
        turn.metadata.get("interrupt_type") != "language_choice"
        and lang_meta.get("locale")
        and float(lang_meta.get("confidence") or 0) >= 0.55
        and not lang_meta.get("needs_clarify")
    ):
        chat.locale = str(lang_meta["locale"])
        language = str(lang_meta["locale"])

    clarify_handoff = await _maybe_specialty_clarify_handoff(
        session=session,
        services=services,
        chat=chat,
        context=context,
        repo=repo,
        turn=turn,
        language=language,
        trace_id=trace_id,
    )
    if clarify_handoff is not None:
        assistant.content = str(clarify_handoff["content"])
        assistant.safety = {
            **(assistant.safety or {}),
            "specialty_clarify_handoff": True,
            "handoff_id": clarify_handoff["handoff_id"],
            "clarify_count": clarify_handoff["clarify_count"],
        }
        await session.flush()

    interrupt_meta = None if clarify_handoff else turn.metadata.get("interrupt_type")
    candidates = turn.metadata.get("candidates") or []
    interrupt_out: InterruptOut | None = None
    run = provisional
    if interrupt_meta and candidates:
        interrupt_id = f"int_{uuid.uuid4().hex[:16]}"
        await runs.mark_interrupted(
            run,
            graph=turn.graph,
            interrupt_type=str(interrupt_meta),
            interrupt_id=interrupt_id,
            interrupt_payload={
                "candidates": candidates,
                "specialty_code": turn.metadata.get("specialty_code"),
                "specialty_label": turn.metadata.get("specialty_label"),
                "preferred_starts_at": turn.metadata.get("preferred_starts_at"),
                "clinic_code": (list(context.clinic_ids) or [None])[0],
                "patient_id": str(chat.patient_id) if chat.patient_id else None,
                "choice_expires_at": _choice_expires_at(),
            },
            result_message_id=assistant.id,
            checkpoint={
                "intent": turn.intent,
                "user_message_id": str(user_message.id),
                "user_text": body.content,
                "thread_id": thread_id,
                "durable_interrupt": bool(turn.metadata.get("durable_interrupt")),
            },
        )
        interrupt_out = InterruptOut(
            run_id=run.id,
            interrupt_id=interrupt_id,
            interrupt_type=str(interrupt_meta),
            payload={
                "candidates": candidates,
                "specialty_code": turn.metadata.get("specialty_code"),
                "specialty_label": turn.metadata.get("specialty_label"),
                "preferred_starts_at": turn.metadata.get("preferred_starts_at"),
                "choice_expires_at": _choice_expires_at(),
            },
        )
        run_id = run.id
    else:
        run.graph = turn.graph
        run.graph_version = turn.graph
        await runs.complete(
            run,
            status="completed",
            result_message_id=assistant.id,
            checkpoint={
                "intent": turn.intent,
                "user_message_id": str(user_message.id),
                "user_text": body.content,
                "thread_id": thread_id,
            },
        )
        run_id = run.id

    user_texts = [
        message.content for message in history_rows if message.role == "user"
    ]
    if body.content not in user_texts:
        user_texts.append(body.content)
    await maybe_auto_title(
        services=services,
        chat=chat,
        user_texts=user_texts,
        intent=turn.intent,
    )

    audit.append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="chat.reply_generated",
        resource_type="chat_session",
        resource_id=str(chat.id),
        patient_id=chat.patient_id,
        consent_id=context.consent_id,
        trace_id=trace_id,
        metadata={
            "model_alias": turn.model_alias,
            "prompt_tokens": turn.prompt_tokens,
            "completion_tokens": turn.completion_tokens,
            "intent": turn.intent,
            "graph": turn.graph,
            "run_id": str(run_id),
            "interrupt": bool(interrupt_out),
            "title_source": getattr(chat, "title_source", "system"),
        },
    )
    await repo.touch(chat)
    await session.commit()
    await session.refresh(user_message)
    await session.refresh(assistant)
    red_flag = None
    if turn.red_flag or safety_payload.get("red_flag"):
        red_flag = RedFlagOut(
            rule_ids=[
                str(item)
                for item in (
                    (turn.red_flag or {}).get("rule_ids")
                    or safety_payload.get("rule_ids")
                    or []
                )
                if item
            ],
            severity=str(
                (turn.red_flag or {}).get("severity")
                or safety_payload.get("severity")
                or "emergency"
            ),
            guidance=str(
                (turn.red_flag or {}).get("guidance")
                or safety_payload.get("guidance")
                or turn.content
            ),
        )
    return SendResult(
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant),
        red_flag=red_flag,
        run_id=run_id,
        interrupt=interrupt_out,
    )


@router.post("/sessions/{session_id}/messages/stream")
async def send_message_stream(
    session_id: uuid.UUID,
    body: MessageCreate,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> StreamingResponse:
    """SSE token stream after safety/intent validation (G-47).

    Events: ``user``, ``token``, ``interrupt``, ``final``, ``error``.
    Booking / emergency / grounded-ask paths emit a single final (or interrupt)
    after the full turn — tokens stream only for general conversation once red
    flags are cleared.
    """
    _ensure_chat_enabled(services)
    repo = ChatRepository(session)
    chat = await repo.get_owned(session_id, context.subject)
    if chat is None:
        raise ProblemError(404, "session_not_found", "Session not found", "No such chat session.")
    language = body.language or normalize_locale(chat.locale)
    trace_id = _trace(request)
    user_message = await repo.add_message(
        session_id=chat.id,
        role="user",
        content=body.content,
        language=language,
        trace_id=trace_id,
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="chat.message_sent",
        resource_type="chat_session",
        resource_id=str(chat.id),
        patient_id=chat.patient_id,
        consent_id=context.consent_id,
        trace_id=trace_id,
        metadata={"language": language, "stream": True},
    )
    await repo.touch(chat)
    await session.commit()

    history_rows = await repo.list_messages(chat.id)
    history = [
        {"role": message.role, "content": message.content}
        for message in history_rows
        if message.role in {"user", "assistant"}
    ]
    runs = ChatRunRepository(session)
    provisional = await runs.create(
        session_id=chat.id,
        owner_subject=context.subject,
        graph="pending",
        graph_version="pending",
        status="running",
        trace_id=trace_id,
        checkpoint={
            "user_message_id": str(user_message.id),
            "user_text": body.content,
            "stream": True,
        },
    )
    thread_id = f"w1:{provisional.id}"
    provisional.checkpoint = {**(provisional.checkpoint or {}), "thread_id": thread_id}
    await session.flush()
    await session.commit()

    def _sse(event: str, payload: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"

    async def event_stream() -> Any:
        from app.agents.conversation_graph import LANGUAGE_NAMES
        from app.agents.llm_gateway import ExternalEgressBlocked, LlmGateway, LlmGatewayError, LlmResult

        yield _sse(
            "user",
            {
                "run_id": str(provisional.id),
                "message": _message_out(user_message).model_dump(mode="json"),
            },
        )
        orchestrator = ChatOrchestrator(services, session)
        tool_context = orchestrator._tool_context(
            subject=context.subject,
            role=context.primary_role.value,
            patient_id=chat.patient_id,
            locale=language,
            clinic_ids=list(context.clinic_ids),
            traffic_class=chat.traffic_class,
            trace_id=trace_id,
        )
        routed = await orchestrator.intent.run(
            text=body.content, locale=language, tool_context=tool_context
        )
        intent = routed.get("intent") or "other"
        streamable_chat = intent in {"other", "clarify"} and not routed.get("emergency")
        streamable_ask = (
            intent in {"records_question", "medication_question"}
            and not routed.get("emergency")
        )

        try:
            if streamable_ask:
                from app.agents.types import AgentTurnResult as _Turn

                from app.core.tracing import current_trace

                collector = current_trace()
                if collector is not None:
                    collector.session_id = str(chat.id)
                    collector.user_id = context.subject
                orchestrator._turn_context = tool_context
                assembled = ""
                final_turn: _Turn | None = None
                async for piece in orchestrator.w2.stream(
                    question=body.content,
                    locale=language,
                    patient_id=chat.patient_id,
                ):
                    if isinstance(piece, _Turn):
                        final_turn = piece
                        assembled = piece.content or assembled
                    else:
                        assembled += piece
                        yield _sse(
                            "token",
                            {"run_id": str(provisional.id), "delta": piece},
                        )
                if final_turn is None:
                    raise RuntimeError("ask stream ended without a final turn")
                # Citation failure: tokens may have dripped — replace with refusal content.
                if final_turn.metadata.get("status") == "citation_failed":
                    assembled = final_turn.content
                    await _record_citation_failure(
                        session=session,
                        context=context,
                        chat=chat,
                        turn=final_turn,
                        trace_id=trace_id,
                    )
                assistant = await repo.add_message(
                    session_id=chat.id,
                    role="assistant",
                    content=assembled or final_turn.content,
                    language=language,
                    sources=_source_refs(final_turn.sources),
                    safety={
                        "grounded": bool(final_turn.metadata.get("grounded", True)),
                        "status": final_turn.metadata.get("status"),
                        "citation_failed": final_turn.metadata.get("status") == "citation_failed",
                        "trace_id": trace_id,
                    },
                    trace_id=trace_id,
                    model_alias=final_turn.model_alias,
                )
                if final_turn.model_alias and (
                    final_turn.prompt_tokens or final_turn.completion_tokens
                ):
                    await UsageRepository(session).record(
                        purpose=final_turn.purpose,
                        model_alias=final_turn.model_alias,
                        prompt_tokens=final_turn.prompt_tokens,
                        completion_tokens=final_turn.completion_tokens,
                        cost_usd=services.model_cost(
                            final_turn.model_alias,
                            final_turn.prompt_tokens,
                            final_turn.completion_tokens,
                        ),
                        trace_id=trace_id,
                        session_id=chat.id,
                        traffic_class=chat.traffic_class,
                        gateway_request_id=final_turn.gateway_request_id,
                    )
                provisional.graph = final_turn.graph
                provisional.graph_version = final_turn.graph
                await runs.complete(
                    provisional,
                    status="completed",
                    result_message_id=assistant.id,
                    checkpoint={"intent": intent, "stream": True, "streamed_ask": True},
                )
                user_texts = [m["content"] for m in history if m.get("role") == "user"]
                await maybe_auto_title(
                    services=services,
                    chat=chat,
                    user_texts=user_texts,
                    intent=str(intent),
                )
                await repo.touch(chat)
                await session.commit()
                yield _sse(
                    "final",
                    {
                        "run_id": str(provisional.id),
                        "assistant_message": _message_out(assistant).model_dump(mode="json"),
                        "red_flag": None,
                        "interrupt": None,
                    },
                )
                return

            if not streamable_chat:
                from app.core.security import doctor_schedule_name

                turn = await orchestrator.handle_turn(
                    text=body.content,
                    locale=language,
                    history=history,
                    subject=context.subject,
                    role=context.primary_role.value,
                    patient_id=chat.patient_id,
                    clinic_ids=list(context.clinic_ids),
                    traffic_class=chat.traffic_class,
                    trace_id=trace_id,
                    thread_id=thread_id,
                    chat_session_id=str(chat.id),
                    fixed_doctor_name=doctor_schedule_name(context),
                )
                if turn.metadata.get("error") in {"egress_blocked", "gateway_unavailable"}:
                    code = str(turn.metadata.get("error"))
                    blocked = await repo.add_message(
                        session_id=chat.id,
                        role="assistant",
                        content=turn.content
                        or (
                            "The assistant reply was blocked by privacy policy."
                            if code == "egress_blocked"
                            else "The assistant is temporarily unavailable."
                        ),
                        language=language,
                        sources=[],
                        safety={"blocked": True, "code": code},
                        trace_id=trace_id,
                    )
                    await runs.complete(
                        provisional,
                        status="failed",
                        error_code=code,
                        result_message_id=blocked.id,
                    )
                    AuditRepository(session).append(
                        actor_subject=context.subject,
                        actor_role=context.primary_role.value,
                        action="chat.reply_blocked"
                        if code == "egress_blocked"
                        else "chat.reply_failed",
                        resource_type="chat_session",
                        resource_id=str(chat.id),
                        patient_id=chat.patient_id,
                        trace_id=trace_id,
                        metadata={"reason": code, "run_id": str(provisional.id), "stream": True},
                    )
                    await session.commit()
                    yield _sse(
                        "error",
                        {
                            "run_id": str(provisional.id),
                            "code": code,
                            "detail": turn.content,
                            "assistant_message": _message_out(blocked).model_dump(mode="json"),
                        },
                    )
                    return

                turn_content = turn.content
                safety_payload: dict[str, Any] = {}
                if turn.intent == "emergency":
                    AuditRepository(session).append(
                        actor_subject=context.subject,
                        actor_role=context.primary_role.value,
                        action="safety.red_flag_triggered",
                        resource_type="chat_session",
                        resource_id=str(chat.id),
                        patient_id=chat.patient_id,
                        consent_id=context.consent_id,
                        trace_id=trace_id,
                        metadata={
                            "rule_ids": (turn.red_flag or {}).get("rule_ids", []),
                            "severity": (turn.red_flag or {}).get("severity"),
                            "graph": turn.graph,
                            "stream": True,
                        },
                    )
                    handoff_note = ""
                    try:
                        clinic = (list(context.clinic_ids) or ["BANER"])[0]
                        rule_ids = [
                            str(r) for r in ((turn.red_flag or {}).get("rule_ids") or []) if r
                        ]
                        handoff = await create_staff_handoff(
                            session,
                            services,
                            patient_id=chat.patient_id,
                            created_by_subject=context.subject,
                            actor_role=context.primary_role.value,
                            clinic_code=str(clinic),
                            reason="emergency_red_flag",
                            notes=(
                                f"Chat red-flag triage (stream). "
                                f"rules={','.join(rule_ids) or 'unknown'}; session={chat.id}"
                            )[:500],
                            resource_type="chat_session",
                            resource_id=str(chat.id),
                            rule_ids=rule_ids,
                            priority="emergency",
                            trace_id=trace_id,
                            consent_id=context.consent_id,
                            locale=language,
                        )
                        handoff_note = (
                            f"\n\nAn emergency desk ticket was opened (`{handoff.id}`), "
                            "SLA call-within-2-minutes. Staff will follow clinic protocol; "
                            "this message does not confirm a phone callback."
                        )
                        safety_payload = {
                            "red_flag": True,
                            "rule_ids": rule_ids,
                            "severity": str(
                                (turn.red_flag or {}).get("severity") or "emergency"
                            ),
                            "guidance": str(
                                (turn.red_flag or {}).get("guidance") or turn.content
                            ),
                            "handoff_id": str(handoff.id),
                        }
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("stream emergency handoff create failed", exc_info=exc)
                        handoff_note = (
                            "\n\nWe could not open an automatic desk ticket. "
                            "Call 112 or go to the nearest emergency department now; "
                            "do not wait for a callback."
                        )
                        safety_payload = {
                            "red_flag": True,
                            "rule_ids": [
                                str(r)
                                for r in ((turn.red_flag or {}).get("rule_ids") or [])
                                if r
                            ],
                            "severity": "emergency",
                            "guidance": str(
                                (turn.red_flag or {}).get("guidance") or turn.content
                            ),
                            "handoff_failed": True,
                        }
                    turn_content = f"{turn.content.rstrip()}{handoff_note}"

                assistant = await repo.add_message(
                    session_id=chat.id,
                    role="assistant",
                    content=turn_content,
                    language=language,
                    sources=_source_refs(turn.sources),
                    safety=safety_payload,
                    trace_id=trace_id,
                    model_alias=turn.model_alias,
                )
                clarify_handoff = await _maybe_specialty_clarify_handoff(
                    session=session,
                    services=services,
                    chat=chat,
                    context=context,
                    repo=repo,
                    turn=turn,
                    language=language,
                    trace_id=trace_id,
                )
                if clarify_handoff is not None:
                    assistant.content = str(clarify_handoff["content"])
                    assistant.safety = {
                        **(assistant.safety or {}),
                        "specialty_clarify_handoff": True,
                        "handoff_id": clarify_handoff["handoff_id"],
                        "clarify_count": clarify_handoff["clarify_count"],
                    }
                    await session.flush()
                user_texts = [m["content"] for m in history if m.get("role") == "user"]
                await maybe_auto_title(
                    services=services,
                    chat=chat,
                    user_texts=user_texts,
                    intent=turn.intent,
                )
                interrupt_meta = None if clarify_handoff else turn.metadata.get("interrupt_type")
                candidates = turn.metadata.get("candidates") or []
                interrupt_out: dict[str, Any] | None = None
                if interrupt_meta and candidates:
                    interrupt_id = f"int_{uuid.uuid4().hex[:16]}"
                    await runs.mark_interrupted(
                        provisional,
                        graph=turn.graph,
                        interrupt_type=str(interrupt_meta),
                        interrupt_id=interrupt_id,
                        interrupt_payload={
                            "candidates": candidates,
                            "specialty_code": turn.metadata.get("specialty_code"),
                            "specialty_label": turn.metadata.get("specialty_label"),
                            "preferred_starts_at": turn.metadata.get("preferred_starts_at"),
                            "clinic_code": (list(context.clinic_ids) or [None])[0],
                            "patient_id": str(chat.patient_id) if chat.patient_id else None,
                            "choice_expires_at": _choice_expires_at(),
                        },
                        result_message_id=assistant.id,
                        checkpoint={
                            "intent": turn.intent,
                            "user_message_id": str(user_message.id),
                            "user_text": body.content,
                            "thread_id": thread_id,
                            "durable_interrupt": bool(turn.metadata.get("durable_interrupt")),
                            "stream": True,
                        },
                    )
                    interrupt_out = {
                        "run_id": str(provisional.id),
                        "interrupt_id": interrupt_id,
                        "interrupt_type": str(interrupt_meta),
                        "payload": {
                            "candidates": candidates,
                            "specialty_code": turn.metadata.get("specialty_code"),
                            "specialty_label": turn.metadata.get("specialty_label"),
                            "preferred_starts_at": turn.metadata.get("preferred_starts_at"),
                            "choice_expires_at": _choice_expires_at(),
                        },
                    }
                    await repo.touch(chat)
                    await session.commit()
                    yield _sse(
                        "interrupt",
                        {
                            "run_id": str(provisional.id),
                            "interrupt": interrupt_out,
                            "assistant_message": _message_out(assistant).model_dump(mode="json"),
                            "red_flag": turn.red_flag or safety_payload or None,
                        },
                    )
                    return

                provisional.graph = turn.graph
                provisional.graph_version = turn.graph
                await runs.complete(
                    provisional,
                    status="completed",
                    result_message_id=assistant.id,
                    checkpoint={"intent": turn.intent, "thread_id": thread_id, "stream": True},
                )
                await repo.touch(chat)
                await session.commit()
                yield _sse(
                    "final",
                    {
                        "run_id": str(provisional.id),
                        "assistant_message": _message_out(assistant).model_dump(mode="json"),
                        "red_flag": turn.red_flag or safety_payload or None,
                        "interrupt": None,
                    },
                )
                return

            # Streamable path: safety already cleared via intent graph.
            from app.core.tracing import current_trace
            from app.modules.memory.service import MemoryFacade, append_attribution

            collector = current_trace()
            if collector is not None:
                collector.session_id = str(chat.id)
                collector.user_id = context.subject

            recall = await MemoryFacade(services, session).recall(
                subject=context.subject,
                query=body.content,
                session_id=str(chat.id),
                history=history,
            )
            prompt = services.prompt("conversation")
            messages = [
                {"role": "system", "content": str(prompt.get("system", ""))},
                {
                    "role": "system",
                    "content": (
                        f"Reply in {LANGUAGE_NAMES.get(language, 'English')}. "
                        "Do not diagnose, prescribe, or invent clinic data. "
                        "If the user needs booking or records, say so briefly. "
                        "When using remembered preferences or earlier chat context, "
                        "mention the marker like [M1] or [C1] inline."
                    ),
                },
            ]
            if recall.memory_note:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"{recall.memory_note}. Use only for tone/routing; "
                            "never invent clinical facts from preferences. "
                            "Cite markers [M#]/[C#] when you rely on them."
                        ),
                    }
                )
            for item in history[-12:]:
                if item.get("role") in {"user", "assistant"}:
                    messages.append(
                        {"role": item["role"], "content": item.get("content", "")[:4000]}
                    )
            gateway = LlmGateway(services.settings, services.models_config)
            assembled = ""
            final_result: LlmResult | None = None
            async for piece in gateway.stream(
                purpose="conversation",
                messages=messages,
                trace_id=trace_id,
                language=language,
            ):
                if isinstance(piece, LlmResult):
                    final_result = piece
                    assembled = piece.content or assembled
                else:
                    assembled += piece
                    yield _sse(
                        "token",
                        {"run_id": str(provisional.id), "delta": piece},
                    )

            if final_result is None:
                raise LlmGatewayError("stream ended without a final result")

            content = append_attribution(
                assembled or final_result.content, recall.attribution
            )
            sources = [
                *recall.sources,
                *(
                    s.model_dump(mode="json")
                    for s in [
                        SourceRef(
                            id=f"model:{final_result.model_alias}",
                            type=SourceType.GENERAL,
                            title="General assistant response — not clinical evidence",
                            locator=f"model:{final_result.model_alias}",
                        )
                    ]
                ),
            ]
            assistant = await repo.add_message(
                session_id=chat.id,
                role="assistant",
                content=content,
                language=language,
                sources=_source_refs(sources),
                trace_id=trace_id,
                model_alias=final_result.model_alias,
            )
            try:
                await MemoryFacade(services, session).remember_session_turn(
                    subject=context.subject,
                    session_id=str(chat.id),
                    user_text=body.content,
                    assistant_text=content,
                )
            except Exception:  # noqa: BLE001
                logger.debug("session episodic memory write skipped", exc_info=True)
            if final_result.model_alias and (
                final_result.prompt_tokens or final_result.completion_tokens
            ):
                await UsageRepository(session).record(
                    purpose="conversation",
                    model_alias=final_result.model_alias,
                    prompt_tokens=final_result.prompt_tokens,
                    completion_tokens=final_result.completion_tokens,
                    cost_usd=services.model_cost(
                        final_result.model_alias,
                        final_result.prompt_tokens,
                        final_result.completion_tokens,
                    ),
                    trace_id=trace_id,
                    session_id=chat.id,
                    traffic_class=chat.traffic_class,
                    gateway_request_id=final_result.gateway_request_id,
                )
            provisional.graph = "conversation.v1"
            provisional.graph_version = "conversation.v1"
            await runs.complete(
                provisional,
                status="completed",
                result_message_id=assistant.id,
                checkpoint={"intent": intent, "stream": True, "streamed_tokens": True},
            )
            user_texts = [m["content"] for m in history if m.get("role") == "user"]
            await maybe_auto_title(
                services=services,
                chat=chat,
                user_texts=user_texts,
                intent=str(intent),
            )
            await repo.touch(chat)
            await session.commit()
            yield _sse(
                "final",
                {
                    "run_id": str(provisional.id),
                    "assistant_message": _message_out(assistant).model_dump(mode="json"),
                    "red_flag": None,
                    "interrupt": None,
                },
            )
        except ExternalEgressBlocked:
            blocked = await repo.add_message(
                session_id=chat.id,
                role="assistant",
                content="The assistant reply was blocked by privacy policy.",
                language=language,
                sources=[],
                safety={"blocked": True, "code": "egress_blocked"},
                trace_id=trace_id,
            )
            await runs.complete(
                provisional,
                status="failed",
                error_code="egress_blocked",
                result_message_id=blocked.id,
            )
            AuditRepository(session).append(
                actor_subject=context.subject,
                actor_role=context.primary_role.value,
                action="chat.reply_blocked",
                resource_type="chat_session",
                resource_id=str(chat.id),
                patient_id=chat.patient_id,
                trace_id=trace_id,
                metadata={"reason": "egress_blocked", "run_id": str(provisional.id), "stream": True},
            )
            await session.commit()
            yield _sse(
                "error",
                {
                    "run_id": str(provisional.id),
                    "code": "egress_blocked",
                    "detail": "The configured model route is blocked by privacy policy.",
                    "assistant_message": _message_out(blocked).model_dump(mode="json"),
                },
            )
        except LlmGatewayError as exc:
            blocked = await repo.add_message(
                session_id=chat.id,
                role="assistant",
                content="The assistant is temporarily unavailable. Your message was saved.",
                language=language,
                sources=[],
                safety={"blocked": True, "code": "gateway_unavailable"},
                trace_id=trace_id,
            )
            await runs.complete(
                provisional,
                status="failed",
                error_code="gateway_unavailable",
                result_message_id=blocked.id,
            )
            await session.commit()
            yield _sse(
                "error",
                {
                    "run_id": str(provisional.id),
                    "code": "gateway_unavailable",
                    "detail": str(exc) or "The model gateway is unavailable.",
                    "assistant_message": _message_out(blocked).model_dump(mode="json"),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("chat stream failed")
            await runs.complete(provisional, status="failed", error_code="stream_failed")
            await session.commit()
            yield _sse(
                "error",
                {
                    "run_id": str(provisional.id),
                    "code": "stream_failed",
                    "detail": str(exc)[:300] or "Streaming failed.",
                },
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/runs/{run_id}", response_model=ChatRunOut)
async def get_run(
    run_id: uuid.UUID,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> ChatRunOut:
    _ensure_chat_enabled(services)
    run = await ChatRunRepository(session).get_owned(run_id, context.subject)
    if run is None:
        raise ProblemError(404, "run_not_found", "Run not found", "No such chat run.")
    return ChatRunOut.model_validate(run)


@router.post("/runs/{run_id}/stop", response_model=StopResult)
async def stop_run(
    run_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> StopResult:
    """Cancel an in-flight or interrupted run without writing a partial assistant turn."""
    _ensure_chat_enabled(services)
    runs = ChatRunRepository(session)
    run = await runs.get_owned(run_id, context.subject)
    if run is None:
        raise ProblemError(404, "run_not_found", "Run not found", "No such chat run.")
    if run.status in {"completed", "failed", "cancelled"}:
        return StopResult(run_id=run.id, status=run.status)
    if run.status not in {"running", "interrupted"}:
        raise ProblemError(
            409, "run_not_stoppable", "Cannot stop", "This run is not active."
        )
    previous = run.status
    await runs.complete(run, status="cancelled", error_code="stopped_by_user")
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="chat.run_stopped",
        resource_type="chat_run",
        resource_id=str(run.id),
        trace_id=_trace(request),
        metadata={"previous_status": previous},
    )
    await session.commit()
    return StopResult(run_id=run.id, status="cancelled")


@router.post("/runs/{run_id}/retry", response_model=SendResult, status_code=status.HTTP_201_CREATED)
async def retry_run(
    run_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> SendResult:
    """Re-send the user text captured on a prior run as a new turn."""
    _ensure_chat_enabled(services)
    runs = ChatRunRepository(session)
    run = await runs.get_owned(run_id, context.subject)
    if run is None:
        raise ProblemError(404, "run_not_found", "Run not found", "No such chat run.")
    if run.status == "interrupted":
        raise ProblemError(
            409,
            "run_interrupted",
            "Resume or stop first",
            "Interrupted runs must be resumed or stopped before retry.",
        )
    text = str((run.checkpoint or {}).get("user_text") or "").strip()
    if not text:
        prior = await ChatRepository(session).previous_user_message(
            session_id=run.session_id,
            before_message_id=run.result_message_id,
        )
        text = (prior.content if prior else "").strip()
    if not text:
        raise ProblemError(
            409, "retry_unavailable", "Nothing to retry", "No user text was stored for this run."
        )
    return await send_message(
        session_id=run.session_id,
        body=MessageCreate(content=text),
        request=request,
        context=context,
        services=services,
        session=session,
    )


@router.post(
    "/messages/{message_id}/feedback",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    message_id: uuid.UUID,
    body: FeedbackCreate,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> FeedbackOut:
    _ensure_chat_enabled(services)
    repo = ChatRepository(session)
    message = await repo.get_message_owned(message_id, context.subject)
    if message is None:
        raise ProblemError(404, "message_not_found", "Not found", "No such chat message.")
    if message.role != "assistant":
        raise ProblemError(
            422,
            "feedback_target_invalid",
            "Feedback rejected",
            "Feedback is only accepted on assistant messages.",
        )
    existing = await session.scalar(
        select(ChatFeedback).where(
            ChatFeedback.message_id == message_id,
            ChatFeedback.user_subject == context.subject,
        )
    )
    if existing is not None:
        return FeedbackOut.model_validate(existing)

    review_task_id: uuid.UUID | None = None
    if body.rating in {"down", "not_helpful"}:
        chat = await repo.get_owned(message.session_id, context.subject)
        task = ReviewTask(
            patient_id=chat.patient_id if chat else None,
            created_by_subject=context.subject,
            assigned_role="admin",
            reason="chat_negative_feedback",
            status="open",
            owner_subject=None,
            resource_type="chat_message",
            resource_id=str(message.id),
        )
        session.add(task)
        await session.flush()
        review_task_id = task.id

    row = ChatFeedback(
        message_id=message_id,
        user_subject=context.subject,
        rating=body.rating,
        comment=(body.comment or "").strip() or None,
        review_task_id=review_task_id,
    )
    session.add(row)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="feedback.submitted",
        resource_type="chat_message",
        resource_id=str(message_id),
        trace_id=_trace(request),
        metadata={
            "rating": body.rating,
            "review_task_id": str(review_task_id) if review_task_id else None,
            "idempotency_key": body.idempotency_key,
        },
    )
    await session.commit()
    await session.refresh(row)
    return FeedbackOut.model_validate(row)


@router.get("/messages/{message_id}/sources")
async def message_sources(
    message_id: uuid.UUID,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> list[dict[str, Any]]:
    _ensure_chat_enabled(services)
    message = await ChatRepository(session).get_message_owned(message_id, context.subject)
    if message is None:
        raise ProblemError(404, "message_not_found", "Not found", "No such chat message.")
    return list(message.sources or [])


@router.get("/runs/{run_id}/sources")
async def run_sources(
    run_id: uuid.UUID,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> list[dict[str, Any]]:
    _ensure_chat_enabled(services)
    run = await ChatRunRepository(session).get_owned(run_id, context.subject)
    if run is None:
        raise ProblemError(404, "run_not_found", "Run not found", "No such chat run.")
    if run.result_message_id is None:
        return []
    message = await ChatRepository(session).get_message_owned(
        run.result_message_id, context.subject
    )
    if message is None:
        return []
    return list(message.sources or [])


@router.get("/citations/{chunk_id}", response_model=ChunkOut)
async def resolve_citation(
    chunk_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> ChunkOut:
    """Resolve a document chunk citation for the caller’s patient scope."""
    _ensure_chat_enabled(services)
    repo = DocumentRepository(session)
    chunk = await repo.get_chunk(chunk_id)
    if chunk is None:
        raise ProblemError(404, "citation_not_found", "Not found", "No such citation.")
    role = context.primary_role.value
    if role in {"patient", "caregiver"}:
        patient_id = await _patient_scope(context, session)
        if patient_id is None or chunk.patient_id != patient_id:
            raise ProblemError(404, "citation_not_found", "Not found", "No such citation.")
    elif role not in {"doctor", "admin", "compliance"}:
        raise ProblemError(404, "citation_not_found", "Not found", "No such citation.")
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="source.resolved",
        resource_type="document_chunk",
        resource_id=str(chunk.id),
        patient_id=chunk.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    return ChunkOut(
        id=chunk.id,
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        page=chunk.page,
        section=chunk.section,
        content=chunk.content[:4000],
    )


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: uuid.UUID,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> StreamingResponse:
    """SSE snapshot of run status (interrupt or final). Not a live token stream."""
    _ensure_chat_enabled(services)
    run = await ChatRunRepository(session).get_owned(run_id, context.subject)
    if run is None:
        raise ProblemError(404, "run_not_found", "Run not found", "No such chat run.")

    async def event_stream():
        payload: dict[str, Any] = {
            "run_id": str(run.id),
            "status": run.status,
            "graph": run.graph,
            "trace_id": run.trace_id,
        }
        if run.status == "interrupted":
            event = "interrupt"
            payload.update(
                {
                    "interrupt_id": run.interrupt_id,
                    "interrupt_type": run.interrupt_type,
                    "payload": run.interrupt_payload,
                }
            )
        elif run.status == "failed":
            event = "error"
            payload["error_code"] = run.error_code
        else:
            event = "final"
            payload["result_message_id"] = (
                str(run.result_message_id) if run.result_message_id else None
            )
        yield f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"
        await asyncio.sleep(0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/runs/{run_id}/resume", response_model=SendResult)
async def resume_run(
    run_id: uuid.UUID,
    body: ResumeRequest,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> SendResult:
    _ensure_chat_enabled(services)
    runs = ChatRunRepository(session)
    run = await runs.get_owned(run_id, context.subject)
    if run is None:
        raise ProblemError(404, "run_not_found", "Run not found", "No such chat run.")
    if run.status != "interrupted":
        raise ProblemError(
            409, "run_not_interrupted", "Run not interrupted", "This run is not waiting for a choice."
        )
    if not run.interrupt_id or run.interrupt_id != body.interrupt_id:
        raise ProblemError(
            409, "interrupt_mismatch", "Interrupt mismatch", "interrupt_id does not match this run."
        )

    chat = await ChatRepository(session).get_owned(run.session_id, context.subject)
    if chat is None:
        raise ProblemError(404, "session_not_found", "Session not found", "No such chat session.")

    language = normalize_locale(chat.locale)
    trace_id = _trace(request)
    repo = ChatRepository(session)

    if body.command == "cancel":
        await runs.complete(run, status="cancelled")
        user_message = await repo.add_message(
            session_id=chat.id,
            role="user",
            content="Cancel booking choice",
            language=language,
            sources=[],
            trace_id=trace_id,
        )
        assistant = await repo.add_message(
            session_id=chat.id,
            role="assistant",
            content="Booking cancelled. You can ask again when you are ready to choose a doctor.",
            language=language,
            sources=[],
            trace_id=trace_id,
        )
        await repo.touch(chat)
        await session.commit()
        await session.refresh(user_message)
        await session.refresh(assistant)
        return SendResult(
            user_message=_message_out(user_message),
            assistant_message=_message_out(assistant),
            run_id=run.id,
        )

    if body.command not in {
        "slot_choice",
        "doctor_choice",
        "specialty_choice",
        "language_choice",
    }:
        raise ProblemError(
            422,
            "command_unsupported",
            "Unsupported command",
            "Use slot_choice, specialty_choice, language_choice, doctor_choice, or cancel.",
        )

    payload = run.interrupt_payload or {}
    candidates = list(payload.get("candidates") or [])
    checkpoint = run.checkpoint or {}
    durable_thread_id = str(checkpoint.get("thread_id") or "") or None

    async def _resume_langgraph(choice: dict[str, Any]) -> None:
        """Clear LangGraph interrupt checkpoint when durable pause was used (G-46)."""
        if not durable_thread_id or not checkpoint.get("durable_interrupt"):
            return
        try:
            orch = ChatOrchestrator(services, session)
            await orch.w1.resume(thread_id=durable_thread_id, resume_value=choice)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "langgraph resume failed; continuing with chat_runs booking path",
                extra={"event": "chat.langgraph_resume_failed", "run_id": str(run.id)},
                exc_info=exc,
            )

    if body.command == "language_choice":
        chosen_locale: str | None = None
        if body.choice_index is not None:
            index = body.choice_index - 1
            if index < 0 or index >= len(candidates):
                raise ProblemError(
                    422, "choice_invalid", "Invalid choice", "choice_index is out of range."
                )
            chosen_locale = str(candidates[index].get("locale") or candidates[index].get("label") or "")
        elif body.locale:
            chosen_locale = body.locale
        else:
            raise ProblemError(
                422,
                "choice_required",
                "Choice required",
                "Provide choice_index or locale for language_choice.",
            )
        language = normalize_locale(chosen_locale)
        chat.locale = language
        await _resume_langgraph({"command": "language_choice", "locale": language})
        user_text = str(checkpoint.get("user_text") or "").strip()
        user_message = await repo.add_message(
            session_id=chat.id,
            role="user",
            content=f"Language: {language}",
            language=language,
            sources=[],
            trace_id=trace_id,
        )
        if not user_text:
            await runs.complete(run, status="completed", result_message_id=None)
            assistant = await repo.add_message(
                session_id=chat.id,
                role="assistant",
                content=f"Language set to {language}. Please restate your concern.",
                language=language,
                sources=[],
                trace_id=trace_id,
            )
            await repo.touch(chat)
            await session.commit()
            return SendResult(
                user_message=_message_out(user_message),
                assistant_message=_message_out(assistant),
                run_id=run.id,
            )
        # Re-run triage with the confirmed locale (skips language clarify).
        from app.core.security import doctor_schedule_name

        orch = ChatOrchestrator(services, session)
        new_thread = f"w1:{uuid.uuid4().hex[:16]}"
        turn = await orch.handle_turn(
            text=user_text,
            locale=language,
            history=[{"role": "user", "content": user_text}],
            subject=context.subject,
            role=context.primary_role.value,
            patient_id=chat.patient_id,
            clinic_ids=list(context.clinic_ids),
            traffic_class=chat.traffic_class,
            trace_id=trace_id,
            thread_id=new_thread,
            chat_session_id=str(chat.id),
            skip_language_clarify=True,
            fixed_doctor_name=doctor_schedule_name(context),
        )
        assistant = await repo.add_message(
            session_id=chat.id,
            role="assistant",
            content=turn.content,
            language=language,
            sources=_source_refs(turn.sources),
            safety={"language_confirmed": language},
            trace_id=trace_id,
            model_alias=turn.model_alias,
        )
        interrupt_meta = turn.metadata.get("interrupt_type")
        candidates_next = turn.metadata.get("candidates") or []
        if interrupt_meta and candidates_next:
            interrupt_id = f"int_{uuid.uuid4().hex[:16]}"
            await runs.mark_interrupted(
                run,
                graph=turn.graph,
                interrupt_type=str(interrupt_meta),
                interrupt_id=interrupt_id,
                interrupt_payload={
                    "candidates": candidates_next,
                    "specialty_code": turn.metadata.get("specialty_code"),
                    "specialty_label": turn.metadata.get("specialty_label"),
                    "preferred_starts_at": turn.metadata.get("preferred_starts_at"),
                    "clinic_code": (list(context.clinic_ids) or [None])[0],
                    "patient_id": str(chat.patient_id) if chat.patient_id else None,
                    "choice_expires_at": _choice_expires_at(),
                },
                result_message_id=assistant.id,
                checkpoint={
                    "intent": turn.intent,
                    "user_message_id": str(user_message.id),
                    "user_text": user_text,
                    "thread_id": new_thread,
                    "durable_interrupt": bool(turn.metadata.get("durable_interrupt")),
                },
            )
            interrupt_out = InterruptOut(
                run_id=run.id,
                interrupt_id=interrupt_id,
                interrupt_type=str(interrupt_meta),
                payload={
                    "candidates": candidates_next,
                    "specialty_code": turn.metadata.get("specialty_code"),
                    "specialty_label": turn.metadata.get("specialty_label"),
                    "choice_expires_at": _choice_expires_at(),
                },
            )
        else:
            await runs.complete(run, status="completed", result_message_id=assistant.id)
            interrupt_out = None
        AuditRepository(session).append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="chat.language_confirmed",
            resource_type="chat_session",
            resource_id=str(chat.id),
            patient_id=chat.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={"locale": language, "run_id": str(run.id)},
        )
        await repo.touch(chat)
        await session.commit()
        await session.refresh(user_message)
        await session.refresh(assistant)
        return SendResult(
            user_message=_message_out(user_message),
            assistant_message=_message_out(assistant),
            run_id=run.id,
            interrupt=interrupt_out,
        )

    if body.command == "specialty_choice":
        chosen_specialty: dict[str, Any] | None = None
        if body.choice_index is not None:
            index = body.choice_index - 1
            if index < 0 or index >= len(candidates):
                raise ProblemError(
                    422, "choice_invalid", "Invalid choice", "choice_index is out of range."
                )
            chosen_specialty = candidates[index]
        elif body.specialty_code:
            chosen_specialty = next(
                (
                    c
                    for c in candidates
                    if str(c.get("specialty_code") or "").lower() == body.specialty_code.lower()
                ),
                {"specialty_code": body.specialty_code, "specialty_label": body.specialty_code},
            )
        else:
            raise ProblemError(
                422,
                "choice_required",
                "Choice required",
                "Provide choice_index or specialty_code for specialty_choice.",
            )
        specialty_code = str(
            chosen_specialty.get("specialty_code") or body.specialty_code or "general_medicine"
        )
        specialty_label = str(
            chosen_specialty.get("specialty_label")
            or chosen_specialty.get("label")
            or specialty_code
        )
        await _resume_langgraph(
            {
                "command": "specialty_choice",
                "specialty_code": specialty_code,
                "specialty_label": specialty_label,
                "choice_index": body.choice_index,
            }
        )
        clinic_code = str(payload.get("clinic_code") or (list(context.clinic_ids) or ["BANER"])[0])
        now = int(dt.datetime.now(dt.UTC).timestamp())
        try:
            actor_role = CtxRole(context.primary_role.value)
        except ValueError:
            actor_role = CtxRole.PATIENT
        tool_context = ExecutionContext(
            actor_subject=context.subject,
            actor_role=actor_role,
            clinic_ids=tuple(context.clinic_ids or ()),
            patient_id=chat.patient_id,
            trace_id=(trace_id or uuid.uuid4().hex)[:64],
            locale=language if language in {"en-IN", "hi-IN", "mr-IN"} else "en-IN",
            traffic_class="synthetic" if chat.traffic_class == "synthetic" else "real",
            issued_at=now,
            expires_at=now + 120,
        )
        tools = McpToolClient(services.settings)
        from app.agents.booking_prefs import format_slot_label, rank_slots_near_preference
        from app.core.security import doctor_schedule_name

        fixed_doctor = doctor_schedule_name(context)
        slot_pool: list[dict[str, Any]] = []
        try:
            doctors_result = await tools.call(
                context=tool_context,
                graph="triage",
                tool="search_doctors",
                arguments={
                    "specialty_code": specialty_code,
                    "clinic_code": clinic_code,
                    "limit": 3,
                },
                timeout_seconds=8.0,
            )
            doctors = list(doctors_result.get("doctors") or [])
        except ToolUnavailable:
            doctors = []
        if fixed_doctor:
            matched = [
                d
                for d in doctors
                if str(d.get("doctor_name") or d.get("name") or "").strip().lower()
                == fixed_doctor.lower()
            ]
            doctors = matched[:1] or [
                {
                    "doctor_name": fixed_doctor,
                    "clinic_code": clinic_code,
                    "specialty_code": specialty_code,
                }
            ]
        for doctor in doctors[: (1 if fixed_doctor else 3)]:
            name = str(doctor.get("doctor_name") or doctor.get("name") or "").strip()
            clinic = str(doctor.get("clinic_code") or clinic_code).strip()
            if not name or not clinic:
                continue
            try:
                avail = await tools.call(
                    context=tool_context,
                    graph="triage",
                    tool="get_availability",
                    arguments={
                        "doctor_name": name,
                        "clinic_code": clinic,
                        "specialty_code": specialty_code,
                        "days": 7,
                    },
                    timeout_seconds=8.0,
                )
                for item in avail.get("slots") or []:
                    if isinstance(item, dict) and item.get("starts_at"):
                        slot_pool.append(
                            {
                                "starts_at": item["starts_at"],
                                "doctor_name": name,
                                "clinic_code": clinic,
                                "specialty_code": specialty_code,
                                "duration_minutes": int(item.get("duration_minutes") or 20),
                            }
                        )
            except ToolUnavailable:
                continue
        ranked = rank_slots_near_preference(slot_pool, None, limit=6)
        clock = dt.datetime.now(CLINIC_TZ)
        slot_candidates: list[dict[str, Any]] = []
        for slot in ranked:
            starts_iso = str(slot["starts_at"])
            try:
                starts = dt.datetime.fromisoformat(starts_iso.replace("Z", "+00:00"))
                if starts.tzinfo is None:
                    starts = starts.replace(tzinfo=CLINIC_TZ)
                else:
                    starts = starts.astimezone(CLINIC_TZ)
                starts_iso = starts.isoformat()
            except ValueError:
                continue
            slot_candidates.append(
                {
                    "doctor_name": slot["doctor_name"],
                    "clinic_code": slot["clinic_code"],
                    "specialty_code": specialty_code,
                    "starts_at": starts_iso,
                    "duration_minutes": slot.get("duration_minutes") or 20,
                    "label": format_slot_label(
                        doctor_name=str(slot["doctor_name"]),
                        clinic_code=str(slot["clinic_code"]),
                        starts_at=starts,
                        now=clock,
                    ),
                }
            )
        if not slot_candidates:
            assistant = await repo.add_message(
                session_id=chat.id,
                role="assistant",
                content=(
                    f"Confirmed specialty **{specialty_label}**, but no open slots were found. "
                    "Please try another day or ask the front desk."
                ),
                language=language,
                sources=[],
                trace_id=trace_id,
            )
            await runs.complete(run, status="completed", result_message_id=assistant.id)
            await repo.touch(chat)
            await session.commit()
            await session.refresh(assistant)
            return SendResult(
                user_message=_message_out(assistant),
                assistant_message=_message_out(assistant),
                run_id=run.id,
            )
        lines = [
            f"Specialty confirmed: **{specialty_label}**. Pick a specific open slot:",
        ]
        for index, candidate in enumerate(slot_candidates, start=1):
            lines.append(f"{index}. {candidate['label']}")
        assistant = await repo.add_message(
            session_id=chat.id,
            role="assistant",
            content="\n".join(lines),
            language=language,
            sources=[],
            trace_id=trace_id,
        )
        new_interrupt_id = f"int_{uuid.uuid4().hex[:16]}"
        await runs.reinterrupt(
            run,
            interrupt_type="slot_choice",
            interrupt_id=new_interrupt_id,
            interrupt_payload={
                "candidates": slot_candidates,
                "specialty_code": specialty_code,
                "specialty_label": specialty_label,
                "clinic_code": clinic_code,
                "patient_id": str(chat.patient_id) if chat.patient_id else None,
                "choice_expires_at": _choice_expires_at(),
            },
            result_message_id=assistant.id,
            checkpoint={"specialty_confirmed": specialty_code},
        )
        await repo.touch(chat)
        await session.commit()
        await session.refresh(assistant)
        return SendResult(
            user_message=_message_out(assistant),
            assistant_message=_message_out(assistant),
            run_id=run.id,
            interrupt=InterruptOut(
                run_id=run.id,
                interrupt_id=new_interrupt_id,
                interrupt_type="slot_choice",
                payload={
                    "candidates": slot_candidates,
                    "specialty_code": specialty_code,
                    "specialty_label": specialty_label,
                    "choice_expires_at": _choice_expires_at(),
                },
            ),
        )

    chosen: dict[str, Any] | None = None
    if body.choice_index is not None:
        index = body.choice_index - 1
        if index < 0 or index >= len(candidates):
            raise ProblemError(
                422, "choice_invalid", "Invalid choice", "choice_index is out of range."
            )
        chosen = candidates[index]
    elif body.doctor_name and body.starts_at is not None:
        chosen = {
            "doctor_name": body.doctor_name,
            "clinic_code": body.clinic_code or payload.get("clinic_code"),
            "specialty_code": body.specialty_code or payload.get("specialty_code"),
            "starts_at": body.starts_at.isoformat(),
        }
    elif body.doctor_name:
        chosen = next(
            (
                c
                for c in candidates
                if str(c.get("doctor_name") or c.get("name") or "").lower()
                == body.doctor_name.lower()
            ),
            None,
        )
        if chosen is None:
            raise ProblemError(
                422,
                "choice_required",
                "Choice required",
                "Doctor not in shortlist; provide choice_index or starts_at.",
            )
    else:
        raise ProblemError(
            422,
            "choice_required",
            "Choice required",
            "Provide choice_index (preferred) or doctor_name with starts_at.",
        )

    doctor_name = str(chosen.get("doctor_name") or chosen.get("name") or "")
    clinic_code = str(
        body.clinic_code or chosen.get("clinic_code") or payload.get("clinic_code") or "BANER"
    )
    specialty_code = str(
        body.specialty_code
        or chosen.get("specialty_code")
        or payload.get("specialty_code")
        or "general_medicine"
    )
    starts_raw = body.starts_at or chosen.get("starts_at") or chosen.get("next_slot")
    if starts_raw is None:
        raise ProblemError(
            422,
            "slot_required",
            "Slot required",
            "Pick a discrete starts_at from the availability shortlist.",
        )
    if isinstance(starts_raw, str):
        starts_at = dt.datetime.fromisoformat(starts_raw.replace("Z", "+00:00"))
    else:
        starts_at = starts_raw
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=CLINIC_TZ)

    await _resume_langgraph(
        {
            "command": body.command,
            "doctor_name": doctor_name,
            "clinic_code": clinic_code,
            "specialty_code": specialty_code,
            "starts_at": starts_at.isoformat(),
            "choice_index": body.choice_index,
        }
    )

    patient_id = chat.patient_id
    if payload.get("patient_id") and patient_id is None:
        patient_id = uuid.UUID(str(payload["patient_id"]))

    appt_repo = AppointmentRepository(session)
    idem_scope = f"chat_run:{run.id}"
    idem_key = (body.idempotency_key or "").strip() or f"slot:{doctor_name}:{clinic_code}:{starts_at.isoformat()}"
    existing = await appt_repo.get_idempotent(scope=idem_scope, key=idem_key)
    if existing is not None:
        appointment = existing
    else:
        now = int(dt.datetime.now(dt.UTC).timestamp())
        try:
            actor_role = CtxRole(context.primary_role.value)
        except ValueError:
            actor_role = CtxRole.PATIENT
        tool_context = ExecutionContext(
            actor_subject=context.subject,
            actor_role=actor_role,
            clinic_ids=tuple(context.clinic_ids or ()),
            patient_id=patient_id,
            trace_id=(trace_id or uuid.uuid4().hex)[:64],
            locale=language if language in {"en-IN", "hi-IN", "mr-IN"} else "en-IN",
            traffic_class="synthetic" if chat.traffic_class == "synthetic" else "real",
            issued_at=now,
            expires_at=now + 120,
        )
        tools = McpToolClient(services.settings)
        try:
            held = await tools.call(
                context=tool_context,
                graph="triage",
                tool="hold_slot",
                arguments={
                    "doctor_name": doctor_name,
                    "clinic_code": clinic_code,
                    "specialty_code": specialty_code,
                    "starts_at": starts_at.isoformat(),
                    "duration_minutes": int(chosen.get("duration_minutes") or 20),
                    "patient_id": str(patient_id) if patient_id else None,
                    "source": "assistant",
                },
                timeout_seconds=15.0,
            )
            if body.confirm:
                appt_id = (held.get("appointment") or {}).get("id")
                if not appt_id:
                    raise ProblemError(
                        502,
                        "hold_incomplete",
                        "Hold incomplete",
                        "Scheduling hold did not return an appointment id.",
                    )
                confirmed = await tools.call(
                    context=tool_context,
                    graph="triage",
                    tool="confirm_booking",
                    arguments={"appointment_id": str(appt_id)},
                    timeout_seconds=15.0,
                )
                appt_payload = confirmed.get("appointment") or held.get("appointment") or {}
            else:
                appt_payload = held.get("appointment") or {}
        except ToolUnavailable as exc:
            raise ProblemError(
                503,
                "scheduling_unavailable",
                "Scheduling unavailable",
                f"Could not book via scheduling tools ({exc.code}).",
            ) from exc
        except ValueError as exc:
            raise ProblemError(
                409,
                "slot_taken",
                "Slot unavailable",
                str(exc)[:300] or "That slot could not be held.",
            ) from exc

        appt_id_raw = appt_payload.get("id")
        if not appt_id_raw:
            raise ProblemError(
                502,
                "booking_incomplete",
                "Booking incomplete",
                "Scheduling tools did not return an appointment.",
            )
        # MCP hold/confirm commit on their own sessions; reload in this session.
        await session.commit()
        appointment = await appt_repo.get(uuid.UUID(str(appt_id_raw)))
        if appointment is None:
            raise ProblemError(
                502,
                "booking_missing",
                "Booking missing",
                "Appointment was created but could not be reloaded.",
            )
        await appt_repo.remember_idempotent(
            scope=idem_scope, key=idem_key, appointment_id=appointment.id
        )

    confirmed = appointment.status == "confirmed"
    # Notify only after a hard confirm (hold-only waits for booking card confirm).
    if confirmed and appointment.patient_id is not None:
        patient = await PatientRepository(session).get(appointment.patient_id)
        if patient is not None and patient.keycloak_subject:
            starts_label = appointment.starts_at.astimezone(CLINIC_TZ).strftime(
                "%d %b %Y, %I:%M %p"
            )
            try:
                await NotificationService(services, session).send(
                    template_id="booking_confirmed",
                    recipient_subject=patient.keycloak_subject,
                    recipient_role="patient",
                    patient_id=appointment.patient_id,
                    locale=language,
                    data={
                        "doctor_name": appointment.doctor_name,
                        "clinic_code": appointment.clinic_code,
                        "starts_at": starts_label,
                        "starts_at_iso": appointment.starts_at.astimezone(dt.UTC).isoformat(),
                        "duration_minutes": str(appointment.duration_minutes),
                        "appointment_id": str(appointment.id),
                    },
                    actor_subject=context.subject,
                    actor_role="service",
                    trace_id=trace_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "chat booking notification skipped",
                    extra={"event": "notification.skipped"},
                    exc_info=exc,
                )

    local_start = appointment.starts_at.astimezone(CLINIC_TZ)
    held_out = _held_appointment_out(appointment)
    if confirmed:
        content = (
            f"Confirmed **{appointment.doctor_name}** · {appointment.clinic_code} · "
            f"{local_start.strftime('%a %d %b, %I:%M %p').lstrip('0')} "
            f"(status={appointment.status}). Appointment id `{appointment.id}`."
        )
    else:
        expires_label = held_out.hold_expires_at.astimezone(CLINIC_TZ).strftime("%I:%M %p")
        content = (
            f"Held **{appointment.doctor_name}** · {appointment.clinic_code} · "
            f"{local_start.strftime('%a %d %b, %I:%M %p').lstrip('0')} "
            f"until {expires_label.lstrip('0')}. Confirm to finish booking "
            f"(appointment id `{appointment.id}`)."
        )
    assistant = await repo.add_message(
        session_id=chat.id,
        role="assistant",
        content=content,
        language=language,
        sources=[
            SourceRef(
                id=f"scheduling:{appointment.id}",
                type=SourceType.TOOL,
                title="Scheduling hold/confirm",
                locator=str(appointment.id),
                metadata={"system": "scheduling", "via": "mcp"},
            )
        ],
        trace_id=trace_id,
    )
    await runs.complete(
        run,
        status="completed",
        result_message_id=assistant.id,
        checkpoint={
            "appointment_id": str(appointment.id),
            "doctor_name": appointment.doctor_name,
            "starts_at": appointment.starts_at.isoformat(),
            "idempotency_key": idem_key,
            "via": "mcp_hold_confirm",
            "confirmed": confirmed,
            "hold_expires_at": held_out.hold_expires_at.isoformat(),
        },
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="chat.run_resumed",
        resource_type="chat_run",
        resource_id=str(run.id),
        patient_id=patient_id,
        consent_id=context.consent_id,
        trace_id=trace_id,
        metadata={
            "appointment_id": str(appointment.id),
            "command": body.command,
            "status": appointment.status,
            "via": "mcp_hold_confirm",
            "confirmed": confirmed,
        },
    )
    await repo.touch(chat)
    await session.commit()
    await session.refresh(assistant)
    return SendResult(
        user_message=_message_out(assistant),
        assistant_message=_message_out(assistant),
        run_id=run.id,
        appointment=held_out if not confirmed else None,
    )
