"""X-01 bounded nursing shift summary with draft versioning (flag-gated)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sahyog_common.errors import ProblemError
from sahyog_common.provenance import SourceRef, SourceType
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.w2_ask_graph import W2AskGraph
from app.core.db import get_session
from app.core.security import AuthContext, Role, require_roles
from app.core.services import Services, get_services
from app.modules.records.ingest import embed_query
from app.repositories.audit import AuditRepository
from app.repositories.models import NursingSummary
from app.repositories.patients import PatientRepository
from app.repositories.records import DocumentRepository

router = APIRouter(prefix="/api/v1/nursing", tags=["nursing"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[Services, Depends(get_services)]
ClinicianDep = Annotated[
    AuthContext,
    Depends(require_roles(Role.DOCTOR, Role.FRONT_DESK, Role.ADMIN, Role.PHARMACIST)),
]


class NursingSummaryRequest(BaseModel):
    patient_id: uuid.UUID
    query: str = Field(
        default="Summarise this shift handover from the record only.",
        min_length=3,
        max_length=2000,
    )
    locale: str = "en-IN"


class NursingSummaryOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    version: int
    status: str
    summary: str
    sources: list[dict[str, Any]]
    graph: str
    model_alias: str | None = None
    draft_only: bool = True
    decided_by: str | None = None
    decided_at: dt.datetime | None = None
    decision_note: str | None = None


class NursingDecisionRequest(BaseModel):
    decision: Literal["accept", "edit", "reject"]
    summary: str | None = Field(default=None, max_length=20000)
    note: str | None = Field(default=None, max_length=500)


def _require_feature(services: Services) -> None:
    if not services.features.enabled("x01_nursing_summary"):
        raise ProblemError(
            403,
            "feature_disabled",
            "Nursing summary unavailable",
            "X-01 nursing summary is disabled by configuration.",
        )


def _to_out(row: NursingSummary) -> NursingSummaryOut:
    return NursingSummaryOut(
        id=row.id,
        patient_id=row.patient_id,
        version=row.version,
        status=row.status,
        summary=row.summary,
        sources=list(row.sources or []),
        graph=row.graph,
        model_alias=row.model_alias,
        draft_only=row.status == "draft",
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        decision_note=row.decision_note,
    )


@router.post("/summary", response_model=NursingSummaryOut)
async def nursing_summary(
    body: NursingSummaryRequest,
    context: ClinicianDep,
    services: ServicesDep,
    session: SessionDep,
) -> NursingSummaryOut:
    _require_feature(services)
    if not await PatientRepository(session).exists(body.patient_id):
        raise ProblemError(404, "patient_not_found", "Not found", "No such patient.")

    async def retrieve(question: str, patient_id: uuid.UUID, *, top_k: int = 8):
        try:
            embedding = await embed_query(services, question)
        except Exception:  # noqa: BLE001
            return [], []
        from app.modules.records.query_expand import expand_query_terms

        from app.core.rls import set_patient_rls

        await set_patient_rls(session, patient_id)
        rows = await DocumentRepository(session).search(
            patient_id=patient_id,
            embedding=embedding,
            limit=top_k,
            query_text=question,
            query_terms=expand_query_terms(question),
        )
        evidence = []
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

    graph = W2AskGraph(
        settings=services.settings,
        models_config=services.models_config,
        prompt=services.prompt("records_answer"),
        retrieve=retrieve,
        checkpointer=getattr(services, "checkpointer", None),
    )
    turn = await graph.run(
        question=(
            "Produce a brief nursing shift handover summary from the record only. "
            "Cite chunk IDs. Do not invent vitals or events. "
            f"Focus: {body.query}"
        ),
        locale=body.locale,
        patient_id=body.patient_id,
    )

    next_version = (
        await session.scalar(
            select(func.coalesce(func.max(NursingSummary.version), 0)).where(
                NursingSummary.patient_id == body.patient_id
            )
        )
        or 0
    ) + 1
    row = NursingSummary(
        patient_id=body.patient_id,
        version=next_version,
        status="draft",
        summary=turn.content,
        sources=list(turn.sources or []),
        graph="x01_nursing.v1",
        model_alias=turn.model_alias,
        created_by=context.subject,
    )
    session.add(row)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="nursing.summary_drafted",
        resource_type="nursing_summary",
        resource_id=str(row.id),
        patient_id=body.patient_id,
        metadata={"graph": "x01_nursing.v1", "sources": len(turn.sources), "version": next_version},
    )
    await session.commit()
    await session.refresh(row)
    return _to_out(row)


@router.get("/summaries/{summary_id}", response_model=NursingSummaryOut)
async def get_nursing_summary(
    summary_id: uuid.UUID,
    context: ClinicianDep,
    services: ServicesDep,
    session: SessionDep,
) -> NursingSummaryOut:
    _require_feature(services)
    row = await session.get(NursingSummary, summary_id)
    if row is None:
        raise ProblemError(404, "nursing_summary_not_found", "Not found", "No such summary.")
    return _to_out(row)


@router.get("/patients/{patient_id}/summaries", response_model=list[NursingSummaryOut])
async def list_nursing_summaries(
    patient_id: uuid.UUID,
    context: ClinicianDep,
    services: ServicesDep,
    session: SessionDep,
) -> list[NursingSummaryOut]:
    _require_feature(services)
    result = await session.execute(
        select(NursingSummary)
        .where(NursingSummary.patient_id == patient_id)
        .order_by(NursingSummary.version.desc())
        .limit(50)
    )
    return [_to_out(row) for row in result.scalars().all()]


@router.post("/summaries/{summary_id}/decision", response_model=NursingSummaryOut)
async def decide_nursing_summary(
    summary_id: uuid.UUID,
    body: NursingDecisionRequest,
    context: ClinicianDep,
    services: ServicesDep,
    session: SessionDep,
) -> NursingSummaryOut:
    """Human-in-the-loop accept / edit / reject. Edits create a new version."""
    _require_feature(services)
    row = await session.get(NursingSummary, summary_id)
    if row is None:
        raise ProblemError(404, "nursing_summary_not_found", "Not found", "No such summary.")
    if row.status != "draft":
        raise ProblemError(
            409,
            "nursing_summary_not_draft",
            "Already decided",
            "Only draft summaries can be decided.",
        )

    now = dt.datetime.now(dt.UTC)
    if body.decision == "accept":
        row.status = "accepted"
        row.decided_by = context.subject
        row.decided_at = now
        row.decision_note = body.note
        decided = row
    elif body.decision == "reject":
        row.status = "rejected"
        row.decided_by = context.subject
        row.decided_at = now
        row.decision_note = body.note
        decided = row
    else:
        edited_text = (body.summary or "").strip()
        if not edited_text:
            raise ProblemError(
                422,
                "nursing_edit_required",
                "Edit text required",
                "Provide summary text when deciding edit.",
            )
        row.status = "rejected"
        row.decided_by = context.subject
        row.decided_at = now
        row.decision_note = body.note or "superseded_by_edit"
        existing = await session.scalar(
            select(func.max(NursingSummary.version)).where(
                NursingSummary.patient_id == row.patient_id
            )
        )
        next_version = int(existing or row.version) + 1
        decided = NursingSummary(
            patient_id=row.patient_id,
            version=next_version,
            status="edited",
            summary=edited_text,
            sources=list(row.sources or []),
            graph=row.graph,
            model_alias=row.model_alias,
            created_by=context.subject,
            decided_by=context.subject,
            decided_at=now,
            decision_note=body.note,
        )
        session.add(decided)

    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action=f"nursing.summary_{body.decision}",
        resource_type="nursing_summary",
        resource_id=str(decided.id),
        patient_id=row.patient_id,
        metadata={"decision": body.decision, "version": decided.version},
    )
    await session.commit()
    await session.refresh(decided)
    return _to_out(decided)
