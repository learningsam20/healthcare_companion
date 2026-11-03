import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  FileCheck,
  History,
  PencilLine,
  Pill,
  ShieldAlert,
} from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import { Badge, StatusBadge } from "../components/Badge";
import { ClinicalRecord } from "../components/ClinicalRecord";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { Modal } from "../components/Modal";
import {
  Callout,
  Field,
  FormError,
  PageHeader,
  Spinner,
} from "../components/primitives";
import { api, apiDownload, errorMessage, qs, saveBlob } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, humanize } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type {
  GridResponse,
  NoteRow,
  NoteVersion,
  ScribeDraft,
  ScribeSource,
} from "../lib/types";

type SectionKey = "subjective" | "objective" | "assessment" | "plan";

const SECTIONS: SectionKey[] = ["subjective", "objective", "assessment", "plan"];

function sectionText(content: ScribeDraft["content"], key: SectionKey): string {
  return (content[key] ?? []).map((line) => line.text).join("\n");
}

function replaceSection(
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

function SourceRows({ sources }: { sources: ScribeSource[] }) {
  const { locale } = useI18n();
  if (!sources.length) return <p className="muted">—</p>;
  return (
    <ul className="source-list">
      {sources.map((source) => {
        const ref = source.source_ref as { title?: unknown; locator?: unknown };
        return (
          <li key={source.id} className="source-card">
            <div className="source-head">
              <div className="source-title">
                <span>
                  {typeof ref.title === "string" ? ref.title : humanize(source.source_type)}
                </span>
                {typeof ref.locator === "string" ? (
                  <code className="source-locator">{ref.locator}</code>
                ) : null}
              </div>
              <StatusBadge status={source.status} />
            </div>
            <div className="source-meta muted">
              <span>
                {source.field} · {humanize(source.source_type)} · #{source.line_index}
              </span>
              {source.as_of ? <span>{formatDateTime(source.as_of, locale)}</span> : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function NotesPage() {
  const { t, locale } = useI18n();
  const { me, hasRole } = useAuth();
  const queryClient = useQueryClient();
  const grid = useGridState("signed_at", "desc");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [showVersions, setShowVersions] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [correctionReason, setCorrectionReason] = useState("");
  const [sectionDrafts, setSectionDrafts] = useState<Record<SectionKey, string>>({
    subjective: "",
    objective: "",
    assessment: "",
    plan: "",
  });
  const [reserving, setReserving] = useState(false);
  const [medicineName, setMedicineName] = useState("");
  const [medicineQuery, setMedicineQuery] = useState("");
  const [stockComboOpen, setStockComboOpen] = useState(false);
  const [quantity, setQuantity] = useState(1);
  const [clinic, setClinic] = useState(me.clinic_ids[0] ?? "");
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const deferredMedicineQ = useDeferredValue(medicineQuery);

  const notesQuery = useQuery({
    queryKey: ["notes", grid.params],
    queryFn: () => api<GridResponse<NoteRow>>(`/api/v1/scribe/notes${qs(grid.params)}`),
    placeholderData: (previous) => previous,
  });

  const detailQuery = useQuery({
    queryKey: ["notes", "detail", detailId],
    queryFn: () => api<NoteRow>(`/api/v1/scribe/notes/${detailId}`),
    enabled: Boolean(detailId),
  });

  const versionsQuery = useQuery({
    queryKey: ["notes", "versions", detailId],
    queryFn: () => api<NoteVersion[]>(`/api/v1/scribe/notes/${detailId}/versions`),
    enabled: Boolean(detailId) && showVersions,
  });

  const sourcesQuery = useQuery({
    queryKey: ["notes", "sources", detailId],
    queryFn: () => api<ScribeSource[]>(`/api/v1/scribe/notes/${detailId}/sources`),
    enabled: Boolean(detailId) && showSources,
  });

  const stockSuggestionsQuery = useQuery({
    queryKey: ["pharmacy", "typeahead", "reserve", deferredMedicineQ, clinic],
    queryFn: () =>
      api<{ items: { id: string; drug_name: string; clinic_code: string; quantity: number; strength?: string }[] }>(
        `/api/v1/pharmacy/stock/typeahead${qs({
          q: deferredMedicineQ,
          clinic_code: clinic || undefined,
          limit: 8,
        })}`,
      ),
    enabled: reserving && deferredMedicineQ.trim().length >= 2,
  });

  const correctionMutation = useMutation({
    mutationFn: (payload: { noteId: string; content: ScribeDraft["content"]; reason: string }) =>
      api<NoteRow>(`/api/v1/scribe/notes/${payload.noteId}/corrections`, {
        method: "POST",
        body: { content: payload.content, reason: payload.reason },
      }),
    onSuccess: (updated) => {
      setCorrecting(false);
      setCorrectionReason("");
      setActionError(null);
      setNotice(t("common.saved"));
      queryClient.setQueryData(["notes", "detail", updated.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["notes"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const reserveMutation = useMutation({
    mutationFn: (payload: {
      noteId: string;
      medicine_name: string;
      clinic_code: string;
      quantity: number;
    }) =>
      api<unknown>(`/api/v1/scribe/notes/${payload.noteId}/reservations`, {
        method: "POST",
        body: {
          medicine_name: payload.medicine_name,
          clinic_code: payload.clinic_code,
          quantity: payload.quantity,
        },
      }),
    onSuccess: () => {
      setReserving(false);
      setMedicineName("");
      setMedicineQuery("");
      setQuantity(1);
      setActionError(null);
      setNotice(t("notes.reserved"));
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const downloadMutation = useMutation({
    mutationFn: (noteId: string) => apiDownload(`/api/v1/scribe/notes/${noteId}/download`),
    onSuccess: ({ blob, filename }) => saveBlob(blob, filename),
    onError: (error) => setActionError(errorMessage(error)),
  });

  const resetReserveForm = () => {
    setMedicineName("");
    setMedicineQuery("");
    setStockComboOpen(false);
    setQuantity(1);
    setClinic(me.clinic_ids[0] ?? "");
  };

  const openNote = (noteId: string) => {
    setDetailId(noteId);
    setShowVersions(false);
    setShowSources(false);
    setCorrecting(false);
    setReserving(false);
    resetReserveForm();
    setActionError(null);
    setNotice(null);
  };

  const toggleReserving = () => {
    setReserving((open) => {
      if (open) {
        resetReserveForm();
        return false;
      }
      return true;
    });
    setActionError(null);
  };

  const pickMedicine = (name: string, clinicCode?: string) => {
    setMedicineName(name);
    setMedicineQuery(name);
    setStockComboOpen(false);
    if (clinicCode) setClinic(clinicCode);
  };

  const note = detailQuery.data;
  const canCorrect = hasRole("doctor") && note?.author_subject === me.subject && !note.metadata_only;
  const canReserve = hasRole("doctor", "pharmacist") && Boolean(note);
  const medicines = useMemo(() => note?.content?.medicines ?? [], [note]);

  const startCorrection = () => {
    if (!note?.content) return;
    setSectionDrafts({
      subjective: sectionText(note.content, "subjective"),
      objective: sectionText(note.content, "objective"),
      assessment: sectionText(note.content, "assessment"),
      plan: sectionText(note.content, "plan"),
    });
    setCorrectionReason("");
    setCorrecting(true);
    setActionError(null);
  };

  const submitCorrection = () => {
    if (!note?.content || correctionReason.trim().length < 5) return;
    let content = note.content;
    for (const key of SECTIONS) content = replaceSection(content, key, sectionDrafts[key]);
    correctionMutation.mutate({
      noteId: note.id,
      content,
      reason: correctionReason.trim(),
    });
  };

  const columns: DataGridColumn<NoteRow>[] = [
    {
      key: "title",
      header: t("notes.note"),
      render: (row) => (
        <div className="cell-stack">
          <strong>{row.title}</strong>
          <span className="muted">{row.patient_display_name ?? row.patient_id.slice(0, 8)}</span>
        </div>
      ),
    },
    {
      key: "status",
      header: t("common.status"),
      render: (row) => (
        <div className="cell-stack">
          <StatusBadge status={row.status} />
          {row.metadata_only ? <Badge tone="neutral">{t("notes.metadataOnlyTitle")}</Badge> : null}
        </div>
      ),
    },
    {
      key: "version",
      header: t("notes.currentVersion"),
      render: (row) => <span className="mono">v{row.current_version}</span>,
    },
    {
      key: "signed_at",
      header: t("notes.signedBy"),
      hideOnMobile: true,
      render: (row) => (
        <div className="cell-stack">
          <span className="muted">{formatDateTime(row.signed_at, locale)}</span>
          <code className="mono muted">{row.signed_by.slice(0, 10)}…</code>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader title={t("notes.title")} subtitle={t("notes.subtitle")} />

      {notice ? (
        <Callout tone="success" title={t("common.saved")}>
          {notice}
        </Callout>
      ) : null}

      <DataGrid
        columns={columns}
        items={notesQuery.data?.items}
        meta={notesQuery.data?.meta}
        loading={notesQuery.isFetching}
        error={notesQuery.error}
        grid={grid}
        rowKey={(row) => row.id}
        onRetry={() => void notesQuery.refetch()}
        onRowClick={(row) => openNote(row.id)}
        searchPlaceholder={t("common.searchPlaceholder")}
        emptyTitle={t("notes.noNotes")}
      />

      <Modal
        open={Boolean(detailId)}
        title={note?.title ?? t("notes.note")}
        description={note ? `${note.patient_display_name ?? ""} · v${note.current_version}` : undefined}
        onClose={() => setDetailId(null)}
        size="xl"
        footer={
          note ? (
            <>
              <button
                type="button"
                className="btn"
                onClick={() => downloadMutation.mutate(note.id)}
                disabled={downloadMutation.isPending}
              >
                <Download size={15} aria-hidden="true" /> {t("notes.download")}
              </button>
              {canReserve ? (
                <button type="button" className="btn" onClick={toggleReserving}>
                  <Pill size={15} aria-hidden="true" /> {t("notes.reserveStock")}
                </button>
              ) : null}
              {canCorrect && !correcting ? (
                <button type="button" className="btn btn-primary" onClick={startCorrection}>
                  <PencilLine size={15} aria-hidden="true" /> {t("notes.corrections")}
                </button>
              ) : null}
            </>
          ) : null
        }
      >
        {detailQuery.isPending ? (
          <Spinner />
        ) : detailQuery.isError ? (
          <FormError message={errorMessage(detailQuery.error)} />
        ) : note ? (
          <div className="stack">
            <div className="detail-row">
              <StatusBadge status={note.status} />
              <Badge tone="neutral">v{note.current_version}</Badge>
              <Badge tone="neutral">{humanize(note.language)}</Badge>
              <span className="muted">{formatDateTime(note.signed_at, locale)}</span>
            </div>
            <div className="detail-row muted">
              <span>{t("notes.signedBy")}: <code className="mono">{note.signed_by}</code></span>
              <span className="mono">{note.signed_hash.slice(0, 16)}…</span>
            </div>

            {actionError ? <FormError message={actionError} /> : null}
            {notice ? <Callout tone="success">{notice}</Callout> : null}

            {note.metadata_only ? (
              <Callout tone="warning" title={t("notes.metadataOnlyTitle")}>
                {t("notes.metadataOnlyBody")}
              </Callout>
            ) : correcting && note.content ? (
              <div className="stack correction-form">
                <Callout tone="warning" title={t("notes.corrections")}>
                  {t("scribe.consentNote")}
                </Callout>
                {SECTIONS.map((key) => (
                  <Field key={key} label={humanize(key)}>
                    <textarea
                      rows={3}
                      value={sectionDrafts[key]}
                      onChange={(event) =>
                        setSectionDrafts((current) => ({ ...current, [key]: event.target.value }))
                      }
                    />
                  </Field>
                ))}
                <Field label={t("notes.correctionReason")} required>
                  <textarea
                    rows={2}
                    value={correctionReason}
                    maxLength={300}
                    onChange={(event) => setCorrectionReason(event.target.value)}
                  />
                </Field>
                <div className="button-row">
                  <button type="button" className="btn" onClick={() => setCorrecting(false)}>
                    {t("common.cancel")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={correctionMutation.isPending || correctionReason.trim().length < 5}
                    onClick={submitCorrection}
                  >
                    {correctionMutation.isPending ? <Spinner /> : null}
                    {t("notes.addCorrection")}
                  </button>
                </div>
              </div>
            ) : note.content ? (
              <ClinicalRecord content={note.content} />
            ) : (
              <p className="muted">{t("common.emptyTitle")}</p>
            )}

            {reserving ? (
              <div className="inline-form reserve-form">
                {medicines.length ? (
                  <div className="reserve-note-picks">
                    <span className="muted small">{t("notes.fromNote")}</span>
                    <div className="chip-row">
                      {medicines.map((medicine, index) => {
                        const name = medicine.name?.trim();
                        if (!name) return null;
                        const selected = medicineName.toLowerCase() === name.toLowerCase();
                        return (
                          <button
                            key={`${name}-${index}`}
                            type="button"
                            className={`chip${selected ? " is-selected" : ""}`}
                            onClick={() => pickMedicine(name)}
                          >
                            {name}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
                <Field label={t("notes.searchStock")} required>
                  <div className="combobox reserve-combobox">
                    <input
                      role="combobox"
                      aria-expanded={stockComboOpen && deferredMedicineQ.trim().length >= 2}
                      aria-controls="reserve-stock-list"
                      aria-autocomplete="list"
                      placeholder={t("notes.selectMedicine")}
                      value={medicineQuery}
                      onChange={(event) => {
                        setMedicineQuery(event.target.value);
                        setMedicineName(event.target.value);
                        setStockComboOpen(true);
                      }}
                      onFocus={() => setStockComboOpen(true)}
                      onBlur={() => window.setTimeout(() => setStockComboOpen(false), 120)}
                    />
                    {stockComboOpen &&
                    deferredMedicineQ.trim().length >= 2 &&
                    (stockSuggestionsQuery.data?.items.length ?? 0) > 0 ? (
                      <ul id="reserve-stock-list" role="listbox" className="combo-list">
                        {stockSuggestionsQuery.data?.items.map((item) => (
                          <li key={item.id} role="option">
                            <button
                              type="button"
                              className="combo-option"
                              onMouseDown={(event) => event.preventDefault()}
                              onClick={() => pickMedicine(item.drug_name, item.clinic_code)}
                            >
                              <strong>{item.drug_name}</strong>
                              <span className="muted small">
                                {item.clinic_code} · qty {item.quantity}
                                {item.strength ? ` · ${item.strength}` : ""}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </Field>
                <Field label={t("notes.quantity")} required>
                  <input
                    type="number"
                    min={1}
                    max={10000}
                    value={quantity}
                    onChange={(event) => setQuantity(Number(event.target.value))}
                  />
                </Field>
                <Field label={t("common.clinic")} required>
                  <select value={clinic} onChange={(event) => setClinic(event.target.value)}>
                    <option value="" disabled>
                      {t("notes.selectClinic")}
                    </option>
                    {me.clinic_ids.map((code) => (
                      <option key={code} value={code}>
                        {code}
                      </option>
                    ))}
                  </select>
                </Field>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={
                    reserveMutation.isPending ||
                    medicineName.trim().length === 0 ||
                    clinic.length === 0
                  }
                  onClick={() =>
                    note &&
                    reserveMutation.mutate({
                      noteId: note.id,
                      medicine_name: medicineName.trim(),
                      clinic_code: clinic,
                      quantity,
                    })
                  }
                >
                  {reserveMutation.isPending ? <Spinner /> : <Pill size={15} aria-hidden="true" />}
                  {t("notes.reserveStock")}
                </button>
              </div>
            ) : null}

            {!note.metadata_only ? (
              <div className="note-extras">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setShowVersions((value) => !value)}
                >
                  <History size={15} aria-hidden="true" /> {t("notes.versions")}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setShowSources((value) => !value)}
                >
                  <ShieldAlert size={15} aria-hidden="true" /> {t("notes.sources")}
                </button>
              </div>
            ) : null}

            {showVersions && !note.metadata_only ? (
              <section>
                <h3 className="section-title">{t("notes.versions")}</h3>
                {versionsQuery.isPending ? (
                  <Spinner />
                ) : versionsQuery.isError ? (
                  <FormError message={errorMessage(versionsQuery.error)} />
                ) : (
                  <ul className="version-list">
                    {(versionsQuery.data ?? []).map((version) => (
                      <li key={version.version} className="version-row">
                        <span className="version-badge">v{version.version}</span>
                        <div className="cell-stack">
                          <span className="mono">{version.content_hash.slice(0, 16)}…</span>
                          <span className="muted">
                            {formatDateTime(version.signed_at, locale)} ·{" "}
                            {version.parent_version
                              ? `${t("notes.parentVersion")} v${version.parent_version}`
                              : "—"}
                          </span>
                        </div>
                        <Badge tone="success">
                          <FileCheck size={12} aria-hidden="true" /> {t("common.active")}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ) : null}

            {showSources && !note.metadata_only ? (
              <section>
                <h3 className="section-title">{t("notes.sources")}</h3>
                {sourcesQuery.isPending ? (
                  <Spinner />
                ) : sourcesQuery.isError ? (
                  <FormError message={errorMessage(sourcesQuery.error)} />
                ) : (
                  <SourceRows sources={sourcesQuery.data ?? []} />
                )}
              </section>
            ) : null}

            <p className="muted small">{t("scribe.consentNote")}</p>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
