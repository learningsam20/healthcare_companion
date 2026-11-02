import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Download,
  Eye,
  FileText,
  RefreshCw,
  Search,
  Sparkles,
  Upload,
} from "lucide-react";
import { useState } from "react";
import { useLocation } from "react-router-dom";

import { Badge, StatusBadge } from "../components/Badge";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { IconButton } from "../components/IconButton";
import { Modal } from "../components/Modal";
import { PatientPicker } from "../components/PatientPicker";
import { SourceList } from "../components/SourceList";
import {
  Callout,
  EmptyState,
  Field,
  FormError,
  PageHeader,
  Spinner,
  Tabs,
} from "../components/primitives";
import { api, errorMessage, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatBytes, formatDateTime, humanize } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type {
  AskResult,
  DocumentChunk,
  DocumentRow,
  GridResponse,
  Medication,
  Meta,
  Patient,
  SearchHit,
} from "../lib/types";

const KINDS = ["lab_report", "discharge_summary", "prescription", "imaging", "other"];
const DOC_STATUSES = ["queued", "processing", "ready", "failed"];
const LANGUAGES = ["en-IN", "hi-IN", "mr-IN"];

interface UploadResult {
  document: DocumentRow;
  queued: boolean;
  warning: string | null;
}

interface SearchOut {
  query: string;
  patient_id: string;
  results: SearchHit[];
  evidence_count: number;
}

type RecordsResult =
  | { mode: "search"; data: SearchOut }
  | { mode: "ask"; data: AskResult };

