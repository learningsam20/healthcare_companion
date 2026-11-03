"""Consultation encounters, transcripts, drafts and signatures.

Drafts live in scribe tables and are never patient-visible. A clinical note row is
created only by an explicit doctor signature. Signed versions are immutable; a
correction appends a new version with a parent link and content hash.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

from app.agents.mcp_client import McpToolClient
from app.agents.scribe_graph import ScribeDraftGraph, ScribeOutcome
from app.core.security import AuthContext, Role
from app.core.services import Services
from app.modules.notifications.service import NotificationService
from app.modules.scribe.grounding import (
    DraftRejected,
    content_hash,
    ground_draft,
    load_schema,
    validate_structure,
)
from app.modules.scribe.medicine_match import align_draft_medicines
from app.modules.scribe.schemas import (
    AudioUploadOut,
    AudioUploadRequest,
    CorrectionRequest,
    DraftEditRequest,
    DraftOut,
    EncounterCreate,
    EncounterOut,
    NoteOut,
    NoteVersionOut,
    RejectRequest,
    ScribeRunOut,
    SignatureOut,
    SignRequest,
    SourceOut,
    StockReservationOut,
    StockReservationRequest,
    TranscriptCreate,
    TranscriptOut,
    TranscriptTurnOut,
)
from app.modules.scribe.stock_enrichment import enrich_medicines, stock_status
from app.modules.scribe.transcript_continue import continued_turns
from app.repositories.audit import AuditRepository
from app.repositories.models import (
    ClinicalNote,
    ClinicalNoteVersion,
    Encounter,
    NoteSource,
    ReviewTask,
    ScribeDraft,
    ScribeRun,
    ScribeSource,
    StockReservation,
    Transcript,
    TranscriptTurn,
)
from app.repositories.patients import PatientRepository
from app.repositories.scribe import (
    EncounterRepository,
    NoteRepository,
    ScribeRepository,
    TranscriptRepository,
)
from app.repositories.usage import UsageRepository
from sahyog_common.context import ExecutionContext
from sahyog_common.context import Role as ToolRole
from sahyog_common.errors import ProblemError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

AUDIO_TYPES = {
    "audio/webm": "webm",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/ogg": "ogg",
}
SIGNED_STATUSES = {"signed", "amended"}


def _problem(status: int, code: str, detail: str) -> ProblemError:
    return ProblemError(status, code, "Consultation request rejected", detail)


def _strip_stock(content: dict[str, Any]) -> dict[str, Any]:
    copied = {**content}
    medicines = []
    for medicine in content.get("medicines", []):
        medicines.append({key: value for key, value in medicine.items() if key != "stock"})
    copied["medicines"] = medicines
    return copied


class ScribeService:
    def __init__(self, services: Services, session: AsyncSession) -> None:
        self._services = services
        self._session = session
        self._encounters = EncounterRepository(session)
        self._transcripts = TranscriptRepository(session)
        self._scribe = ScribeRepository(session)
        self._notes = NoteRepository(session)
        self._patients = PatientRepository(session)
        self._audit = AuditRepository(session)
        self._schema = load_schema(services.settings.config_dir)
        self._tools = McpToolClient(services.settings)
        self._graph = ScribeDraftGraph(
            settings=services.settings,
            models_config=services.models_config,
            red_flags_config=services.red_flags,
            prompt=services.prompt("scribe"),
            config_dir=services.settings.config_dir,
            tool_client=self._tools,
            stock_source=str(services.stock_config.get("source_label", "stock")),
            checkpointer=getattr(services, "checkpointer", None),
            medicine_search=self._search_catalog,
        )

    async def _search_catalog(self, terms: list[str], clinic_code: str) -> list[dict[str, str]]:
        from app.repositories.stock import StockRepository

        rows = await StockRepository(self._session).match_terms(terms, clinic_code=clinic_code)
        return [
            {"name": row.drug_name, "form": row.form or "", "strength": row.strength or ""}
            for row in rows
        ]

    def _tool_context(
        self, context: AuthContext, encounter: Encounter, trace_id: str | None
    ) -> ExecutionContext:
        now = int(dt.datetime.now(dt.UTC).timestamp())
        role = ToolRole(context.primary_role.value)
        return ExecutionContext(
            actor_subject=context.subject,
            actor_role=role,
            patient_id=encounter.patient_id,
            clinic_ids=(encounter.clinic_code,),
            trace_id=(trace_id or uuid.uuid4().hex)[:64],
            locale=context.locale if context.locale in {"en-IN", "hi-IN", "mr-IN"} else "en-IN",
            traffic_class="synthetic" if context.traffic_class == "synthetic" else "real",
            issued_at=now,
            expires_at=now + 60,
        )

    def _require_doctor(self, context: AuthContext) -> None:
        if context.primary_role is not Role.DOCTOR:
            raise _problem(403, "doctor_only", "Only a doctor can use the scribe console.")

    async def _doctor_encounter(
        self, context: AuthContext, encounter_id: uuid.UUID, *, lock: bool = False
    ) -> Encounter:
        self._require_doctor(context)
        encounter = (
            await self._session.get(Encounter, encounter_id, with_for_update=True)
            if lock
            else await self._encounters.get(encounter_id)
        )
        if encounter is None or encounter.doctor_subject != context.subject:
            raise _problem(404, "encounter_not_found", "No such encounter.")
        return encounter

    async def _patient_name(self, patient_id: uuid.UUID) -> str | None:
        patient = await self._patients.get(patient_id)
        return patient.display_name if patient else None

    async def _encounter_out(self, encounter: Encounter) -> EncounterOut:
        latest = await self._scribe.latest_run(encounter.id)
        note = await self._notes.for_encounter(encounter.id)
        return EncounterOut(
            id=encounter.id,
            patient_id=encounter.patient_id,
            patient_display_name=await self._patient_name(encounter.patient_id),
            doctor_subject=encounter.doctor_subject,
            doctor_name=encounter.doctor_name,
            clinic_code=encounter.clinic_code,
            appointment_id=encounter.appointment_id,
            kind=encounter.kind,
            status=encounter.status,
            started_at=encounter.started_at,
            ended_at=encounter.ended_at,
            latest_run_id=latest.id if latest else None,
            latest_run_status=latest.status if latest else None,
            note_id=note.id if note else None,
        )

    async def start_encounter(
        self, context: AuthContext, body: EncounterCreate, trace_id: str | None
    ) -> EncounterOut:
        self._require_doctor(context)
        if body.kind == "scheduled":
            assert body.appointment_id is not None
            existing = await self._encounters.for_appointment(body.appointment_id)
            if existing is not None:
                return await self._encounter_out(existing)
            appointment = await self._encounters.appointment(body.appointment_id)
            if appointment is None or appointment.patient_id is None:
                raise _problem(404, "appointment_not_found", "No such appointment.")
            if appointment.status in {"cancelled", "no_show"}:
                raise _problem(409, "appointment_inactive", "This appointment is not active.")
            if appointment.clinic_code not in context.clinic_ids:
                raise _problem(403, "forbidden", "The appointment is outside your clinic scope.")
            patient_id = appointment.patient_id
            doctor_name = appointment.doctor_name
            clinic_code = appointment.clinic_code
        else:
            assert body.patient_id is not None
            if not context.clinic_ids:
                raise _problem(403, "clinic_scope_missing", "A doctor needs a clinic assignment.")
            if not await self._patients.exists(body.patient_id):
                raise _problem(404, "patient_not_found", "No such patient.")
            patient_id = body.patient_id
            doctor_name = (body.doctor_name or "").strip()
            if not doctor_name and context.doctor_display_name:
                doctor_name = context.doctor_display_name.strip()
            if not doctor_name and context.display_name:
                name = context.display_name.strip()
                doctor_name = name if name.lower().startswith("dr") else f"Dr. {name}"
            if not doctor_name:
                raise _problem(422, "doctor_name_required", "A walk-in needs the treating doctor.")
            clinic_code = context.clinic_ids[0]
        encounter = Encounter(
            patient_id=patient_id,
            doctor_subject=context.subject,
            doctor_name=doctor_name[:120],
            clinic_code=clinic_code,
            appointment_id=body.appointment_id,
            kind=body.kind,
            status="active",
            traffic_class=context.traffic_class,
        )
        await self._encounters.create(encounter)
        await self._transcripts.create(
            Transcript(
                encounter_id=encounter.id,
                status="ready",
                source="manual",
                language="en-IN",
                duration_ms=0,
            )
        )
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="encounter.started",
            resource_type="encounter",
            resource_id=str(encounter.id),
            patient_id=encounter.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={"kind": encounter.kind, "clinic_code": encounter.clinic_code},
        )
        return await self._encounter_out(encounter)

    async def get_encounter(self, context: AuthContext, encounter_id: uuid.UUID) -> EncounterOut:
        encounter = await self._doctor_encounter(context, encounter_id)
        return await self._encounter_out(encounter)

    async def list_encounters(
        self,
        context: AuthContext,
        *,
        query: str | None,
        status: str | None,
        sort: str,
        descending: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[EncounterOut], int]:
        self._require_doctor(context)
        rows, total = await self._encounters.list_grid(
            doctor_subject=context.subject,
            clinic_scope=context.clinic_ids,
            status=status,
            query=query,
            sort=sort,
            descending=descending,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        items = [
            EncounterOut(
                id=encounter.id,
                patient_id=encounter.patient_id,
                patient_display_name=display_name,
                doctor_subject=encounter.doctor_subject,
                doctor_name=encounter.doctor_name,
                clinic_code=encounter.clinic_code,
                appointment_id=encounter.appointment_id,
                kind=encounter.kind,
                status=encounter.status,
                started_at=encounter.started_at,
                ended_at=encounter.ended_at,
                latest_run_id=run_id,
                latest_run_status=run_status,
                note_id=note_id,
            )
            for encounter, display_name, run_id, run_status, note_id in rows
        ]
        return items, total

    async def close_encounter(
        self, context: AuthContext, encounter_id: uuid.UUID, trace_id: str | None
    ) -> EncounterOut:
        encounter = await self._doctor_encounter(context, encounter_id)
        if encounter.status == "active":
            latest = await self._scribe.latest_run(encounter.id)
            if latest is not None and latest.status in {"running", "draft", "blocked"}:
                raise _problem(
                    409,
                    "scribe_run_active",
                    "Finish, reject or park the open draft before closing the encounter.",
                )
            await self._encounters.close(encounter)
            self._audit.append(
                actor_subject=context.subject,
                actor_role=context.primary_role.value,
                action="encounter.closed",
                resource_type="encounter",
                resource_id=str(encounter.id),
                patient_id=encounter.patient_id,
                consent_id=context.consent_id,
                trace_id=trace_id,
            )
        return await self._encounter_out(encounter)

    async def upload_transcript(
        self,
        context: AuthContext,
        encounter_id: uuid.UUID,
        body: TranscriptCreate,
        trace_id: str | None,
    ) -> TranscriptOut:
        encounter = await self._doctor_encounter(context, encounter_id)
        if await self._notes.for_encounter(encounter.id):
            raise _problem(409, "note_signed", "A signed note already exists for this encounter.")
        latest = await self._scribe.latest_run(encounter.id)
        if latest is not None and latest.status in {"running", "draft", "blocked"}:
            raise _problem(409, "scribe_run_active", "Finish or reject the current draft first.")
        # Keep the encounter transcript. A later save, including one after the
        # doctor rejects a draft, appends turns instead of replacing them.
        existing = await self._transcripts.latest_for_encounter(encounter.id)
        prior: list[Any] = []
        if existing is not None and existing.status == "ready":
            transcript = existing
            prior = await self._transcripts.turns(existing.id)
            if prior and transcript.language != body.language:
                transcript.language = "mixed"
            else:
                transcript.language = body.language
        else:
            transcript = Transcript(
                encounter_id=encounter.id,
                status="ready",
                source="manual",
                language=body.language,
                duration_ms=body.duration_ms,
            )
            await self._transcripts.create(transcript)
        incoming = [(turn.speaker, turn.text.strip()) for turn in body.turns]
        saved = [(turn.speaker, turn.text.strip()) for turn in prior]
        if continued_turns(saved, incoming) is None:
            return await self._transcript_out(transcript)
        offset = prior[-1].end_ms if prior else 0
        base = prior[-1].turn_index + 1 if prior else 0
        turns = [
            TranscriptTurn(
                transcript_id=transcript.id,
                turn_index=base + index,
                speaker=turn.speaker,
                start_ms=offset + turn.start_ms,
                end_ms=offset + max(turn.end_ms, turn.start_ms),
                text=turn.text,
                language=turn.language or body.language,
            )
            for index, turn in enumerate(body.turns)
        ]
        if turns:
            transcript.duration_ms = turns[-1].end_ms or transcript.duration_ms
        await self._transcripts.add_turns(transcript.id, turns)
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="transcript.uploaded",
            resource_type="transcript",
            resource_id=str(transcript.id),
            patient_id=encounter.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={"turns": len(turns), "source": "manual", "language": body.language},
        )
        return await self._transcript_out(transcript)

    async def _transcript_out(self, transcript: Transcript) -> TranscriptOut:
        turns = await self._transcripts.turns(transcript.id)
        result = TranscriptOut.model_validate(transcript)
        result.turns = [TranscriptTurnOut.model_validate(turn) for turn in turns]
        return result

    async def start_audio_upload(
        self,
        context: AuthContext,
        encounter_id: uuid.UUID,
        body: AudioUploadRequest,
        trace_id: str | None,
    ) -> AudioUploadOut:
        encounter = await self._doctor_encounter(context, encounter_id)
        if not self._services.settings.s3_configured:
            raise _problem(503, "storage_unconfigured", "Audio upload is not configured.")
        if await self._notes.for_encounter(encounter.id):
            raise _problem(409, "note_signed", "A signed note already exists for this encounter.")
        suffix = AUDIO_TYPES[body.content_type]
        key = f"audio/{encounter.clinic_code}/{encounter.id}/{uuid.uuid4()}.{suffix}"
        transcript = Transcript(
            encounter_id=encounter.id,
            status="uploaded",
            source="audio",
            language="mixed",
            object_key=key,
        )
        await self._transcripts.create(transcript)
        try:
            upload_url = await self._services.storage.presign_put(
                key=key,
                content_type=body.content_type,
                bucket=self._services.settings.s3_bucket_audio,
                expires_seconds=300,
            )
        except Exception as exc:  # noqa: BLE001 - storage boundary
            raise _problem(503, "storage_unavailable", "Audio storage is unavailable.") from exc
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="transcript.audio_upload_started",
            resource_type="transcript",
            resource_id=str(transcript.id),
            patient_id=encounter.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={"content_type": body.content_type, "size_bytes": body.size_bytes},
        )
        return AudioUploadOut(
            transcript_id=transcript.id, upload_url=upload_url, expires_in_seconds=300
        )

    async def complete_audio_upload(
        self,
        context: AuthContext,
        encounter_id: uuid.UUID,
        transcript_id: uuid.UUID,
        trace_id: str | None,
    ) -> TranscriptOut:
        encounter = await self._doctor_encounter(context, encounter_id)
        transcript = await self._transcripts.get(transcript_id)
        if (
            transcript is None
            or transcript.encounter_id != encounter.id
            or transcript.source != "audio"
        ):
            raise _problem(404, "transcript_not_found", "No such audio transcript.")
        if transcript.status == "ready":
            return await self._transcript_out(transcript)
        if transcript.status not in {"uploaded", "failed"}:
            raise _problem(409, "transcript_not_uploadable", "This transcript cannot be processed.")
        if transcript.scan_status == "infected":
            raise _problem(409, "transcript_quarantined", "This audio file was quarantined.")
        if transcript.object_key and transcript.scan_status not in {"clean", "disabled"}:
            try:
                audio = await self._services.storage.get(
                    key=transcript.object_key,
                    bucket=self._services.settings.s3_bucket_audio,
                )
            except Exception:  # noqa: BLE001 - storage boundary
                await self._transcripts.set_status(
                    transcript, status="failed", error_code="audio_unreadable"
                )
                return await self._transcript_out(transcript)
            verdict = await self._services.malware.scan(audio)
            transcript.scan_engine = verdict.engine
            transcript.scan_engine_version = verdict.engine_version
            if verdict.infected:
                try:
                    await self._services.storage.delete(
                        key=transcript.object_key,
                        bucket=self._services.settings.s3_bucket_audio,
                    )
                except Exception:  # noqa: BLE001 - deletion is retried by retention
                    logger.warning(
                        "quarantined audio object could not be deleted",
                        extra={
                            "event": "transcript.quarantine.delete_failed",
                            "extra_fields": {"transcript_id": str(transcript.id)},
                        },
                    )
                transcript.scan_status = "infected"
                transcript.scanned_at = dt.datetime.now(dt.UTC)
                await self._transcripts.set_status(
                    transcript, status="failed", error_code="malware_detected"
                )
                self._audit.append(
                    actor_subject=context.subject,
                    actor_role=context.primary_role.value,
                    action="transcript.quarantined",
                    resource_type="transcript",
                    resource_id=str(transcript.id),
                    patient_id=encounter.patient_id,
                    trace_id=trace_id,
                    metadata={
                        "scan_engine": verdict.engine,
                        "signature": verdict.signature or "unknown",
                    },
                )
                return await self._transcript_out(transcript)
            if verdict.status == "unavailable" and self._services.malware.required:
                transcript.scan_status = "unavailable"
                transcript.scanned_at = dt.datetime.now(dt.UTC)
                await self._transcripts.set_status(
                    transcript, status="failed", error_code="malware_scan_unavailable"
                )
                self._audit.append(
                    actor_subject=context.subject,
                    actor_role=context.primary_role.value,
                    action="transcript.scan_blocked",
                    resource_type="transcript",
                    resource_id=str(transcript.id),
                    patient_id=encounter.patient_id,
                    trace_id=trace_id,
                    metadata={"reason": "malware_scan_unavailable"},
                )
                return await self._transcript_out(transcript)
            transcript.scan_status = verdict.status
            transcript.scanned_at = (
                dt.datetime.now(dt.UTC) if verdict.status != "unavailable" else None
            )
        await self._transcripts.set_status(transcript, status="processing")
        try:
            if not transcript.object_key:
                raise ValueError("audio object key missing")
            # mcp-stt contract: it fetches `audio_url` itself, so hand it an
            # internal-endpoint presigned GET (not the browser-facing host).
            audio_url = await self._services.storage.presign_get_internal(
                key=transcript.object_key,
                bucket=self._services.settings.s3_bucket_audio,
                expires_seconds=600,
            )
            result = await self._tools.call(
                context=self._tool_context(context, encounter, trace_id),
                graph="scribe",
                tool="transcribe",
                arguments={
                    "audio_url": audio_url,
                    "language": context.locale.split("-")[0],
                },
                timeout_seconds=300,
            )
        except Exception as exc:  # noqa: BLE001 - MCP boundary
            await self._transcripts.set_status(
                transcript, status="failed", error_code="stt_unavailable"
            )
            self._audit.append(
                actor_subject=context.subject,
                actor_role=context.primary_role.value,
                action="transcript.stt_failed",
                resource_type="transcript",
                resource_id=str(transcript.id),
                patient_id=encounter.patient_id,
                consent_id=context.consent_id,
                trace_id=trace_id,
                metadata={"reason": getattr(exc, "code", "stt_unavailable")},
            )
            return await self._transcript_out(transcript)
        raw_turns = result.get("turns")
        if not isinstance(raw_turns, list) or not raw_turns:
            await self._transcripts.set_status(transcript, status="failed", error_code="stt_empty")
            return await self._transcript_out(transcript)
        turns: list[TranscriptTurn] = []
        for turn in raw_turns[:400]:
            text = str(turn.get("text", "")).strip()
            if not text:
                continue
            speaker = str(turn.get("speaker", "other"))
            if speaker not in {"doctor", "patient", "other"}:
                speaker = "other"
            turns.append(
                TranscriptTurn(
                    transcript_id=transcript.id,
                    turn_index=len(turns),
                    speaker=speaker,
                    start_ms=max(0, int(turn.get("start_ms", 0))),
                    end_ms=max(0, int(turn.get("end_ms", 0))),
                    text=text[:4000],
                    language=str(turn.get("language", result.get("language", "mixed")))[:10],
                )
            )
        if not turns:
            await self._transcripts.set_status(transcript, status="failed", error_code="stt_empty")
            return await self._transcript_out(transcript)
        duration = int(result.get("duration_ms") or transcript.duration_ms or 0)
        transcript.duration_ms = duration or None
        transcript.language = str(result.get("language", "mixed"))[:10]
        await self._transcripts.add_turns(transcript.id, turns)
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="transcript.stt_completed",
            resource_type="transcript",
            resource_id=str(transcript.id),
            patient_id=encounter.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={"turns": len(turns), "engine": "local_mcp_stt"},
        )
        return await self._transcript_out(transcript)

    async def start_run(
        self,
        context: AuthContext,
        encounter_id: uuid.UUID,
        transcript_id: uuid.UUID | None,
        trace_id: str | None,
    ) -> ScribeRunOut:
        encounter = await self._doctor_encounter(context, encounter_id)
        if encounter.status != "active":
            raise _problem(409, "encounter_closed", "This encounter is closed.")
        if await self._notes.for_encounter(encounter.id):
            raise _problem(409, "note_signed", "A signed note already exists for this encounter.")
        latest = await self._scribe.latest_run(encounter.id)
        if latest is not None and latest.status in {"draft", "blocked"}:
            return await self._run_out(latest)
        if latest is not None and latest.status == "running":
            raise _problem(409, "scribe_run_active", "A draft is already running.")
        transcript = (
            await self._transcripts.get(transcript_id)
            if transcript_id
            else await self._transcripts.latest_for_encounter(encounter.id)
        )
        if (
            transcript is None
            or transcript.encounter_id != encounter.id
            or transcript.status != "ready"
        ):
            raise _problem(422, "transcript_required", "Upload a ready transcript before drafting.")
        rejection = await self._scribe.last_rejection(encounter.id)
        feedback = rejection.rejection_reason if rejection else None
        run = ScribeRun(
            encounter_id=encounter.id,
            transcript_id=transcript.id,
            requested_by_subject=context.subject,
            status="running",
            revision=(latest.revision + 1) if latest else 1,
            prompt_version=int(self._services.prompt("scribe").get("version", 1)),
            trace_id=(trace_id or "")[:64] or None,
        )
        await self._scribe.create_run(run)
        return await self._execute_run(
            run,
            encounter,
            transcript,
            context,
            trace_id,
            acknowledged=False,
            feedback=feedback,
        )

    async def _execute_run(
        self,
        run: ScribeRun,
        encounter: Encounter,
        transcript: Transcript,
        context: AuthContext,
        trace_id: str | None,
        *,
        acknowledged: bool,
        feedback: str | None,
    ) -> ScribeRunOut:
        turns = await self._transcripts.turns(transcript.id)
        turn_payload = [
            {
                "turn_index": turn.turn_index,
                "speaker": turn.speaker,
                "start_ms": turn.start_ms,
                "end_ms": turn.end_ms,
                "text": turn.text,
            }
            for turn in turns
        ]
        from app.core.tracing import current_trace
        from app.modules.memory.service import MemoryFacade

        collector = current_trace()
        if collector is not None:
            collector.session_id = str(encounter.id)
            collector.user_id = context.subject

        memory_note = None
        try:
            recall = await MemoryFacade(self._services, self._session).recall(
                subject=context.subject,
                query="doctor preferences",
                history=[],
            )
            memory_note = recall.memory_note
        except Exception:  # noqa: BLE001 - prefs must not block draft
            memory_note = None

        outcome = await self._graph.run(
            turns=turn_payload,
            locale=context.locale,
            acknowledged=acknowledged,
            feedback=feedback,
            tool_context=self._tool_context(context, encounter, trace_id),
            clinic_code=encounter.clinic_code,
            trace_id=trace_id,
            patient_id=str(encounter.patient_id),
            memory_note=memory_note,
        )
        return await self._persist_outcome(run, encounter, context, trace_id, outcome)

    async def _persist_outcome(
        self,
        run: ScribeRun,
        encounter: Encounter,
        context: AuthContext,
        trace_id: str | None,
        outcome: ScribeOutcome,
    ) -> ScribeRunOut:
        run.completed_at = outcome.completed_at
        run.model_alias = outcome.model_alias
        run.trace_id = (trace_id or "")[:64] or None
        run.red_flag_ids = [flag["rule_id"] for flag in outcome.red_flags]
        if outcome.error:
            run.status = "blocked" if outcome.error == "red_flag_ack_required" else "failed"
            run.error_code = outcome.error
            self._session.add(
                ReviewTask(
                    patient_id=encounter.patient_id,
                    created_by_subject=context.subject,
                    assigned_role="doctor",
                    reason=outcome.error[:200],
                    status="open",
                    resource_type="scribe_run",
                    resource_id=str(run.id),
                    due_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=4),
                )
            )
            self._audit.append(
                actor_subject=context.subject,
                actor_role=context.primary_role.value,
                action="scribe.run_failed",
                resource_type="scribe_run",
                resource_id=str(run.id),
                patient_id=encounter.patient_id,
                consent_id=context.consent_id,
                trace_id=trace_id,
                metadata={"reason": outcome.error},
            )
            await self._session.flush()
            return await self._run_out(run, outcome=outcome)
        assert outcome.draft is not None
        draft = ScribeDraft(
            run_id=run.id,
            revision=1,
            schema_version="scribe_v1",
            content=outcome.draft,
        )
        await self._scribe.add_draft(draft)
        sources = [
            ScribeSource(
                draft_id=draft.id,
                field=source["field"],
                line_index=source["line_index"],
                source_type=source["source_type"],
                source_ref=source["source_ref"],
                status=source["status"],
                as_of=source["as_of"],
            )
            for source in outcome.sources
        ]
        await self._scribe.add_sources(sources)
        run.status = "draft"
        run.error_code = None
        await UsageRepository(self._session).record(
            purpose="w3_draft",
            model_alias=outcome.model_alias or "unknown",
            prompt_tokens=outcome.prompt_tokens,
            completion_tokens=outcome.completion_tokens,
            cost_usd=self._services.model_cost(
                outcome.model_alias or "unknown", outcome.prompt_tokens, outcome.completion_tokens
            ),
            trace_id=trace_id,
            session_id=None,
            traffic_class=encounter.traffic_class,
            gateway_request_id=outcome.gateway_request_id,
        )
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="scribe.draft_created",
            resource_type="scribe_run",
            resource_id=str(run.id),
            patient_id=encounter.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={
                "model_alias": outcome.model_alias,
                "revision": run.revision,
                "red_flags": run.red_flag_ids,
            },
        )
        await self._session.flush()
        return await self._run_out(run, outcome=outcome)

    async def acknowledge_red_flags(
        self, context: AuthContext, run_id: uuid.UUID, trace_id: str | None
    ) -> ScribeRunOut:
        run = await self._scribe.get_run(run_id, lock=True)
        if run is None:
            raise _problem(404, "scribe_run_not_found", "No such scribe run.")
        encounter = await self._doctor_encounter(context, run.encounter_id)
        if run.status != "blocked" or run.error_code != "red_flag_ack_required":
            return await self._run_out(run)
        run.red_flag_acknowledged_at = dt.datetime.now(dt.UTC)
        run.status = "running"
        run.error_code = None
        transcript = await self._transcripts.get(run.transcript_id)
        if transcript is None:
            raise _problem(409, "transcript_missing", "The transcript is no longer available.")
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="scribe.red_flag_acknowledged",
            resource_type="scribe_run",
            resource_id=str(run.id),
            patient_id=encounter.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={"rule_ids": run.red_flag_ids},
        )
        return await self._execute_run(
            run,
            encounter,
            transcript,
            context,
            trace_id,
            acknowledged=True,
            feedback=None,
        )

    async def edit_draft(
        self,
        context: AuthContext,
        run_id: uuid.UUID,
        body: DraftEditRequest,
        trace_id: str | None,
    ) -> ScribeRunOut:
        run = await self._scribe.get_run(run_id, lock=True)
        if run is None:
            raise _problem(404, "scribe_run_not_found", "No such scribe run.")
        encounter = await self._doctor_encounter(context, run.encounter_id)
        if run.status != "draft":
            raise _problem(409, "draft_not_editable", "This run has no editable draft.")
        draft = await self._scribe.latest_draft(run.id)
        if draft is None:
            raise _problem(409, "draft_missing", "This run has no draft.")
        payload = _strip_stock(body.content)
        turns = await self._transcripts.turns(run.transcript_id)
        turn_payload = [
            {
                "turn_index": turn.turn_index,
                "speaker": turn.speaker,
                "start_ms": turn.start_ms,
                "end_ms": turn.end_ms,
                "text": turn.text,
            }
            for turn in turns
        ]
        try:
            content, sources = ground_draft(payload, turns=turn_payload, schema=self._schema)
            content, sources = await align_draft_medicines(
                content,
                sources,
                turn_payload,
                encounter.clinic_code,
                self._search_catalog,
            )
        except DraftRejected as exc:
            raise _problem(422, exc.code, exc.detail) from exc
        content = await enrich_medicines(
            draft=content,
            sources=sources,
            tools=self._tools,
            context=self._tool_context(context, encounter, trace_id),
            clinic_code=encounter.clinic_code,
            source_label=str(self._services.stock_config.get("source_label", "stock")),
        )
        revision = draft.revision + 1
        new_draft = ScribeDraft(
            run_id=run.id,
            revision=revision,
            schema_version="scribe_v1",
            content=content,
        )
        await self._scribe.add_draft(new_draft)
        await self._scribe.add_sources(
            [
                ScribeSource(
                    draft_id=new_draft.id,
                    field=source["field"],
                    line_index=source["line_index"],
                    source_type=source["source_type"],
                    source_ref=source["source_ref"],
                    status=source["status"],
                    as_of=source["as_of"],
                )
                for source in sources
            ]
        )
        changed = [
            field
            for field in ("subjective", "objective", "assessment", "plan", "follow_up", "medicines")
            if body.content.get(field) != draft.content.get(field)
        ]
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="scribe.draft_edited",
            resource_type="scribe_draft",
            resource_id=str(new_draft.id),
            patient_id=encounter.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={"revision": revision, "changed_fields": changed},
        )
        await self._session.flush()
        return await self._run_out(run)

    async def reject_run(
        self,
        context: AuthContext,
        run_id: uuid.UUID,
        body: RejectRequest,
        trace_id: str | None,
    ) -> ScribeRunOut:
        run = await self._scribe.get_run(run_id, lock=True)
        if run is None:
            raise _problem(404, "scribe_run_not_found", "No such scribe run.")
        encounter = await self._doctor_encounter(context, run.encounter_id)
        if run.status not in {"draft", "blocked"}:
            raise _problem(409, "draft_not_rejectable", "This run cannot be rejected.")
        run.status = "rejected"
        run.rejection_reason = body.comment
        run.rejection_category = body.category
        run.completed_at = dt.datetime.now(dt.UTC)
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="scribe.draft_rejected",
            resource_type="scribe_run",
            resource_id=str(run.id),
            patient_id=encounter.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={"category": body.category},
        )
        await self._session.flush()
        return await self._run_out(run)

    async def sign_run(
        self,
        context: AuthContext,
        run_id: uuid.UUID,
        body: SignRequest,
        *,
        ip_address: str | None,
        user_agent: str | None,
        trace_id: str | None,
    ) -> SignatureOut:
        run = await self._scribe.get_run(run_id, lock=True)
        if run is None:
            raise _problem(404, "scribe_run_not_found", "No such scribe run.")
        encounter = await self._doctor_encounter(context, run.encounter_id)
        if encounter.status != "active":
            raise _problem(409, "encounter_closed", "This encounter is closed.")
        existing = await self._notes.for_encounter(encounter.id)
        if existing is not None:
            version = await self._notes.latest_version(existing.id)
            return SignatureOut(
                note_id=existing.id,
                version=existing.current_version,
                content_hash=version.content_hash if version else existing.signed_hash,
                signed_at=existing.signed_at,
                stock_flags=[],
                patient_notified=False,
            )
        if run.status != "draft":
            raise _problem(409, "draft_not_signable", "Only a reviewed draft can be signed.")
        draft = await self._scribe.latest_draft(run.id)
        if draft is None:
            raise _problem(409, "draft_missing", "This run has no draft.")
        now = dt.datetime.now(dt.UTC)
        digest = content_hash(draft.content)
        from app.modules.scribe.edit_metrics import field_edit_distances, review_seconds

        drafts = await self._scribe.drafts(run.id)
        first_draft = drafts[-1] if drafts else draft
        edit_stats = field_edit_distances(first_draft.content, draft.content)
        reviewed = review_seconds(draft_ready_at=run.completed_at, signed_at=now)
        run.edit_distance = edit_stats
        run.review_seconds = reviewed
        note = ClinicalNote(
            encounter_id=encounter.id,
            patient_id=encounter.patient_id,
            author_subject=context.subject,
            status="signed",
            title=f"Consultation note — {encounter.started_at.astimezone(dt.UTC):%d %b %Y}",
            language=context.locale.split("-")[0],
            current_version=1,
            signed_by=context.subject,
            signed_at=now,
            signed_hash=digest,
        )
        await self._notes.create(note)
        version = ClinicalNoteVersion(
            note_id=note.id,
            version=1,
            content=draft.content,
            content_hash=digest,
            prev_content_hash=None,
            parent_version=None,
            signed_by=context.subject,
            signed_at=now,
            signature_ref={
                "actor_subject": context.subject,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "attestation": True,
                "comment": body.comment,
                "run_id": str(run.id),
                "draft_revision": draft.revision,
                "edit_distance_total": edit_stats.get("total"),
                "review_seconds": reviewed,
            },
        )
        await self._notes.add_version(version)
        draft_sources = await self._scribe.sources(draft.id)
        await self._notes.add_sources(
            [
                NoteSource(
                    note_id=note.id,
                    version=1,
                    field=source.field,
                    line_index=source.line_index,
                    source_type=source.source_type,
                    source_ref=source.source_ref,
                    status=source.status,
                    as_of=source.as_of,
                )
                for source in draft_sources
            ]
        )
        run.status = "signed"
        notified = await self._notify_patient(encounter, context, trace_id)
        stock_flags = [
            {
                "name": medicine.get("name"),
                "stock": medicine.get("stock"),
            }
            for medicine in draft.content.get("medicines", [])
        ]
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="note.signed",
            resource_type="clinical_note",
            resource_id=str(note.id),
            patient_id=encounter.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={
                "version": 1,
                "content_hash": digest,
                "run_id": str(run.id),
                "edit_distance": edit_stats,
                "review_seconds": reviewed,
                "stock_unknown": sum(
                    1
                    for item in stock_flags
                    if (item.get("stock") or {}).get("status") == "unknown"
                ),
            },
        )
        await self._session.flush()
        return SignatureOut(
            note_id=note.id,
            version=1,
            content_hash=digest,
            signed_at=now,
            stock_flags=stock_flags,
            patient_notified=notified,
        )

    async def _notify_patient(
        self, encounter: Encounter, context: AuthContext, trace_id: str | None
    ) -> bool:
        patient = await self._patients.get(encounter.patient_id)
        if patient is None or not patient.keycloak_subject:
            return False
        try:
            await NotificationService(self._services, self._session).send(
                template_id="document_ready",
                recipient_subject=patient.keycloak_subject,
                recipient_role="patient",
                patient_id=patient.id,
                locale=patient.locale,
                data={"document_kind": "Visit note"},
                actor_subject=context.subject,
                actor_role="service",
                trace_id=trace_id,
            )
        except Exception:  # noqa: BLE001 - notification failure never rolls back a signature
            return False
        return True

    async def _run_out(
        self, run: ScribeRun, *, outcome: ScribeOutcome | None = None
    ) -> ScribeRunOut:
        draft = await self._scribe.latest_draft(run.id)
        sources = await self._scribe.sources(draft.id) if draft else []
        result = ScribeRunOut.model_validate(run)
        if draft is not None:
            result.draft = DraftOut(
                id=draft.id,
                revision=draft.revision,
                schema_version=draft.schema_version,
                content=draft.content,
                created_at=draft.created_at,
            )
        result.sources = [SourceOut.model_validate(source) for source in sources]
        result.red_flags = self._red_flag_details(run.red_flag_ids)
        if run.status == "draft" and run.completed_at is not None:
            result.elapsed_seconds = max(
                0, int((dt.datetime.now(dt.UTC) - run.completed_at).total_seconds())
            )
        if outcome is not None:
            result.error_detail = outcome.error_detail
        return result

    def _red_flag_details(self, rule_ids: list[str]) -> list[dict[str, str]]:
        rules = {str(rule["id"]): rule for rule in self._services.red_flags.get("rules", [])}
        details: list[dict[str, str]] = []
        for rule_id in rule_ids:
            rule = rules.get(rule_id)
            if rule is None:
                continue
            details.append(
                {
                    "rule_id": rule_id,
                    "name": str(rule.get("name", rule_id)),
                    "severity": str(rule.get("severity", "urgent")),
                    "guidance": str(rule.get("guidance", "")),
                }
            )
        return details

    async def get_run(self, context: AuthContext, run_id: uuid.UUID) -> ScribeRunOut:
        run = await self._scribe.get_run(run_id)
        if run is None:
            raise _problem(404, "scribe_run_not_found", "No such scribe run.")
        await self._doctor_encounter(context, run.encounter_id)
        return await self._run_out(run)

    async def get_transcript(self, context: AuthContext, encounter_id: uuid.UUID) -> TranscriptOut:
        encounter = await self._doctor_encounter(context, encounter_id)
        transcript = await self._transcripts.latest_for_encounter(encounter.id)
        if transcript is None:
            # Encounters started before empty-shell seeding still need a usable transcript.
            transcript = await self._transcripts.create(
                Transcript(
                    encounter_id=encounter.id,
                    status="ready",
                    source="manual",
                    language="en-IN",
                    duration_ms=0,
                )
            )
            await self._session.commit()
        return await self._transcript_out(transcript)

    async def note_visible(
        self, context: AuthContext, note_id: uuid.UUID
    ) -> tuple[ClinicalNote, dict[str, Any] | None, bool]:
        note = await self._notes.get(note_id)
        if note is None:
            raise _problem(404, "note_not_found", "No such note.")
        role = context.primary_role
        metadata_only = False
        content: dict[str, Any] | None = None
        if role is Role.DOCTOR:
            if note.author_subject != context.subject:
                raise _problem(
                    403, "note_owner_only", "Only the treating doctor can open this note."
                )
            version = await self._notes.latest_version(note.id)
            content = version.content if version else None
        elif role in {Role.ADMIN, Role.COMPLIANCE}:
            metadata_only = True
        elif role is Role.PATIENT:
            if context.patient_id != note.patient_id:
                raise _problem(403, "forbidden", "This note belongs to another patient.")
            version = await self._notes.latest_version(note.id)
            content = version.content if version else None
        elif role is Role.CAREGIVER:
            if context.patient_id != note.patient_id or not await self._patients.active_consent(
                caregiver_subject=context.subject,
                patient_id=note.patient_id,
                scope="records",
                consent_id=context.consent_id,
            ):
                raise _problem(403, "consent_required", "Active records consent is required.")
            version = await self._notes.latest_version(note.id)
            content = version.content if version else None
        elif role is Role.PHARMACIST:
            if context.clinic_ids:
                encounter = await self._encounters.get(note.encounter_id)
                if encounter is None or encounter.clinic_code not in context.clinic_ids:
                    raise _problem(403, "forbidden", "This note is outside your clinic scope.")
            version = await self._notes.latest_version(note.id)
            content = {"medicines": version.content.get("medicines", [])} if version else None
        else:
            raise _problem(403, "forbidden", "Your role cannot open clinical notes.")
        return note, content, metadata_only

    async def get_note(self, context: AuthContext, note_id: uuid.UUID) -> NoteOut:
        note, content, metadata_only = await self.note_visible(context, note_id)
        patient_name = await self._patient_name(note.patient_id)
        result = NoteOut.model_validate(note)
        result.patient_display_name = patient_name
        result.content = content
        result.metadata_only = metadata_only
        if context.primary_role is Role.DOCTOR:
            version = await self._notes.latest_version(note.id)
            if version is not None:
                sources = await self._notes.sources(note.id, version.version)
                result.sources = [SourceOut.model_validate(source) for source in sources]
        return result

    async def list_notes(
        self,
        context: AuthContext,
        *,
        query: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[NoteOut], int]:
        role = context.primary_role
        doctor_subject: str | None = None
        patient_id: uuid.UUID | None = None
        clinic_scope: tuple[str, ...] = ()
        if role is Role.DOCTOR:
            doctor_subject = context.subject
        elif role is Role.PATIENT:
            if context.patient_id is None:
                raise _problem(403, "patient_not_linked", "This account is not linked.")
            patient_id = context.patient_id
        elif role is Role.CAREGIVER:
            if context.patient_id is None or not await self._patients.active_consent(
                caregiver_subject=context.subject,
                patient_id=context.patient_id,
                scope="records",
                consent_id=context.consent_id,
            ):
                raise _problem(403, "consent_required", "Active records consent is required.")
            patient_id = context.patient_id
        elif role in {Role.PHARMACIST, Role.ADMIN, Role.COMPLIANCE}:
            clinic_scope = context.clinic_ids if role is Role.PHARMACIST else ()
        else:
            raise _problem(403, "forbidden", "Your role cannot list clinical notes.")
        rows, total = await self._notes.list_grid(
            doctor_subject=doctor_subject,
            patient_id=patient_id,
            clinic_scope=clinic_scope,
            query=query,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        metadata_only = role in {Role.ADMIN, Role.COMPLIANCE, Role.PHARMACIST}
        items = []
        for note, display_name in rows:
            item = NoteOut.model_validate(note)
            item.patient_display_name = display_name
            item.metadata_only = metadata_only
            items.append(item)
        return items, total

    async def note_versions(self, context: AuthContext, note_id: uuid.UUID) -> list[NoteVersionOut]:
        note, _, _ = await self.note_visible(context, note_id)
        versions = await self._notes.versions(note.id)
        return [NoteVersionOut.model_validate(version) for version in versions]

    async def correct_note(
        self,
        context: AuthContext,
        note_id: uuid.UUID,
        body: CorrectionRequest,
        trace_id: str | None,
    ) -> NoteOut:
        note = await self._notes.get(note_id)
        if note is None:
            raise _problem(404, "note_not_found", "No such note.")
        if context.primary_role is not Role.DOCTOR or note.author_subject != context.subject:
            raise _problem(
                403, "note_owner_only", "Only the treating doctor can correct this note."
            )
        payload = _strip_stock(body.content)
        try:
            validate_structure(payload, self._schema)
        except DraftRejected as exc:
            raise _problem(422, exc.code, exc.detail) from exc
        previous = await self._notes.latest_version(note.id)
        if previous is None:
            raise _problem(409, "note_version_missing", "The note has no signed version.")
        version_number = note.current_version + 1
        digest = content_hash(payload)
        now = dt.datetime.now(dt.UTC)
        await self._notes.add_version(
            ClinicalNoteVersion(
                note_id=note.id,
                version=version_number,
                content=payload,
                content_hash=digest,
                prev_content_hash=previous.content_hash,
                parent_version=previous.version,
                signed_by=context.subject,
                signed_at=now,
                signature_ref={
                    "actor_subject": context.subject,
                    "reason": body.reason,
                    "correction": True,
                },
            )
        )
        await self._notes.add_sources(
            self._correction_sources(note.id, version_number, payload, previous)
        )
        note.current_version = version_number
        note.status = "amended"
        note.signed_hash = digest
        note.signed_at = now
        note.signed_by = context.subject
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="note.corrected",
            resource_type="clinical_note",
            resource_id=str(note.id),
            patient_id=note.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={
                "version": version_number,
                "parent_version": previous.version,
                "content_hash": digest,
                "reason": body.reason,
            },
        )
        await self._session.flush()
        return await self.get_note(context, note.id)

    def _correction_sources(
        self,
        note_id: uuid.UUID,
        version: int,
        content: dict[str, Any],
        previous: ClinicalNoteVersion,
    ) -> list[NoteSource]:
        previous_content = previous.content
        rows: list[NoteSource] = []
        for field in ("subjective", "objective", "assessment", "plan"):
            previous_lines = previous_content.get(field, [])
            for index, line in enumerate(content.get(field, [])):
                unchanged = index < len(previous_lines) and previous_lines[index] == line
                rows.append(
                    NoteSource(
                        note_id=note_id,
                        version=version,
                        field=field,
                        line_index=index,
                        source_type="transcript" if unchanged else "none",
                        source_ref={
                            "label": None if unchanged else "clinician correction",
                            "carried_from": previous.version if unchanged else None,
                        },
                        status="resolved" if unchanged else "unsourced",
                        as_of=None,
                    )
                )
        for index, _medicine in enumerate(content.get("medicines", [])):
            rows.append(
                NoteSource(
                    note_id=note_id,
                    version=version,
                    field="medicine",
                    line_index=index,
                    source_type="none",
                    source_ref={"label": "clinician correction"},
                    status="unsourced",
                    as_of=None,
                )
            )
        return rows

    async def note_sources(
        self, context: AuthContext, note_id: uuid.UUID, version: int | None
    ) -> list[SourceOut]:
        note, _, metadata_only = await self.note_visible(context, note_id)
        if metadata_only:
            raise _problem(403, "forbidden", "Source maps are not visible to this role.")
        selected = version or note.current_version
        rows = await self._notes.sources(note.id, selected)
        return [SourceOut.model_validate(row) for row in rows]

    async def note_download(self, context: AuthContext, note_id: uuid.UUID) -> bytes:
        from app.modules.scribe.note_pdf import render_clinical_note_pdf

        note, content, metadata_only = await self.note_visible(context, note_id)
        if metadata_only or content is None:
            raise _problem(403, "forbidden", "Download is not available for this role.")
        patient_name = await self._patient_name(note.patient_id) or "Patient"
        encounter = await self._encounters.get(note.encounter_id)
        return render_clinical_note_pdf(
            note_id=note.id,
            title=note.title,
            patient_name=patient_name,
            patient_id=note.patient_id,
            version=note.current_version,
            language=note.language,
            status=note.status,
            signed_by=note.signed_by,
            signed_at=note.signed_at,
            signed_hash=note.signed_hash,
            content=content,
            doctor_name=encounter.doctor_name if encounter else None,
            clinic_code=encounter.clinic_code if encounter else None,
            org_name=self._services.settings.app_name,
        )

    async def reserve_stock(
        self,
        context: AuthContext,
        note_id: uuid.UUID,
        body: StockReservationRequest,
        trace_id: str | None,
    ) -> StockReservationOut:
        if context.primary_role not in {Role.DOCTOR, Role.PHARMACIST}:
            raise _problem(403, "forbidden", "Only a doctor or pharmacist can reserve stock.")
        note, content, _ = await self.note_visible(context, note_id)
        if content is None:
            raise _problem(403, "forbidden", "This note is not visible to you.")
        # Prefer medicines listed on the note, but allow any clinic stock SKU so
        # pharmacists can reserve substitutes / additional lines against this note.
        from app.modules.pharmacy.service import PharmacyService

        stock = await PharmacyService(self._services, self._session).lookup_guard(
            drug_name=body.medicine_name, clinic_code=body.clinic_code
        )
        status = str(stock.get("status") or "unknown")
        if status == "unknown" or stock.get("stale"):
            raise _problem(
                422,
                "stock_unknown",
                "Stock is unknown or stale for this medicine; refresh inventory before reserving.",
            )
        if status in {"not_available"} or not stock.get("available"):
            raise _problem(
                422,
                "stock_unavailable",
                "This medicine is not available at the selected clinic.",
            )
        on_hand = int(stock.get("quantity") or 0)
        if body.quantity > on_hand:
            raise _problem(
                422,
                "stock_insufficient",
                f"Only {on_hand} units are available for reservation.",
            )
        reservation = StockReservation(
            note_id=note.id,
            medicine_name=body.medicine_name,
            sku=body.sku or stock.get("sku"),
            clinic_code=body.clinic_code,
            quantity=body.quantity,
            status="reserved",
            reserved_by_subject=context.subject,
        )
        await self._notes.add_reservation(reservation)
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="stock.reservation_created",
            resource_type="clinical_note",
            resource_id=str(note.id),
            patient_id=note.patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={
                "medicine": body.medicine_name,
                "quantity": body.quantity,
                "clinic_code": body.clinic_code,
            },
        )
        return StockReservationOut.model_validate(reservation)

    async def stock_lookup(
        self, context: AuthContext, *, drug_name: str, clinic_code: str
    ) -> dict[str, Any]:
        if context.primary_role not in {Role.DOCTOR, Role.PHARMACIST, Role.FRONT_DESK}:
            raise _problem(403, "forbidden", "Your role cannot read stock.")
        result = await stock_status(
            tools=self._tools,
            context=self._tool_context_for_role(context, clinic_code),
            drug_name=drug_name,
            clinic_code=clinic_code,
            source_label=str(self._services.stock_config.get("source_label", "stock")),
        )
        return result

    def _tool_context_for_role(self, context: AuthContext, clinic_code: str) -> ExecutionContext:
        now = int(dt.datetime.now(dt.UTC).timestamp())
        return ExecutionContext(
            actor_subject=context.subject,
            actor_role=ToolRole(context.primary_role.value),
            clinic_ids=(clinic_code,),
            trace_id=uuid.uuid4().hex,
            locale=context.locale if context.locale in {"en-IN", "hi-IN", "mr-IN"} else "en-IN",
            traffic_class="synthetic" if context.traffic_class == "synthetic" else "real",
            issued_at=now,
            expires_at=now + 60,
        )
