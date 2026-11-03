import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Download,
  FilePlus2,
  LoaderCircle,
  Mic,
  MicOff,
  PencilLine,
  Plus,
  ShieldAlert,
  Stethoscope,
  Trash2,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge, StatusBadge } from "../components/Badge";
import { ClinicalRecord } from "../components/ClinicalRecord";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { IconButton } from "../components/IconButton";
import { Modal } from "../components/Modal";
import { PatientPicker } from "../components/PatientPicker";
import {
  Callout,
  Field,
  FormError,
  PageHeader,
  Spinner,
} from "../components/primitives";
import { api, apiDownload, errorMessage, isApiError, qs, saveBlob } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, humanize } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type {
  Appointment,
  Encounter,
  GridResponse,
  NoteRow,
  Patient,
  PreconsultBrief,
  ScribeDraft,
  ScribeRun,
  SignatureResult,
  Transcript,
} from "../lib/types";

interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0: { transcript: string };
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}

interface SpeechRecognitionLike extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function speechRecognitionCtor(): SpeechRecognitionCtor | null {
  const root = window as Window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return root.SpeechRecognition ?? root.webkitSpeechRecognition ?? null;
}

type SectionKey = "subjective" | "objective" | "assessment" | "plan";
const SECTIONS: SectionKey[] = ["subjective", "objective", "assessment", "plan"];
const SPEAKERS = ["doctor", "patient", "other"] as const;
const LANGUAGES = ["mixed", "en-IN", "hi-IN", "mr-IN"];
const REJECT_CATEGORIES = [
  "wrong_content",
  "missing_content",
  "unsafe",
  "template",
  "transcription",
  "other",
];
const ENCOUNTER_STATUSES = ["active", "closed"];

interface TurnDraft {
  speaker: (typeof SPEAKERS)[number];
  text: string;
}

function speakerAfter(speaker: string | undefined): TurnDraft["speaker"] {
  if (speaker === "doctor") return "patient";
  if (speaker === "patient") return "doctor";
  return "doctor";
}

function joined(content: ScribeDraft["content"], key: SectionKey): string {
  return (content[key] ?? []).map((line) => line.text).join("\n");
}

function withSection(
  content: ScribeDraft["content"],
  key: SectionKey,
  text: string,
): ScribeDraft["content"] {
  const existing = content[key] ?? [];
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const previous = existing[index];
      if (previous && previous.text === line) return previous;
      return { text: line, source_turn_ids: [], unsourced: true };
    });
  return { ...content, [key]: lines };
}