export function RecordsPage() {
  const { t, locale } = useI18n();
  const { hasRole } = useAuth();
  const queryClient = useQueryClient();
  const location = useLocation();
  const routedPatient = (location.state as { patient?: Patient } | null)?.patient ?? null;

  const autoScoped = hasRole("patient", "caregiver");
  const [patient, setPatient] = useState<Patient | null>(autoScoped ? null : routedPatient);
  const patientId = autoScoped ? undefined : patient?.id;
  const hasScope = autoScoped || Boolean(patient);
  const [tab, setTab] = useState("documents");

  const [statusFilter, setStatusFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const documentsGrid = useGridState("created_at", "desc");
  const medicationsGrid = useGridState("name", "asc");

  const [detailId, setDetailId] = useState<string | null>(null);
  const [chunkPage, setChunkPage] = useState(1);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("lab_report");
  const [language, setLanguage] = useState("en-IN");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [mode, setMode] = useState<"search" | "ask">("ask");
  const [nursingSummary, setNursingSummary] = useState<{
    id: string;
    summary: string;
    status: string;
  } | null>(null);
  const metaQuery = useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/api/v1/meta"),
    staleTime: 120_000,
  });
  const nursingEnabled = Boolean(metaQuery.data?.capabilities?.x01_nursing_summary);
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(6);
  const [result, setResult] = useState<RecordsResult | null>(null);
  const [resultError, setResultError] = useState<string | null>(null);

  const documentsQuery = useQuery({
    queryKey: ["records", "documents", patientId, documentsGrid.params, statusFilter, kindFilter],
    queryFn: () =>
      api<GridResponse<DocumentRow>>(
        `/api/v1/records/documents${qs({
          ...documentsGrid.params,
          patient_id: patientId,
          status: statusFilter || undefined,
          kind: kindFilter || undefined,
        })}`,
      ),
    enabled: hasScope && tab === "documents",
    placeholderData: (previous) => previous,
  });

  const medicationsQuery = useQuery({
    queryKey: ["records", "medications", patientId, medicationsGrid.params],
    queryFn: () =>
      api<GridResponse<Medication>>(
        `/api/v1/records/medications${qs({
          ...medicationsGrid.params,
          patient_id: patientId,
        })}`,
      ),
    enabled: hasScope && tab === "medications",
    placeholderData: (previous) => previous,
  });

  const detailQuery = useQuery({
    queryKey: ["records", "document", detailId],
    queryFn: () => api<DocumentRow>(`/api/v1/records/documents/${detailId}`),
    enabled: Boolean(detailId),
  });

  const chunksQuery = useQuery({
    queryKey: ["records", "chunks", detailId, chunkPage],
    queryFn: () =>
      api<GridResponse<DocumentChunk>>(
        `/api/v1/records/documents/${detailId}/chunks${qs({ page: chunkPage, page_size: 10 })}`,
      ),
    enabled: Boolean(detailId),
    placeholderData: (previous) => previous,
  });

  const uploadMutation = useMutation({
    mutationFn: (form: FormData) =>
      api<UploadResult>("/api/v1/records/documents", { method: "POST", form }),
    onSuccess: (data) => {
      setUploadOpen(false);
      setFile(null);
      setTitle("");
      setUploadError(null);
      setUploadNotice(
        data.warning ? `${t("records.uploadQueued")} ${t("records.uploadWarning")}` : t("records.uploadQueued"),
      );
      void queryClient.invalidateQueries({ queryKey: ["records", "documents"] });
      void queryClient.invalidateQueries({ queryKey: ["records", "medications"] });
    },
    onError: (error) => setUploadError(errorMessage(error)),
  });

  const retryMutation = useMutation({
    mutationFn: (documentId: string) =>
      api<UploadResult>(`/api/v1/records/documents/${documentId}/ingest`, { method: "POST" }),
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["records", "documents"] });
      void queryClient.invalidateQueries({ queryKey: ["records", "document", detailId] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const downloadMutation = useMutation({
    mutationFn: (documentId: string) =>
      api<{ url: string; expires_in: number }>(
        `/api/v1/records/documents/${documentId}/download`,
      ),
    onSuccess: (data) => {
      setActionError(null);
      window.open(data.url, "_blank", "noopener,noreferrer");
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const askMutation = useMutation({
    mutationFn: async (payload: { mode: "search" | "ask"; text: string; topK: number }) => {
      const path = payload.mode === "ask" ? "/api/v1/records/ask" : "/api/v1/records/search";
      const body = {
        query: payload.text,
        patient_id: patientId,
        top_k: payload.topK,
      };
      if (payload.mode === "ask") {
        return { mode: "ask" as const, data: await api<AskResult>(path, { method: "POST", body }) };
      }
      return { mode: "search" as const, data: await api<SearchOut>(path, { method: "POST", body }) };
    },
    onSuccess: (data) => {
      setResult(data);
      setResultError(null);
    },
    onError: (error) => {
      setResult(null);
      setResultError(errorMessage(error));
    },
  });

  const openDocument = (documentId: string) => {
    setDetailId(documentId);
    setChunkPage(1);
    setActionError(null);
  };

  const submitUpload = () => {
    if (!file) {
      setUploadError(t("records.file"));
      return;
    }
    if (title.trim().length < 2) {
      setUploadError(t("records.uploadTitle"));
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("title", title.trim());
    form.append("kind", kind);
    form.append("language", language);
    if (patientId) form.append("patient_id", patientId);
    setUploadError(null);
    uploadMutation.mutate(form);
  };

  const submitQuestion = () => {
    if (query.trim().length < 2) return;
    askMutation.mutate({ mode, text: query.trim(), topK });
  };

  const documentColumns: DataGridColumn<DocumentRow>[] = [
    {
      key: "title",
      header: t("records.uploadTitle"),
      sortKey: "title",
      render: (row) => (
        <div className="cell-stack">
          <strong>{row.title}</strong>
          <span className="muted mono">
            {row.kind} · {formatBytes(row.size_bytes)}
          </span>
        </div>
      ),
    },
    {
      key: "language",
      header: t("common.language"),
      hideOnMobile: true,
      render: (row) => <span>{humanize(row.language)}</span>,
    },
    {
      key: "status",
      header: t("records.documentStatus"),
      sortKey: "status",
      render: (row) => (
        <div className="cell-stack">
          <StatusBadge status={row.status} />
          {row.error_code ? <code className="mono muted">{row.error_code}</code> : null}
        </div>
      ),
    },
    {
      key: "created_at",
      header: t("patients.created"),
      sortKey: "created_at",
      hideOnMobile: true,
      render: (row) => <span className="muted">{formatDateTime(row.created_at, locale)}</span>,
    },
    {
      key: "actions",
      header: t("common.actions"),
      align: "right",
      width: "110px",
      render: (row) => (
        <div className="row-actions">
          <IconButton
            label={t("records.viewDocument")}
            icon={<Eye size={16} />}
            onClick={() => openDocument(row.id)}
          />
          {row.status === "failed" ? (
            <IconButton
              label={t("records.retryIngest")}
              icon={<RefreshCw size={16} />}
              disabled={retryMutation.isPending}
              onClick={() => retryMutation.mutate(row.id)}
            />
          ) : null}
        </div>
      ),
    },
  ];

  const medicationColumns: DataGridColumn<Medication>[] = [
    {
      key: "name",
      header: t("records.medName"),
      render: (row) => <strong>{row.name}</strong>,
    },
    {
      key: "dose",
      header: t("records.dose"),
      hideOnMobile: true,
      render: (row) => row.dose ?? <span className="muted">—</span>,
    },
    {
      key: "frequency",
      header: t("records.frequency"),
      render: (row) => row.frequency ?? <span className="muted">—</span>,
    },
    {
      key: "status",
      header: t("common.status"),
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "dates",
      header: t("records.started"),
      hideOnMobile: true,
      render: (row) => (
        <span className="muted">
          {row.started_on ? formatDateTime(row.started_on, locale) : "—"}
          {row.ended_on ? ` → ${formatDateTime(row.ended_on, locale)}` : ""}
        </span>
      ),
    },
  ];

  const phaseLabel = mode === "ask" ? t("records.ask") : t("records.search");

  return (
    <>
      <PageHeader
        title={t("records.title")}
        subtitle={t("records.subtitle")}
        actions={
          hasScope ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setUploadOpen(true);
                setUploadNotice(null);
              }}
            >
              <Upload size={16} aria-hidden="true" /> {t("records.upload")}
            </button>
          ) : null
        }
      />

      {!autoScoped ? (
        <section className="scope-bar">
          <span className="scope-label">{t("records.selectPatient")}</span>
          <PatientPicker value={patient} onChange={setPatient} />
          {patient ? (
            <span className="muted mono">
              {patient.id.slice(0, 8)} · {humanize(patient.locale)}
            </span>
          ) : null}
        </section>
      ) : (
        <section className="scope-bar">
          <span className="scope-label">{t("common.patient")}</span>
          <Badge tone="violet">{t("patients.linked")}</Badge>
          <span className="muted">{t("settings.noPhi")}</span>
        </section>
      )}

      {uploadNotice ? (
        <Callout tone="success" title={t("common.saved")}>
          {uploadNotice}
        </Callout>
      ) : null}

      {!hasScope ? (
        <EmptyState
          title={t("records.noPatient")}
          hint={t("records.selectPatient")}
          icon={<FileText size={22} aria-hidden="true" />}
        />
      ) : (
        <>
          <Tabs
            items={[
              { id: "documents", label: t("records.documents") },
              { id: "search", label: `${t("records.search")} / ${t("records.ask")}` },
              { id: "medications", label: t("records.medications") },
            ]}
            active={tab}
            onChange={setTab}
          />

          {tab === "documents" ? (
            <>
              {actionError ? <Callout tone="danger" title={t("common.errorTitle")}>{actionError}</Callout> : null}
              <DataGrid
                columns={documentColumns}
                items={documentsQuery.data?.items}
                meta={documentsQuery.data?.meta}
                loading={documentsQuery.isFetching}
                error={documentsQuery.error}
                grid={documentsGrid}
                rowKey={(row) => row.id}
                onRetry={() => void documentsQuery.refetch()}
                onRowClick={(row) => openDocument(row.id)}
                searchPlaceholder={t("common.searchPlaceholder")}
                filters={
                  <>
                    <select
                      value={statusFilter}
                      onChange={(event) => {
                        setStatusFilter(event.target.value);
                        documentsGrid.setPage(1);
                      }}
                      aria-label={t("records.documentStatus")}
                    >
                      <option value="">{t("common.all")}</option>
                      {DOC_STATUSES.map((status) => (
                        <option key={status} value={status}>
                          {humanize(status)}
                        </option>
                      ))}
                    </select>
                    <select
                      value={kindFilter}
                      onChange={(event) => {
                        setKindFilter(event.target.value);
                        documentsGrid.setPage(1);
                      }}
                      aria-label={t("records.kind")}
                    >
                      <option value="">{t("common.all")}</option>
                      {KINDS.map((item) => (
                        <option key={item} value={item}>
                          {humanize(item)}
                        </option>
                      ))}
                    </select>
                  </>
                }
                emptyTitle={t("common.emptyTitle")}
              />
            </>
          ) : null}

          {tab === "search" ? (
            <section className="panel">
              <div className="search-ask-controls">
                <div className="segmented" role="group" aria-label={t("records.mode")}>
                  <button
                    type="button"
                    className={mode === "ask" ? "is-active" : ""}
                    onClick={() => setMode("ask")}
                  >
                    <Sparkles size={15} aria-hidden="true" /> {t("records.ask")}
                  </button>
                  <button
                    type="button"
                    className={mode === "search" ? "is-active" : ""}
                    onClick={() => setMode("search")}
                  >
                    <Search size={15} aria-hidden="true" /> {t("records.search")}
                  </button>
                </div>
                <div className="search-ask-form">
                  <div className="search-box">
                    <Search size={16} aria-hidden="true" />
                    <input
                      type="search"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") submitQuestion();
                      }}
                      placeholder={t("records.searchPlaceholder")}
                      aria-label={t("records.searchPlaceholder")}
                      maxLength={500}
                    />
                  </div>
                  <label className="inline-field">
                    <span>{t("appointments.duration")}</span>
                    <select
                      value={topK}
                      onChange={(event) => setTopK(Number(event.target.value))}
                      aria-label={t("records.evidence")}
                    >
                      {[3, 5, 6, 8, 12].map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={askMutation.isPending || query.trim().length < 2}
                    onClick={submitQuestion}
                  >
                    {askMutation.isPending ? <Spinner /> : <Sparkles size={16} aria-hidden="true" />}
                    {phaseLabel}
                  </button>
                  {nursingEnabled && patientId ? (
                    <button
                      type="button"
                      className="btn btn-secondary"
                      data-testid="nursing-summary"
                      disabled={askMutation.isPending}
                      onClick={() => {
                        setNursingSummary(null);
                        void api<{ id: string; summary: string; status: string }>(
                          "/api/v1/nursing/summary",
                          {
                            method: "POST",
                            body: {
                              patient_id: patientId,
                              query: query.trim() || "Shift handover summary",
                            },
                          },
                        )
                          .then((res) =>
                            setNursingSummary({
                              id: res.id,
                              summary: res.summary,
                              status: res.status,
                            }),
                          )
                          .catch((error) => setResultError(errorMessage(error)));
                      }}
                    >
                      Nursing summary
                    </button>
                  ) : null}
                </div>
              </div>

              <Callout tone="info">{t("settings.noPhi")}</Callout>
              {nursingSummary ? (
                <article className="answer-card" data-testid="nursing-summary-result">
                  <header className="answer-head">
                    <Badge tone="info">Nursing {nursingSummary.status} (X-01)</Badge>
                  </header>
                  <p className="answer-text">{nursingSummary.summary}</p>
                  {nursingSummary.status === "draft" ? (
                    <div className="btn-row" role="group" aria-label="Nursing summary decision">
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => {
                          void api(`/api/v1/nursing/summaries/${nursingSummary.id}/decision`, {
                            method: "POST",
                            body: { decision: "accept" },
                          })
                            .then(() =>
                              setNursingSummary({ ...nursingSummary, status: "accepted" }),
                            )
                            .catch((error) => setResultError(errorMessage(error)));
                        }}
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger"
                        onClick={() => {
                          void api(`/api/v1/nursing/summaries/${nursingSummary.id}/decision`, {
                            method: "POST",
                            body: { decision: "reject", note: "clinician_rejected" },
                          })
                            .then(() =>
                              setNursingSummary({ ...nursingSummary, status: "rejected" }),
                            )
                            .catch((error) => setResultError(errorMessage(error)));
                        }}
                      >
                        Reject
                      </button>
                    </div>
                  ) : null}
                </article>
              ) : null}
              {resultError ? <Callout tone="danger" title={t("common.errorTitle")}>{resultError}</Callout> : null}

              {result?.mode === "ask" ? (
                <article className="answer-card">
                  <header className="answer-head">
                    <Badge tone="violet">
                      <Sparkles size={12} aria-hidden="true" /> {t("records.answer")}
                    </Badge>
                    <StatusBadge status={result.data.status} />
                    <span className="muted">
                      {t("records.evidence", { count: result.data.evidence_count })}
                    </span>
                  </header>
                  <p className="answer-text">{result.data.answer}</p>
                  {result.data.note ? <p className="muted">{result.data.note}</p> : null}
                  {result.data.status === "no_evidence" ? (
                    <Callout tone="warning">{t("records.noEvidence")}</Callout>
                  ) : null}
                  {result.data.status === "model_unavailable" ? (
                    <Callout tone="warning">{t("records.modelUnavailable")}</Callout>
                  ) : null}
                  <h3 className="section-title">{t("common.sources")}</h3>
                  <SourceList sources={result.data.sources} />
                </article>
              ) : null}

              {result?.mode === "search" ? (
                <div className="search-results">
                  <h3 className="section-title">
                    {t("records.searchResults")} · {result.data.evidence_count}
                  </h3>
                  {result.data.results.length === 0 ? (
                    <EmptyState title={t("records.noEvidence")} />
                  ) : (
                    result.data.results.map((hit) => (
                      <article key={hit.chunk_id} className="search-hit">
                        <header>
                          <button
                            type="button"
                            className="link-button"
                            onClick={() => openDocument(hit.document_id)}
                          >
                            {hit.document_title}
                          </button>
                          <span className="muted">
                            #{hit.chunk_index}
                            {hit.page ? ` · ${t("records.pages")} ${hit.page}` : ""}
                          </span>
                          <Badge tone="info">{hit.score.toFixed(3)}</Badge>
                        </header>
                        <p>{hit.snippet}</p>
                        <SourceList sources={[hit.source]} compact />
                      </article>
                    ))
                  )}
                </div>
              ) : null}
            </section>
          ) : null}

          {tab === "medications" ? (
            <DataGrid
              columns={medicationColumns}
              items={medicationsQuery.data?.items}
              meta={medicationsQuery.data?.meta}
              loading={medicationsQuery.isFetching}
              error={medicationsQuery.error}
              grid={medicationsGrid}
              rowKey={(row) => row.id}
              onRetry={() => void medicationsQuery.refetch()}
              searchPlaceholder={t("common.searchPlaceholder")}
              emptyTitle={t("common.emptyTitle")}
            />
          ) : null}
        </>
      )}

      <Modal
        open={Boolean(detailId)}
        title={detailQuery.data?.title ?? t("records.viewDocument")}
        description={
          detailQuery.data
            ? `${detailQuery.data.kind} · ${formatBytes(detailQuery.data.size_bytes)} · ${formatDateTime(detailQuery.data.created_at, locale)}`
            : undefined
        }
        onClose={() => setDetailId(null)}
        size="lg"
        footer={
          <>
            <button
              type="button"
              className="btn"
              disabled={!detailId || downloadMutation.isPending}
              onClick={() => detailId && downloadMutation.mutate(detailId)}
            >
              <Download size={15} aria-hidden="true" /> {t("records.download")}
            </button>
            {detailQuery.data?.status === "failed" ? (
              <button
                type="button"
                className="btn btn-primary"
                disabled={retryMutation.isPending}
                onClick={() => detailId && retryMutation.mutate(detailId)}
              >
                <RefreshCw size={15} aria-hidden="true" /> {t("records.retryIngest")}
              </button>
            ) : null}
          </>
        }
      >
        {detailQuery.isPending ? (
          <Spinner />
        ) : detailQuery.isError ? (
          <FormError message={errorMessage(detailQuery.error)} />
        ) : detailQuery.data ? (
          <div className="stack">
            <div className="detail-row">
              <StatusBadge status={detailQuery.data.status} />
              {detailQuery.data.error_code ? (
                <code className="mono danger-text">{detailQuery.data.error_code}</code>
              ) : null}
              <span className="muted">
                {t("records.pages")}: {detailQuery.data.page_count ?? "—"}
              </span>
              <Badge tone="neutral">{humanize(detailQuery.data.language)}</Badge>
            </div>
            {actionError ? <FormError message={actionError} /> : null}
            <h3 className="section-title">{t("records.chunks")}</h3>
            {chunksQuery.isError ? (
              <FormError message={errorMessage(chunksQuery.error)} />
            ) : !chunksQuery.data?.items.length ? (
              <p className="muted">{t("common.emptyTitle")}</p>
            ) : (
              <>
                <ol className="chunk-list">
                  {chunksQuery.data.items.map((chunk) => (
                    <li key={chunk.id} className="chunk">
                      <header>
                        <span className="muted">
                          #{chunk.chunk_index}
                          {chunk.page ? ` · ${t("records.pages")} ${chunk.page}` : ""}
                        </span>
                        {chunk.section ? <Badge tone="neutral">{chunk.section}</Badge> : null}
                      </header>
                      <p>{chunk.content}</p>
                    </li>
                  ))}
                </ol>
                <div className="mini-pager">
                  <IconButton
                    label={t("common.previous")}
                    icon={<ArrowLeft size={15} />}
                    disabled={chunkPage <= 1}
                    onClick={() => setChunkPage((current) => Math.max(1, current - 1))}
                  />
                  <span className="muted">
                    {t("common.page")} {chunkPage} {t("common.of")}{" "}
                    {Math.max(chunksQuery.data.meta.pages, 1)}
                  </span>
                  <IconButton
                    label={t("common.next")}
                    icon={<ArrowRight size={15} />}
                    disabled={chunkPage >= chunksQuery.data.meta.pages}
                    onClick={() => setChunkPage((current) => current + 1)}
                  />
                </div>
              </>
            )}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={uploadOpen}
        title={t("records.upload")}
        onClose={() => setUploadOpen(false)}
        busy={uploadMutation.isPending}
        footer={
          <>
            <button
              type="button"
              className="btn"
              onClick={() => setUploadOpen(false)}
              disabled={uploadMutation.isPending}
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={submitUpload}
              disabled={uploadMutation.isPending}
            >
              {uploadMutation.isPending ? <Spinner /> : <Upload size={16} aria-hidden="true" />}
              {t("records.upload")}
            </button>
          </>
        }
      >
        <div className="stack">
          <Field label={t("records.file")} required>
            <input
              type="file"
              accept=".pdf,image/png,image/jpeg,image/webp"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </Field>
          <Field label={t("records.uploadTitle")} required>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={200}
              placeholder={t("records.uploadTitle")}
            />
          </Field>
          <div className="field-row">
            <Field label={t("records.kind")}>
              <select value={kind} onChange={(event) => setKind(event.target.value)}>
                {KINDS.map((item) => (
                  <option key={item} value={item}>
                    {humanize(item)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("common.language")}>
              <select value={language} onChange={(event) => setLanguage(event.target.value)}>
                {LANGUAGES.map((item) => (
                  <option key={item} value={item}>
                    {humanize(item)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Callout tone="info">{t("settings.noPhi")}</Callout>
          <FormError message={uploadError} />
        </div>
      </Modal>
    </>
  );
}
