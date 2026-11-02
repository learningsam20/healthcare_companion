from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import (
    Appointment,
    ClinicalNote,
    ClinicalNoteVersion,
    Encounter,
    NoteSource,
    Patient,
    ScribeDraft,
    ScribeRun,
    ScribeSource,
    StockReservation,
    Transcript,
    TranscriptTurn,
)


class EncounterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, encounter: Encounter) -> Encounter:
        self._session.add(encounter)
        await self._session.flush()
        return encounter

    async def get(self, encounter_id: uuid.UUID) -> Encounter | None:
        return await self._session.get(Encounter, encounter_id)

    async def for_appointment(self, appointment_id: uuid.UUID) -> Encounter | None:
        return await self._session.scalar(
            select(Encounter).where(Encounter.appointment_id == appointment_id)
        )

    async def appointment(self, appointment_id: uuid.UUID) -> Appointment | None:
        return await self._session.get(Appointment, appointment_id)

    async def list_grid(
        self,
        *,
        doctor_subject: str | None,
        clinic_scope: tuple[str, ...],
        status: str | None,
        query: str | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[
        list[tuple[Encounter, str | None, uuid.UUID | None, str | None, uuid.UUID | None]], int
    ]:
        conditions = []
        if doctor_subject:
            conditions.append(Encounter.doctor_subject == doctor_subject)
        if clinic_scope:
            conditions.append(Encounter.clinic_code.in_(clinic_scope))
        if status:
            conditions.append(Encounter.status == status)
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    Patient.display_name.ilike(pattern),
                    cast(Encounter.id, String).ilike(pattern),
                    Encounter.doctor_name.ilike(pattern),
                )
            )
        latest_run_id = (
            select(ScribeRun.id)
            .where(ScribeRun.encounter_id == Encounter.id)
            .order_by(ScribeRun.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        latest_run_status = (
            select(ScribeRun.status)
            .where(ScribeRun.encounter_id == Encounter.id)
            .order_by(ScribeRun.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        note_id = (
            select(ClinicalNote.id)
            .where(ClinicalNote.encounter_id == Encounter.id)
            .limit(1)
            .scalar_subquery()
        )
        sort_columns = {
            "started_at": Encounter.started_at,
            "patient_name": Patient.display_name,
            "doctor_name": Encounter.doctor_name,
            "status": Encounter.status,
            "clinic_code": Encounter.clinic_code,
        }
        order_by = sort_columns.get(sort, Encounter.started_at)
        base = select(
            Encounter, Patient.display_name, latest_run_id, latest_run_status, note_id
        ).join(Patient, Patient.id == Encounter.patient_id)
        total = await self._session.scalar(
            select(func.count())
            .select_from(Encounter)
            .join(Patient, Patient.id == Encounter.patient_id)
            .where(*conditions)
        )
        rows = await self._session.execute(
            base.where(*conditions)
            .order_by(order_by.desc() if descending else order_by.asc(), Encounter.id)
            .limit(limit)
            .offset(offset)
        )
        return [(row[0], row[1], row[2], row[3], row[4]) for row in rows], int(total or 0)

    async def close(self, encounter: Encounter) -> None:
        encounter.status = "closed"
        encounter.ended_at = dt.datetime.now(dt.UTC)
        await self._session.flush()


class TranscriptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, transcript: Transcript) -> Transcript:
        self._session.add(transcript)
        await self._session.flush()
        return transcript

    async def get(self, transcript_id: uuid.UUID) -> Transcript | None:
        return await self._session.get(Transcript, transcript_id)

    async def latest_for_encounter(self, encounter_id: uuid.UUID) -> Transcript | None:
        return await self._session.scalar(
            select(Transcript)
            .where(Transcript.encounter_id == encounter_id, Transcript.status != "deleted")
            .order_by(Transcript.created_at.desc())
            .limit(1)
        )

    async def add_turns(self, transcript_id: uuid.UUID, turns: list[TranscriptTurn]) -> None:
        for turn in turns:
            turn.transcript_id = transcript_id
            self._session.add(turn)
        transcript = await self.get(transcript_id)
        if transcript is not None:
            transcript.status = "ready"
        await self._session.flush()

    async def turns(self, transcript_id: uuid.UUID) -> list[TranscriptTurn]:
        rows = await self._session.scalars(
            select(TranscriptTurn)
            .where(TranscriptTurn.transcript_id == transcript_id)
            .order_by(TranscriptTurn.turn_index)
        )
        return list(rows)

    async def set_status(
        self,
        transcript: Transcript,
        *,
        status: str,
        error_code: str | None = None,
    ) -> None:
        transcript.status = status
        transcript.error_code = error_code
        await self._session.flush()

    async def due_audio_deletions(
        self, *, cutoff: dt.datetime, limit: int = 50
    ) -> list[Transcript]:
        rows = await self._session.scalars(
            select(Transcript)
            .where(
                Transcript.object_key.is_not(None),
                Transcript.audio_deleted_at.is_(None),
                Transcript.created_at <= cutoff,
            )
            .limit(limit)
        )
        return list(rows)

    async def mark_audio_deleted(self, transcript: Transcript) -> None:
        transcript.audio_deleted_at = dt.datetime.now(dt.UTC)
        await self._session.flush()


class ScribeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self, run: ScribeRun) -> ScribeRun:
        self._session.add(run)
        await self._session.flush()
        return run

    async def get_run(self, run_id: uuid.UUID, *, lock: bool = False) -> ScribeRun | None:
        if lock:
            return await self._session.scalar(
                select(ScribeRun).where(ScribeRun.id == run_id).with_for_update()
            )
        return await self._session.get(ScribeRun, run_id)

    async def latest_run(self, encounter_id: uuid.UUID) -> ScribeRun | None:
        return await self._session.scalar(
            select(ScribeRun)
            .where(ScribeRun.encounter_id == encounter_id)
            .order_by(ScribeRun.created_at.desc())
            .limit(1)
        )

    async def last_rejection(self, encounter_id: uuid.UUID) -> ScribeRun | None:
        return await self._session.scalar(
            select(ScribeRun)
            .where(
                ScribeRun.encounter_id == encounter_id,
                ScribeRun.status == "rejected",
                ScribeRun.rejection_reason.is_not(None),
            )
            .order_by(ScribeRun.updated_at.desc())
            .limit(1)
        )

    async def add_draft(self, draft: ScribeDraft) -> ScribeDraft:
        self._session.add(draft)
        await self._session.flush()
        return draft

    async def get_draft(self, draft_id: uuid.UUID) -> ScribeDraft | None:
        return await self._session.get(ScribeDraft, draft_id)

    async def latest_draft(self, run_id: uuid.UUID) -> ScribeDraft | None:
        return await self._session.scalar(
            select(ScribeDraft)
            .where(ScribeDraft.run_id == run_id)
            .order_by(ScribeDraft.revision.desc())
            .limit(1)
        )

    async def drafts(self, run_id: uuid.UUID) -> list[ScribeDraft]:
        rows = await self._session.scalars(
            select(ScribeDraft)
            .where(ScribeDraft.run_id == run_id)
            .order_by(ScribeDraft.revision.desc())
        )
        return list(rows)

    async def add_sources(self, sources: list[ScribeSource]) -> None:
        self._session.add_all(sources)
        await self._session.flush()

    async def sources(self, draft_id: uuid.UUID) -> list[ScribeSource]:
        rows = await self._session.scalars(
            select(ScribeSource)
            .where(ScribeSource.draft_id == draft_id)
            .order_by(ScribeSource.field, ScribeSource.line_index, ScribeSource.id)
        )
        return list(rows)


class NoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, note: ClinicalNote) -> ClinicalNote:
        self._session.add(note)
        await self._session.flush()
        return note

    async def get(self, note_id: uuid.UUID) -> ClinicalNote | None:
        return await self._session.get(ClinicalNote, note_id)

    async def for_encounter(self, encounter_id: uuid.UUID) -> ClinicalNote | None:
        return await self._session.scalar(
            select(ClinicalNote).where(ClinicalNote.encounter_id == encounter_id)
        )

    async def add_version(self, version: ClinicalNoteVersion) -> ClinicalNoteVersion:
        self._session.add(version)
        await self._session.flush()
        return version

    async def latest_version(self, note_id: uuid.UUID) -> ClinicalNoteVersion | None:
        return await self._session.scalar(
            select(ClinicalNoteVersion)
            .where(ClinicalNoteVersion.note_id == note_id)
            .order_by(ClinicalNoteVersion.version.desc())
            .limit(1)
        )

    async def version(self, note_id: uuid.UUID, version: int) -> ClinicalNoteVersion | None:
        return await self._session.scalar(
            select(ClinicalNoteVersion).where(
                ClinicalNoteVersion.note_id == note_id,
                ClinicalNoteVersion.version == version,
            )
        )

    async def versions(self, note_id: uuid.UUID) -> list[ClinicalNoteVersion]:
        rows = await self._session.scalars(
            select(ClinicalNoteVersion)
            .where(ClinicalNoteVersion.note_id == note_id)
            .order_by(ClinicalNoteVersion.version.desc())
        )
        return list(rows)

    async def add_sources(self, sources: list[NoteSource]) -> None:
        self._session.add_all(sources)
        await self._session.flush()

    async def sources(self, note_id: uuid.UUID, version: int) -> list[NoteSource]:
        rows = await self._session.scalars(
            select(NoteSource)
            .where(NoteSource.note_id == note_id, NoteSource.version == version)
            .order_by(NoteSource.field, NoteSource.line_index, NoteSource.id)
        )
        return list(rows)

    async def list_grid(
        self,
        *,
        doctor_subject: str | None,
        patient_id: uuid.UUID | None,
        clinic_scope: tuple[str, ...],
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[ClinicalNote, str | None]], int]:
        conditions = []
        if doctor_subject:
            conditions.append(ClinicalNote.author_subject == doctor_subject)
        if patient_id:
            conditions.append(ClinicalNote.patient_id == patient_id)
        if clinic_scope:
            conditions.append(Encounter.clinic_code.in_(clinic_scope))
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    Patient.display_name.ilike(pattern),
                    ClinicalNote.title.ilike(pattern),
                    cast(ClinicalNote.id, String).ilike(pattern),
                )
            )
        join = (
            select(ClinicalNote, Patient.display_name)
            .join(Patient, Patient.id == ClinicalNote.patient_id)
            .join(Encounter, Encounter.id == ClinicalNote.encounter_id)
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(ClinicalNote)
            .join(Patient, Patient.id == ClinicalNote.patient_id)
            .join(Encounter, Encounter.id == ClinicalNote.encounter_id)
            .where(*conditions)
        )
        rows = await self._session.execute(
            join.where(*conditions)
            .order_by(ClinicalNote.signed_at.desc(), ClinicalNote.id)
            .limit(limit)
            .offset(offset)
        )
        return [(row[0], row[1]) for row in rows], int(total or 0)

    async def reservations(self, note_id: uuid.UUID) -> list[StockReservation]:
        rows = await self._session.scalars(
            select(StockReservation)
            .where(StockReservation.note_id == note_id)
            .order_by(StockReservation.created_at.desc())
        )
        return list(rows)

    async def add_reservation(self, reservation: StockReservation) -> StockReservation:
        self._session.add(reservation)
        await self._session.flush()
        return reservation