export function ScribePage() {
  const { t, locale } = useI18n();
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const grid = useGridState("started_at", "desc");
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [newOpen, setNewOpen] = useState(false);
  const [kind, setKind] = useState<"scheduled" | "walk_in">("walk_in");
  const [newPatient, setNewPatient] = useState<Patient | null>(null);
  const [appointmentId, setAppointmentId] = useState("");
  const [newError, setNewError] = useState<string | null>(null);
  const [closeConfirm, setCloseConfirm] = useState(false);
  const [listening, setListening] = useState(false);
  const [interimText, setInterimText] = useState("");
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const speechSupported = Boolean(speechRecognitionCtor());

  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [transcriptLanguage, setTranscriptLanguage] = useState("mixed");
  const [turns, setTurns] = useState<TurnDraft[]>([{ speaker: "doctor", text: "" }]);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [draftSections, setDraftSections] = useState<Record<SectionKey, string>>({
    subjective: "",
    objective: "",
    assessment: "",
    plan: "",
  });
  const [draftError, setDraftError] = useState<string | null>(null);

  const [signOpen, setSignOpen] = useState(false);
  const [attestation, setAttestation] = useState(false);
  const [signComment, setSignComment] = useState("");
  const [signResult, setSignResult] = useState<SignatureResult | null>(null);
  const [signError, setSignError] = useState<string | null>(null);

  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectCategory, setRejectCategory] = useState("wrong_content");
  const [rejectComment, setRejectComment] = useState("");
  const [rejectError, setRejectError] = useState<string | null>(null);

  const encountersQuery = useQuery({
    queryKey: ["scribe", "encounters", grid.params, statusFilter],
    queryFn: () =>
      api<GridResponse<Encounter>>(
        `/api/v1/scribe/encounters${qs({
          ...grid.params,
          status: statusFilter || undefined,
        })}`,
      ),
    placeholderData: (previous) => previous,
  });

  const encounterQuery = useQuery({
    queryKey: ["scribe", "encounter", selectedId],
    queryFn: () => api<Encounter>(`/api/v1/scribe/encounters/${selectedId}`),
    enabled: Boolean(selectedId),
  });

  const signedNoteId = encounterQuery.data?.note_id ?? null;
  const noteQuery = useQuery({
    queryKey: ["notes", "detail", signedNoteId],
    queryFn: () => api<NoteRow>(`/api/v1/scribe/notes/${signedNoteId}`),
    enabled: Boolean(signedNoteId),
  });

  const transcriptQuery = useQuery({
    queryKey: ["scribe", "transcript", selectedId],
    queryFn: () => api<Transcript>(`/api/v1/scribe/encounters/${selectedId}/transcript`),
    enabled: Boolean(selectedId),
    retry: false,
  });

  const effectiveRunId = runId ?? encounterQuery.data?.latest_run_id ?? null;
  const runQuery = useQuery({
    queryKey: ["scribe", "run", effectiveRunId],
    queryFn: () => api<ScribeRun>(`/api/v1/scribe/runs/${effectiveRunId}`),
    enabled: Boolean(effectiveRunId),
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 2000 : false,
  });

  const appointmentsQuery = useQuery({
    queryKey: ["scribe", "appointments", "confirmed"],
    queryFn: () =>
      api<GridResponse<Appointment>>(
        `/api/v1/appointments${qs({
          status: "confirmed",
          page_size: 100,
          sort: "starts_at",
          order: "asc",
        })}`,
      ),
    enabled: newOpen && kind === "scheduled",
  });

  const preconsultQuery = useQuery({
    queryKey: ["scribe", "preconsult", appointmentId],
    queryFn: () =>
      api<PreconsultBrief>(
        `/api/v1/scribe/preconsult${qs({ appointment_id: appointmentId || undefined })}`,
      ),
    enabled: Boolean(appointmentId) && (newOpen || Boolean(selectedId)),
  });

  const createEncounter = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<Encounter>("/api/v1/scribe/encounters", { method: "POST", body }),
    onSuccess: (encounter) => {
      setNewOpen(false);
      setNewPatient(null);
      setAppointmentId("");
      setNewError(null);
      setSelectedId(encounter.id);
      setRunId(null);
      setNotice(null);
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["scribe", "encounters"] });
    },
    onError: (error) => setNewError(errorMessage(error)),
  });

  const closeEncounter = useMutation({
    mutationFn: (encounterId: string) =>
      api<Encounter>(`/api/v1/scribe/encounters/${encounterId}/close`, { method: "POST" }),
    onSuccess: () => {
      setCloseConfirm(false);
      void queryClient.invalidateQueries({ queryKey: ["scribe"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const addTranscript = useMutation({
    mutationFn: (payload: {
      encounterId: string;
      language: string;
      turns: { speaker: string; text: string; start_ms: number; end_ms: number }[];
    }) =>
      api<Transcript>(`/api/v1/scribe/encounters/${payload.encounterId}/transcripts`, {
        method: "POST",
        body: { language: payload.language, turns: payload.turns },
      }),
    onSuccess: (_data, payload) => {
      const last = payload.turns[payload.turns.length - 1];
      setTurns([{ speaker: speakerAfter(last?.speaker), text: "" }]);
      setTranscriptError(null);
      setNotice(t("scribe.transcriptSaved"));
      void queryClient.invalidateQueries({ queryKey: ["scribe", "transcript", selectedId] });
      void queryClient.invalidateQueries({ queryKey: ["scribe", "encounter", selectedId] });
      void queryClient.invalidateQueries({ queryKey: ["scribe", "encounters"] });
    },
    onError: (error) => setTranscriptError(errorMessage(error)),
  });

  const startDraft = useMutation({
    mutationFn: (payload: { encounterId: string; transcriptId: string }) =>
      api<ScribeRun>(`/api/v1/scribe/encounters/${payload.encounterId}/runs`, {
        method: "POST",
        body: { transcript_id: payload.transcriptId },
      }),
    onSuccess: (run) => {
      setRunId(run.id);
      setEditing(false);
      setDraftError(null);
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["scribe", "encounter", selectedId] });
      void queryClient.invalidateQueries({ queryKey: ["scribe", "encounters"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const acknowledge = useMutation({
    mutationFn: (id: string) =>
      api<ScribeRun>(`/api/v1/scribe/runs/${id}/acknowledge`, { method: "POST" }),
    onSuccess: (run) => {
      setNotice(t("scribe.acknowledged"));
      queryClient.setQueryData(["scribe", "run", run.id], run);
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const saveDraft = useMutation({
    mutationFn: (payload: { runId: string; content: ScribeDraft["content"] }) =>
      api<ScribeRun>(`/api/v1/scribe/runs/${payload.runId}/draft`, {
        method: "PATCH",
        body: { content: payload.content },
      }),
    onSuccess: (run) => {
      setEditing(false);
      setDraftError(null);
      setNotice(t("scribe.draftSaved"));
      queryClient.setQueryData(["scribe", "run", run.id], run);
    },
    onError: (error) => setDraftError(errorMessage(error)),
  });

  const rejectRun = useMutation({
    mutationFn: (payload: { runId: string; category: string; comment: string }) =>
      api<ScribeRun>(`/api/v1/scribe/runs/${payload.runId}/reject`, {
        method: "POST",
        body: { category: payload.category, comment: payload.comment },
      }),
    onSuccess: (run) => {
      setRejectOpen(false);
      setRejectComment("");
      setRejectError(null);
      setNotice(t("common.saved"));
      queryClient.setQueryData(["scribe", "run", run.id], run);
      void queryClient.invalidateQueries({ queryKey: ["scribe", "encounters"] });
    },
    onError: (error) => setRejectError(errorMessage(error)),
  });

  const downloadNote = useMutation({
    mutationFn: (noteId: string) => apiDownload(`/api/v1/scribe/notes/${noteId}/download`),
    onSuccess: ({ blob, filename }) => saveBlob(blob, filename),
    onError: (error) => setActionError(errorMessage(error)),
  });

  const signRun = useMutation({
    mutationFn: (payload: { runId: string; comment: string }) =>
      api<SignatureResult>(`/api/v1/scribe/runs/${payload.runId}/sign`, {
        method: "POST",
        body: { attestation: true, comment: payload.comment || undefined },
      }),
    onSuccess: (signature) => {
      setSignOpen(false);
      setAttestation(false);
      setSignComment("");
      setSignError(null);
      setSignResult(signature);
      setNotice(t("scribe.signed", { version: signature.version }));
      setRunId(null);
      void queryClient.invalidateQueries({ queryKey: ["scribe"] });
      void queryClient.invalidateQueries({ queryKey: ["notes"] });
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (error) => setSignError(errorMessage(error)),
  });

  useEffect(() => {
    setRunId(null);
    setEditing(false);
    setSignResult(null);
    setNotice(null);
    setActionError(null);
    setTranscriptOpen(true);
    setTurns([{ speaker: "doctor", text: "" }]);
    setTranscriptError(null);
    setListening(false);
    setInterimText("");
    recognitionRef.current?.stop();
    if (selectedId) window.scrollTo({ top: 0 });
    recognitionRef.current = null;
  }, [selectedId]);

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      recognitionRef.current = null;
    };
  }, []);

  useEffect(() => {
    const saved = transcriptQuery.data?.turns;
    if (!saved?.length) return;
    const speaker = speakerAfter(saved[saved.length - 1]?.speaker);
    setTurns((current) => {
      if (current.some((turn) => turn.text.trim()) || current.length !== 1) return current;
      if (current[0]?.speaker === speaker) return current;
      return [{ speaker, text: "" }];
    });
  }, [transcriptQuery.data]);

  const run = runQuery.data;
  const transcript = transcriptQuery.data;
  const encounter = encounterQuery.data;
  const canStartDraft =
    encounter?.status === "active" &&
    !encounter.note_id &&
    transcript?.status === "ready" &&
    (transcript.turns?.length ?? 0) > 0 &&
    (!run || ["failed", "rejected"].includes(run.status));

  const appendSpokenText = (text: string) => {
    const cleaned = text.trim().replace(/\s+/g, " ");
    if (!cleaned) return;
    setTurns((current) => {
      const next = [...current];
      const last = next[next.length - 1];
      if (last && !last.text.trim()) {
        next[next.length - 1] = { ...last, text: cleaned };
        return next;
      }
      if (last) {
        const previous = last.text.trim();
        const previousFold = previous.toLowerCase();
        const cleanedFold = cleaned.toLowerCase();
        if (cleanedFold === previousFold || cleanedFold.startsWith(previousFold)) {
          if (cleanedFold === previousFold) return next;
          next[next.length - 1] = { ...last, text: cleaned };
          return next;
        }
        next.push({ speaker: speakerAfter(last.speaker), text: cleaned });
        return next;
      }
      return [{ speaker: "doctor", text: cleaned }];
    });
    setTranscriptOpen(true);
  };

  const stopSpeaking = (announce = false) => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setListening(false);
    setInterimText("");
    if (announce) setNotice(t("scribe.dictationSaved"));
  };

  const startSpeaking = () => {
    const Ctor = speechRecognitionCtor();
    if (!Ctor) {
      setTranscriptError(t("scribe.speechUnsupported"));
      setTranscriptOpen(true);
      return;
    }
    setTranscriptError(null);
    setTranscriptOpen(true);
    const recognition = new Ctor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = locale.startsWith("hi")
      ? "hi-IN"
      : locale.startsWith("mr")
        ? "mr-IN"
        : "en-IN";
    recognition.onresult = (event) => {
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const piece = result[0]?.transcript ?? "";
        if (result.isFinal) appendSpokenText(piece);
        else interim += piece;
      }
      setInterimText(interim.trim());
    };
    recognition.onerror = (event) => {
      const code = event.error ?? "";
      if (code === "not-allowed" || code === "service-not-allowed") {
        setTranscriptError(t("scribe.speechDenied"));
      } else if (code !== "aborted") {
        setTranscriptError(t("scribe.speechError"));
      }
      stopSpeaking();
    };
    recognition.onend = () => {
      setListening(false);
      setInterimText("");
      recognitionRef.current = null;
    };
    try {
      recognitionRef.current = recognition;
      recognition.start();
      setListening(true);
    } catch {
      setTranscriptError(t("scribe.speechError"));
      stopSpeaking();
    }
  };

  const draft = run?.draft ?? null;
  const readOnly = run?.status === "signed";

  const startEdit = () => {
    if (!draft) return;
    setDraftSections({
      subjective: joined(draft.content, "subjective"),
      objective: joined(draft.content, "objective"),
      assessment: joined(draft.content, "assessment"),
      plan: joined(draft.content, "plan"),
    });
    setDraftError(null);
    setEditing(true);
  };

  const submitDraft = () => {
    if (!run || !draft) return;
    let content = draft.content;
    for (const key of SECTIONS) content = withSection(content, key, draftSections[key]);
    saveDraft.mutate({ runId: run.id, content });
  };

  const unsavedTurns = turns.filter((turn) => turn.text.trim().length > 0);

  const submitTranscript = () => {
    if (!selectedId) return;
    const valid = turns
      .map((turn, index) => ({
        speaker: turn.speaker,
        text: turn.text.trim(),
        start_ms: index * 60_000,
        end_ms: (index + 1) * 60_000,
      }))
      .filter((turn) => turn.text.length > 0);
    if (!valid.length) {
      setTranscriptError(t("scribe.transcriptNeedText"));
      setTranscriptOpen(true);
      return;
    }
    addTranscript.mutate({ encounterId: selectedId, language: transcriptLanguage, turns: valid });
  };

  const createEncounterNow = () => {
    if (kind === "scheduled") {
      if (!appointmentId) {
        setNewError(t("scribe.appointment"));
        return;
      }
      createEncounter.mutate({ kind, appointment_id: appointmentId });
      return;
    }
    if (!newPatient) {
      setNewError(t("records.selectPatient"));
      return;
    }
    createEncounter.mutate({
      kind,
      patient_id: newPatient.id,
      doctor_name: me.doctor_display_name || me.display_name || undefined,
    });
  };

  const encounterColumns: DataGridColumn<Encounter>[] = [
    {
      key: "patient",
      header: t("common.patient"),
      sortKey: "patient_name",
      render: (row) => (
        <div className="cell-stack">
          <strong>{row.patient_display_name ?? row.patient_id.slice(0, 8)}</strong>
          <span className="muted mono">{row.clinic_code}</span>
        </div>
      ),
    },
    {
      key: "kind",
      header: t("scribe.scheduled"),
      hideOnMobile: true,
      render: (row) => <Badge tone="neutral">{humanize(row.kind)}</Badge>,
    },
    {
      key: "status",
      header: t("common.status"),
      sortKey: "status",
      render: (row) => (
        <div className="cell-stack">
          <StatusBadge status={row.status} />
          {row.latest_run_status ? <span className="muted small">{humanize(row.latest_run_status)}</span> : null}
        </div>
      ),
    },
    {
      key: "started_at",
      header: t("patients.created"),
      sortKey: "started_at",
      hideOnMobile: true,
      render: (row) => <span className="muted">{formatDateTime(row.started_at, locale)}</span>,
    },
    {
      key: "actions",
      header: t("common.actions"),
      align: "right",
      width: "70px",
      render: (row) => (
        <IconButton
          label={t("common.view")}
          icon={<Stethoscope size={16} />}
          onClick={() => setSelectedId(row.id)}
        />
      ),
    },
  ];

  const appointments = useMemo(() => appointmentsQuery.data?.items ?? [], [appointmentsQuery.data]);

  return (
    <>
      <PageHeader
        title={t("scribe.title")}
        subtitle={t("scribe.subtitle")}
        actions={
          <button type="button" className="btn btn-primary" data-testid="scribe-new-encounter" onClick={() => setNewOpen(true)}>
            <Plus size={16} aria-hidden="true" /> {t("scribe.newEncounter")}
          </button>
        }
      />

      {notice ? (
        <Callout tone="success" title={t("common.saved")}>
          {notice}
        </Callout>
      ) : null}
      {actionError ? (
        <Callout tone="danger" title={t("common.errorTitle")}>
          {actionError}
        </Callout>
      ) : null}

      {selectedId ? null : (
        <DataGrid
          columns={encounterColumns}
          items={encountersQuery.data?.items}
          meta={encountersQuery.data?.meta}
          loading={encountersQuery.isFetching}
          error={encountersQuery.error}
          grid={grid}
          rowKey={(row) => row.id}
          onRetry={() => void encountersQuery.refetch()}
          onRowClick={(row) => setSelectedId(row.id)}
          searchPlaceholder={t("common.searchPlaceholder")}
          filters={
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                grid.setPage(1);
              }}
              aria-label={t("common.status")}
            >
              <option value="">{t("common.all")}</option>
              {ENCOUNTER_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {humanize(status)}
                </option>
              ))}
            </select>
          }
          emptyTitle={t("scribe.noEncounters")}
        />
      )}

      {selectedId ? (
        <section className="scribe-workspace">
          <button
            type="button"
            className="btn btn-sm scribe-back"
            data-testid="scribe-back-encounters"
            onClick={() => setSelectedId(null)}
          >
            {t("common.back")}
          </button>
          {encounterQuery.isPending ? (
            <Spinner />
          ) : encounterQuery.isError ? (
            <FormError message={errorMessage(encounterQuery.error)} />
          ) : encounter ? (
            <>
              <header className="workspace-head">
                <div>
                  <h2>{encounter.patient_display_name ?? encounter.patient_id.slice(0, 8)}</h2>
                  <p className="muted">
                    {encounter.clinic_code} · {formatDateTime(encounter.started_at, locale)} ·{" "}
                    {humanize(encounter.kind)}
                  </p>
                </div>
                <div className="workspace-actions">
                  <StatusBadge status={encounter.status} />
                  {encounter.note_id ? (
                    <Badge tone="success">
                      <CheckCircle2 size={12} aria-hidden="true" /> {t("scribe.sign")}
                    </Badge>
                  ) : null}
                  {encounter.status === "active" ? (
                    <button type="button" className="btn btn-sm" onClick={() => setCloseConfirm(true)}>
                      {t("common.close")}
                    </button>
                  ) : null}
                </div>
              </header>

              {encounter.note_id ? (
                <Callout tone="success" title={t("scribe.sign")}>
                  <p>{t("scribe.signedLocked")}</p>
                </Callout>
              ) : (
                <Callout tone="info" title={t("scribe.speakTitle")}>
                  <p>{t("scribe.speakSteps")}</p>
                  <p className="muted small">
                    {t("scribe.speakHint")} {t("scribe.consentMic")}
                  </p>
                </Callout>
              )}

              <div className="scribe-grid">
                <section className="panel">
                  <div className="panel-head">
                    <h3>
                      <Mic size={16} aria-hidden="true" /> {t("scribe.transcript")}
                    </h3>
                    {encounter.status === "active" && !encounter.note_id ? (
                      <div className="button-row">
                        {listening ? (
                          <button
                            type="button"
                            className="btn btn-sm btn-danger"
                            data-testid="scribe-stop-speaking"
                            onClick={() => stopSpeaking(true)}
                          >
                            <MicOff size={14} aria-hidden="true" /> {t("scribe.stopSpeaking")}
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-sm btn-primary"
                            data-testid="scribe-start-speaking"
                            onClick={startSpeaking}
                          >
                            <Mic size={14} aria-hidden="true" /> {t("scribe.startSpeaking")}
                          </button>
                        )}
                      </div>
                    ) : null}
                  </div>
                  {listening ? (
                    <p className="listening-pill" aria-live="polite">
                      <span className="listening-dot" aria-hidden="true" />
                      {t("scribe.listening")}
                      {interimText ? ` — ${interimText}` : ""}
                    </p>
                  ) : null}
                  {!speechSupported ? (
                    <p className="muted small">{t("scribe.speechUnsupported")}</p>
                  ) : null}
                  {transcriptQuery.isPending ? (
                    <Spinner />
                  ) : transcriptQuery.isError ? (
                    isApiError(transcriptQuery.error) && transcriptQuery.error.status === 404 ? (
                      <p className="muted">{t("scribe.transcriptEmpty")}</p>
                    ) : (
                      <FormError message={errorMessage(transcriptQuery.error)} />
                    )
                  ) : transcript ? (
                    <div className="stack">
                      <div className="detail-row">
                        <StatusBadge status={transcript.status} />
                        <Badge tone="neutral">{humanize(transcript.language)}</Badge>
                        {transcript.error_code ? (
                          <code className="mono danger-text">{transcript.error_code}</code>
                        ) : null}
                      </div>
                      {transcript.turns.length === 0 ? (
                        <p className="muted">{t("scribe.transcriptEmpty")}</p>
                      ) : (
                        <ol className="turn-list" data-testid="scribe-saved-turns">
                          {transcript.turns.map((turn) => (
                            <li key={turn.id} className={`turn turn-${turn.speaker}`}>
                              <span className="turn-speaker">{humanize(turn.speaker)}</span>
                              <p>{turn.text}</p>
                            </li>
                          ))}
                        </ol>
                      )}
                      {unsavedTurns.length > 0 ? (
                        <div className="stack">
                          <p className="muted small">{t("scribe.unsavedDraft")}</p>
                          <ol className="turn-list turn-list-unsaved">
                            {unsavedTurns.map((turn, index) => (
                              <li key={`unsaved-${index}`} className={`turn turn-${turn.speaker}`}>
                                <span className="turn-speaker">{humanize(turn.speaker)}</span>
                                <p>{turn.text}</p>
                              </li>
                            ))}
                          </ol>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </section>

                <section className="panel">
                  <div className="panel-head">
                    <h3>
                      <PencilLine size={16} aria-hidden="true" />{" "}
                      {encounter.note_id ? t("scribe.sign") : t("scribe.draft")}
                    </h3>
                    {encounter.note_id ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        data-testid="scribe-download-note"
                        disabled={downloadNote.isPending}
                        onClick={() => downloadNote.mutate(encounter.note_id!)}
                      >
                        {downloadNote.isPending ? (
                          <Spinner />
                        ) : (
                          <Download size={14} aria-hidden="true" />
                        )}
                        {t("scribe.downloadNote")}
                      </button>
                    ) : canStartDraft && transcript ? (
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={startDraft.isPending}
                        data-testid="scribe-generate-draft"
                        onClick={() =>
                          startDraft.mutate({ encounterId: encounter.id, transcriptId: transcript.id })
                        }
                      >
                        {startDraft.isPending ? <Spinner /> : <FilePlus2 size={14} aria-hidden="true" />}
                        {t("scribe.startDraft")}
                      </button>
                    ) : null}
                  </div>

                  {encounter.note_id ? (
                    noteQuery.isPending ? (
                      <Spinner />
                    ) : noteQuery.isError ? (
                      <FormError message={errorMessage(noteQuery.error)} />
                    ) : noteQuery.data?.content ? (
                      <div className="signed-sheet" data-testid="signed-note">
                        <ClinicalRecord
                          content={{
                            ...noteQuery.data.content,
                            medicines: noteQuery.data.content.medicines ?? [],
                          }}
                        />
                        <footer className="signature-block">
                          <h4>{t("scribe.digitalSignature")}</h4>
                          <p>
                            {t("scribe.signedBy")} {noteQuery.data.signed_by}
                          </p>
                          <p>{formatDateTime(noteQuery.data.signed_at, locale)}</p>
                          <p>
                            {t("scribe.signatureHash")}{" "}
                            <code className="mono">{noteQuery.data.signed_hash}</code>
                          </p>
                          <p className="muted small">v{noteQuery.data.current_version}</p>
                        </footer>
                      </div>
                    ) : (
                      <p className="muted">{t("scribe.signedLocked")}</p>
                    )
                  ) : !effectiveRunId ? (
                    <p className="muted">
                      {canStartDraft ? t("scribe.startDraft") : t("scribe.draftNeedsTranscript")}
                    </p>
                  ) : runQuery.isPending ? (
                    <div className="loading-row">
                      <LoaderCircle className="spin" size={18} aria-hidden="true" />
                      <span>{t("common.loading")}</span>
                    </div>
                  ) : runQuery.isError ? (
                    <FormError message={errorMessage(runQuery.error)} />
                  ) : run ? (
                    <div className="stack">
                      <div className="detail-row">
                        <StatusBadge status={run.status} />
                        <Badge tone="neutral">v{run.revision}</Badge>
                        {run.model_alias ? <code className="mono muted">{run.model_alias}</code> : null}
                        {run.trace_id ? (
                          <span className="muted small">
                            {t("admin.traceId")} <code className="mono">{run.trace_id}</code>
                          </span>
                        ) : null}
                        {run.status === "draft" ? <span className="muted">{t("scribe.editDraft")}</span> : null}
                      </div>

                      {run.red_flags.length ? (
                        <Callout tone={run.status === "blocked" ? "danger" : "warning"} title={t("scribe.redFlags")}>
                          <ul className="flag-list">
                            {run.red_flags.map((flag) => (
                              <li key={flag.rule_id}>
                                <Badge tone={flag.severity === "emergency" ? "danger" : "warning"}>
                                  {humanize(flag.severity)}
                                </Badge>
                                <strong>{flag.name}</strong>
                                <span>{flag.guidance}</span>
                              </li>
                            ))}
                          </ul>
                          {run.status === "blocked" ? (
                            <button
                              type="button"
                              className="btn btn-danger btn-sm"
                              disabled={acknowledge.isPending}
                              onClick={() => acknowledge.mutate(run.id)}
                            >
                              {acknowledge.isPending ? <Spinner /> : <ShieldAlert size={14} aria-hidden="true" />}
                              {t("scribe.acknowledge")}
                            </button>
                          ) : null}
                        </Callout>
                      ) : null}

                      {run.status === "running" ? (
                        <div className="loading-row">
                          <LoaderCircle className="spin" size={18} aria-hidden="true" />
                          <span>{t("common.loading")}</span>
                        </div>
                      ) : null}

                      {run.status === "failed" ? (
                        <Callout tone="danger" title={t("scribe.runFailed")}>
                          {run.error_code ? <code className="mono">{run.error_code}</code> : null}
                          {run.error_detail ? <p>{run.error_detail}</p> : null}
                        </Callout>
                      ) : null}

                      {run.status === "rejected" ? (
                        <Callout tone="warning" title={t("scribe.reject")}>
                          {run.rejection_reason} ({humanize(run.rejection_category ?? "")})
                        </Callout>
                      ) : null}

                      {draft ? (
                        <>
                          <div className="workspace-actions">
                            {run.status === "draft" && !editing ? (
                              <button type="button" className="btn btn-sm" onClick={startEdit}>
                                <PencilLine size={14} aria-hidden="true" /> {t("scribe.editDraft")}
                              </button>
                            ) : null}
                            {run.status === "draft" ? (
                              <>
                                <button
                                  type="button"
                                  className="btn btn-sm"
                                  onClick={() => {
                                    setRejectOpen(true);
                                    setRejectError(null);
                                  }}
                                >
                                  <XCircle size={14} aria-hidden="true" /> {t("scribe.reject")}
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-primary btn-sm"
                                  data-testid="scribe-open-sign"
                                  onClick={() => {
                                    setSignOpen(true);
                                    setSignError(null);
                                  }}
                                >
                                  <CheckCircle2 size={14} aria-hidden="true" /> {t("scribe.sign")}
                                </button>
                              </>
                            ) : null}
                          </div>

                          {editing ? (
                            <div className="stack">
                              {SECTIONS.map((key) => (
                                <Field key={key} label={humanize(key)}>
                                  <textarea
                                    rows={4}
                                    value={draftSections[key]}
                                    onChange={(event) =>
                                      setDraftSections((current) => ({
                                        ...current,
                                        [key]: event.target.value,
                                      }))
                                    }
                                  />
                                </Field>
                              ))}
                              <FormError message={draftError} />
                              <div className="button-row">
                                <button type="button" className="btn" onClick={() => setEditing(false)}>
                                  {t("common.cancel")}
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-primary"
                                  disabled={saveDraft.isPending}
                                  onClick={submitDraft}
                                >
                                  {saveDraft.isPending ? <Spinner /> : null}
                                  {t("scribe.saveDraft")}
                                </button>
                              </div>
                            </div>
                          ) : (
                            <ClinicalRecord
                              content={{
                                ...draft.content,
                                medicines: draft.content.medicines ?? [],
                              }}
                            />
                          )}

                          {readOnly ? (
                            <Callout tone="success" title={t("scribe.sign")}>
                              {t("scribe.signed", { version: run.revision })}
                            </Callout>
                          ) : null}
                        </>
                      ) : null}

                      {signResult ? (
                        <Callout tone="success" title={t("scribe.signed", { version: signResult.version })}>
                          <p>
                            {t("scribe.signatureHash")}: <code className="mono">{signResult.content_hash}</code>
                          </p>
                          <p>
                            {signResult.patient_notified
                              ? t("scribe.patientNotified")
                              : t("scribe.patientNotNotified")}
                          </p>
                        </Callout>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              </div>

              {encounter.status === "active" && !encounter.note_id && transcriptOpen ? (
                <section className="panel transcript-form" data-testid="scribe-transcript-editor">
                  <div className="panel-head">
                    <h3>{t("scribe.addTranscript")}</h3>
                  </div>
                  <Field label={t("scribe.transcriptLanguage")}>
                    <select
                      value={transcriptLanguage}
                      onChange={(event) => setTranscriptLanguage(event.target.value)}
                    >
                      {LANGUAGES.map((code) => (
                        <option key={code} value={code}>
                          {humanize(code)}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <div className="turn-editor">
                    {turns.map((turn, index) => (
                      <div className="turn-edit-row" key={index}>
                        <select
                          value={turn.speaker}
                          onChange={(event) =>
                            setTurns((current) =>
                              current.map((item, itemIndex) =>
                                itemIndex === index
                                  ? { ...item, speaker: event.target.value as TurnDraft["speaker"] }
                                  : item,
                              ),
                            )
                          }
                          aria-label={t("scribe.speaker")}
                        >
                          {SPEAKERS.map((speaker) => (
                            <option key={speaker} value={speaker}>
                              {humanize(speaker)}
                            </option>
                          ))}
                        </select>
                        <textarea
                          rows={2}
                          value={turn.text}
                          onChange={(event) =>
                            setTurns((current) =>
                              current.map((item, itemIndex) =>
                                itemIndex === index ? { ...item, text: event.target.value } : item,
                              ),
                            )
                          }
                          placeholder={t("scribe.text")}
                          aria-label={t("scribe.text")}
                        />
                        <IconButton
                          label={t("common.delete")}
                          icon={<Trash2 size={15} />}
                          disabled={turns.length === 1}
                          onClick={() =>
                            setTurns((current) => current.filter((_, itemIndex) => itemIndex !== index))
                          }
                        />
                      </div>
                    ))}
                  </div>
                  <div className="button-row">
                    <button
                      type="button"
                      className="btn"
                      onClick={() =>
                        setTurns((current) => [
                          ...current,
                          { speaker: speakerAfter(current[current.length - 1]?.speaker), text: "" },
                        ])
                      }
                    >
                      <Plus size={15} aria-hidden="true" /> {t("scribe.addTurn")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={addTranscript.isPending}
                      data-testid="scribe-submit-transcript"
                      onClick={submitTranscript}
                    >
                      {addTranscript.isPending ? <Spinner /> : <FilePlus2 size={15} aria-hidden="true" />}
                      {t("scribe.saveTranscript")}
                    </button>
                  </div>
                  <FormError message={transcriptError} />
                </section>
              ) : null}
            </>
          ) : null}
        </section>
      ) : null}

      <Modal
        open={newOpen}
        title={t("scribe.newEncounter")}
        onClose={() => setNewOpen(false)}
        busy={createEncounter.isPending}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setNewOpen(false)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={createEncounter.isPending}
              data-testid="scribe-start-encounter"
              onClick={createEncounterNow}
            >
              {createEncounter.isPending ? <Spinner /> : <Plus size={15} aria-hidden="true" />}
              {t("scribe.startEncounter")}
            </button>
          </>
        }
      >
        <div className="stack">
          <div className="segmented" role="group" aria-label={t("scribe.newEncounter")}>
            <button
              type="button"
              className={kind === "walk_in" ? "is-active" : ""}
              onClick={() => setKind("walk_in")}
            >
              {t("scribe.walkIn")}
            </button>
            <button
              type="button"
              className={kind === "scheduled" ? "is-active" : ""}
              onClick={() => setKind("scheduled")}
            >
              {t("scribe.scheduled")}
            </button>
          </div>
          {kind === "walk_in" ? (
            <Field label={t("common.patient")} required>
              <PatientPicker value={newPatient} onChange={setNewPatient} />
            </Field>
          ) : (
            <Field
              label={t("scribe.appointment")}
              required
              hint={
                appointmentsQuery.isPending
                  ? t("common.loading")
                  : !appointments.length
                    ? t("appointments.noSlots")
                    : t("appointments.slotsHint")
              }
            >
              <select value={appointmentId} onChange={(event) => setAppointmentId(event.target.value)}>
                <option value="">{t("scribe.appointment")}</option>
                {appointments.map((appointment) => (
                  <option key={appointment.id} value={appointment.id}>
                    {formatDateTime(appointment.starts_at, locale)} · {appointment.doctor_name} ·{" "}
                    {appointment.clinic_code}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {kind === "scheduled" ? (
            <section className="stack" aria-label={t("scribe.preconsult")}>
              <h3>{t("scribe.preconsult")}</h3>
              <p className="muted small">{t("scribe.preconsultHint")}</p>
              {!appointmentId ? (
                <p className="muted">{t("scribe.preconsultEmpty")}</p>
              ) : preconsultQuery.isPending ? (
                <Spinner />
              ) : preconsultQuery.data?.status === "ok" ? (
                <div className="stack">
                  {(preconsultQuery.data.active_medications?.length ?? 0) > 0 ? (
                    <div>
                      <strong>{t("scribe.preconsultMeds")}</strong>
                      <ul>
                        {preconsultQuery.data.active_medications?.map((med) => (
                          <li key={med.id}>
                            {med.name}
                            {med.dose ? ` · ${med.dose}` : ""}
                            {med.frequency ? ` · ${med.frequency}` : ""}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {(preconsultQuery.data.documents?.length ?? 0) > 0 ? (
                    <div>
                      <strong>{t("scribe.preconsultDocs")}</strong>
                      <ul>
                        {preconsultQuery.data.documents?.map((doc) => (
                          <li key={doc.id}>
                            {doc.title} <span className="muted mono">[{doc.citation}]</span>
                            {doc.quarantined ? (
                              <Badge tone="danger">quarantined</Badge>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {preconsultQuery.data.last_signed_note ? (
                    <div>
                      <strong>{t("scribe.preconsultLastNote")}</strong>
                      <p className="muted small">
                        {preconsultQuery.data.last_signed_note.title}
                        {preconsultQuery.data.last_signed_note.signed_at
                          ? ` · ${formatDateTime(preconsultQuery.data.last_signed_note.signed_at, locale)}`
                          : ""}
                      </p>
                      <ul>
                        {(preconsultQuery.data.last_signed_note.assessment ?? []).map((line) => (
                          <li key={`a-${line}`}>{line}</li>
                        ))}
                        {(preconsultQuery.data.last_signed_note.plan ?? []).map((line) => (
                          <li key={`p-${line}`}>{line}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              ) : (
                <FormError message={errorMessage(preconsultQuery.error)} />
              )}
            </section>
          ) : null}
          <FormError message={newError} />
        </div>
      </Modal>

      <ConfirmDialog
        open={closeConfirm}
        title={t("common.close")}
        body={t("scribe.consentNote")}
        confirmLabel={t("common.close")}
        tone="danger"
        busy={closeEncounter.isPending}
        onClose={() => setCloseConfirm(false)}
        onConfirm={() => selectedId && closeEncounter.mutate(selectedId)}
      />

      <Modal
        open={signOpen}
        title={t("scribe.sign")}
        onClose={() => setSignOpen(false)}
        busy={signRun.isPending}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setSignOpen(false)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!attestation || signRun.isPending}
              data-testid="scribe-confirm-sign"
              onClick={() => run && signRun.mutate({ runId: run.id, comment: signComment })}
            >
              {signRun.isPending ? <Spinner /> : <CheckCircle2 size={15} aria-hidden="true" />}
              {t("scribe.sign")}
            </button>
          </>
        }
      >
        <div className="stack">
          <label className="check-row">
            <input
              type="checkbox"
              checked={attestation}
              data-testid="scribe-attestation"
              onChange={(event) => setAttestation(event.target.checked)}
            />
            <span>{t("scribe.signAttestation")}</span>
          </label>
          <Field label={t("scribe.signComment")}>
            <textarea rows={3} value={signComment} maxLength={500} onChange={(event) => setSignComment(event.target.value)} />
          </Field>
          <Callout tone="warning">{t("scribe.consentNote")}</Callout>
          <FormError message={signError} />
        </div>
      </Modal>

      <Modal
        open={rejectOpen}
        title={t("scribe.reject")}
        onClose={() => setRejectOpen(false)}
        busy={rejectRun.isPending}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setRejectOpen(false)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-danger"
              disabled={rejectRun.isPending || rejectComment.trim().length < 3}
              onClick={() =>
                run &&
                rejectRun.mutate({
                  runId: run.id,
                  category: rejectCategory,
                  comment: rejectComment.trim(),
                })
              }
            >
              {rejectRun.isPending ? <Spinner /> : <XCircle size={15} aria-hidden="true" />}
              {t("scribe.reject")}
            </button>
          </>
        }
      >
        <div className="stack">
          <Field label={t("scribe.rejectCategory")} required>
            <select value={rejectCategory} onChange={(event) => setRejectCategory(event.target.value)}>
              {REJECT_CATEGORIES.map((category) => (
                <option key={category} value={category}>
                  {humanize(category)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("scribe.rejectReason")} required>
            <textarea
              rows={3}
              value={rejectComment}
              maxLength={500}
              onChange={(event) => setRejectComment(event.target.value)}
            />
          </Field>
          <FormError message={rejectError} />
        </div>
      </Modal>
    </>
  );
}
