import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ExternalLink,
  LineChart,
  MessageSquare,
  Radio,
  Search,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge, StatusBadge } from "../components/Badge";
import { Callout, Field, FormError, PageHeader, Spinner, Stat, Tabs } from "../components/primitives";
import { api, errorMessage, qs } from "../lib/api";
import { formatCurrency, formatDateTime, formatNumber, humanize, truncate } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { AuditChainStatus } from "../lib/types";

interface OpsLinks {
  langfuse: {
    url: string | null;
    configured: boolean;
    capture_content: boolean;
  };
  grafana: { url: string | null; embed: boolean; embed_url: string | null };
  prometheus: { url: string | null };
  mailpit: { url: string | null };
  note: string;
}

interface OpsSnapshot {
  period: { days: number };
  links: OpsLinks;
  traffic: { chat_sessions: number; chat_runs: number; chat_runs_failed: number };
  finops: {
    calls: number;
    cost_usd: number;
    prompt_tokens: number;
    completion_tokens: number;
    monthly_run_rate_usd: number;
    reconciliation_status: string | null;
    reconciliation_variance_pct: number | null;
  };
  handoffs: {
    open: number;
    overdue: number;
    mtta: {
      acknowledged_count: number;
      mean_seconds: number | null;
      p50_seconds: number | null;
      within_sla_ratio: number | null;
      sla_seconds_emergency: number;
    };
  };
  jobs: {
    job_name: string;
    status: string;
    started_at: string | null;
    finished_at: string | null;
    error_code: string | null;
  }[];
  as_of: string;
}

interface SessionRow {
  id: string;
  title: string;
  owner_subject: string;
  owner_role: string;
  patient_id: string | null;
  status: string;
  locale: string;
  traffic_class: string;
  message_count: number;
  run_count: number;
  latest_trace_id: string | null;
  created_at: string;
  updated_at: string;
}

interface RunRow {
  id: string;
  session_id: string;
  owner_subject: string;
  graph: string;
  status: string;
  error_code: string | null;
  trace_id: string | null;
  trace_url: string | null;
  started_at: string | null;
  duration_ms: number | null;
}

interface SessionDetail {
  session: SessionRow & { locale: string };
  usage: { cost_usd: number; prompt_tokens: number; completion_tokens: number; calls: number };
  messages: {
    id: string;
    role: string;
    language: string;
    model_alias: string | null;
    trace_id: string | null;
    trace_url: string | null;
    safety: Record<string, unknown>;
    source_count: number;
    content: string | null;
    content_chars: number;
    created_at: string;
  }[];
  runs: RunRow[];
  privacy_note: string;
  include_content: boolean;
}

function ExternalChip({ href, label }: { href: string | null | undefined; label: string }) {
  if (!href) {
    return (
      <span className="chip muted" title="Not configured">
        {label}
      </span>
    );
  }
  return (
    <a className="chip chip-link" href={href} target="_blank" rel="noreferrer">
      {label} <ExternalLink size={12} aria-hidden="true" />
    </a>
  );
}

export function OpsPage() {
  const { t, locale } = useI18n();
  const [tab, setTab] = useState("overview");
  const [days, setDays] = useState(7);
  const [sessionQ, setSessionQ] = useState("");
  const [runQ, setRunQ] = useState("");
  const [runStatus, setRunStatus] = useState("");
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [showGrafana, setShowGrafana] = useState(true);

  const snapshotQuery = useQuery({
    queryKey: ["ops", "snapshot", days],
    queryFn: () => api<OpsSnapshot>(`/api/v1/admin/observability/snapshot${qs({ days })}`),
    enabled: tab === "overview" || tab === "grafana",
    refetchInterval: 60_000,
  });

  const chainQuery = useQuery({
    queryKey: ["ops", "audit-chain"],
    queryFn: () => api<AuditChainStatus>("/api/v1/admin/audit/chain"),
    enabled: tab === "overview",
    refetchInterval: 60_000,
  });

  const sessionsQuery = useQuery({
    queryKey: ["ops", "sessions", sessionQ],
    queryFn: () =>
      api<{ items: SessionRow[] }>(
        `/api/v1/admin/observability/sessions${qs({ q: sessionQ || undefined, page_size: 30 })}`,
      ),
    enabled: tab === "conversations",
  });

  const runsQuery = useQuery({
    queryKey: ["ops", "runs", runQ, runStatus],
    queryFn: () =>
      api<{ items: RunRow[]; links: OpsLinks }>(
        `/api/v1/admin/observability/runs${qs({
          q: runQ || undefined,
          status: runStatus || undefined,
          page_size: 40,
        })}`,
      ),
    enabled: tab === "runs",
  });

  const detailQuery = useQuery({
    queryKey: ["ops", "session", selectedSessionId],
    queryFn: () =>
      api<SessionDetail>(
        `/api/v1/admin/observability/sessions/${selectedSessionId}${qs({ include_content: true })}`,
      ),
    enabled: Boolean(selectedSessionId),
  });

  const links = snapshotQuery.data?.links ?? runsQuery.data?.links;
  const grafanaEmbed = links?.grafana.embed_url;

  const tabs = useMemo(
    () => [
      { id: "overview", label: t("ops.tabOverview") },
      { id: "conversations", label: t("ops.tabConversations") },
      { id: "runs", label: t("ops.tabRuns") },
      { id: "grafana", label: t("ops.tabGrafana") },
    ],
    [t],
  );

  return (
    <div className="page">
      <PageHeader
        title={t("ops.title")}
        subtitle={t("ops.subtitle")}
        actions={
          <label className="inline-field">
            <span>{t("analytics.period")}</span>
            <select
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
              aria-label={t("analytics.period")}
            >
              {[1, 7, 30].map((value) => (
                <option key={value} value={value}>
                  {t("analytics.days", { days: value })}
                </option>
              ))}
            </select>
          </label>
        }
      />

      <div className="filter-row" style={{ marginBottom: 12 }}>
        <ExternalChip href={links?.langfuse.url} label="Langfuse" />
        <ExternalChip href={links?.grafana.url} label="Grafana" />
        <ExternalChip href={links?.prometheus.url} label="Prometheus" />
        <ExternalChip href={links?.mailpit.url} label="Mailpit" />
      </div>

      <Tabs items={tabs} active={tab} onChange={setTab} />

      {tab === "overview" ? (
        <section className="panel stack">
          {snapshotQuery.isPending ? (
            <Spinner />
          ) : snapshotQuery.isError ? (
            <FormError message={errorMessage(snapshotQuery.error)} />
          ) : snapshotQuery.data ? (
            <>
              <Callout tone="info">{snapshotQuery.data.links.note}</Callout>
              <div className="stat-grid">
                <Stat
                  label={t("ops.sessions")}
                  value={formatNumber(snapshotQuery.data.traffic.chat_sessions, locale)}
                  hint={t("ops.lastDays", { days })}
                />
                <Stat
                  label={t("ops.runs")}
                  value={formatNumber(snapshotQuery.data.traffic.chat_runs, locale)}
                  hint={`${formatNumber(snapshotQuery.data.traffic.chat_runs_failed, locale)} failed`}
                />
                <Stat
                  label={t("ops.finopsCost")}
                  value={formatCurrency(snapshotQuery.data.finops.cost_usd, "USD", locale)}
                  hint={formatCurrency(snapshotQuery.data.finops.monthly_run_rate_usd, "USD", locale)}
                />
                <Stat
                  label={t("ops.handoffs")}
                  value={formatNumber(snapshotQuery.data.handoffs.open, locale)}
                  hint={`${formatNumber(snapshotQuery.data.handoffs.overdue, locale)} overdue`}
                />
                <Stat
                  label={t("ops.mtta")}
                  value={
                    snapshotQuery.data.handoffs.mtta.p50_seconds != null
                      ? `${formatNumber(snapshotQuery.data.handoffs.mtta.p50_seconds, locale)}s`
                      : "—"
                  }
                  hint={
                    snapshotQuery.data.handoffs.mtta.within_sla_ratio != null
                      ? `${Math.round(snapshotQuery.data.handoffs.mtta.within_sla_ratio * 100)}% within SLA`
                      : t("ops.mttaEmpty")
                  }
                />
                <Stat
                  label={t("ops.recon")}
                  value={snapshotQuery.data.finops.reconciliation_status ?? "—"}
                  hint={
                    snapshotQuery.data.finops.reconciliation_variance_pct != null
                      ? `${snapshotQuery.data.finops.reconciliation_variance_pct}% var`
                      : undefined
                  }
                />
                <Stat
                  label={t("ops.auditChain")}
                  value={
                    chainQuery.isLoading
                      ? "…"
                      : chainQuery.data?.status
                        ? humanize(chainQuery.data.status)
                        : "—"
                  }
                  hint={
                    chainQuery.data?.detail?.checked != null
                      ? t("ops.auditChainHint", { n: chainQuery.data.detail.checked })
                      : t("ops.auditChainNever")
                  }
                />
              </div>

              <div className="split-grid">
                <div>
                  <h3 className="section-title">{t("ops.recentJobs")}</h3>
                  {snapshotQuery.data.jobs.length === 0 ? (
                    <p className="muted">{t("ops.noJobs")}</p>
                  ) : (
                    <div className="table-wrap">
                      <table className="data-table compact">
                        <thead>
                          <tr>
                            <th>{t("ops.job")}</th>
                            <th>{t("common.status")}</th>
                            <th>{t("common.date")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {snapshotQuery.data.jobs.map((job) => (
                            <tr key={`${job.job_name}-${job.started_at}`}>
                              <td>
                                <code className="mono">{job.job_name}</code>
                                {job.error_code ? (
                                  <div className="muted small">{job.error_code}</div>
                                ) : null}
                              </td>
                              <td>
                                <StatusBadge status={job.status} />
                              </td>
                              <td className="muted small">
                                {job.started_at ? formatDateTime(job.started_at, locale) : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
                <div className="callout-stack">
                  <Callout tone="warning" title={t("ops.howToDebug")}>
                    {t("ops.howToDebugBody")}
                  </Callout>
                  <p className="muted small">
                    {t("analytics.asOf")}: {formatDateTime(snapshotQuery.data.as_of, locale)}
                  </p>
                </div>
              </div>
            </>
          ) : null}
        </section>
      ) : null}

      {tab === "conversations" ? (
        <div className="split-grid">
          <section className="panel stack">
            <Field label={t("ops.searchSessions")}>
              <div className="inline-field">
                <Search size={16} aria-hidden="true" />
                <input
                  value={sessionQ}
                  onChange={(event) => setSessionQ(event.target.value)}
                  placeholder={t("ops.searchSessionsHint")}
                />
              </div>
            </Field>
            {sessionsQuery.isPending ? (
              <Spinner />
            ) : sessionsQuery.isError ? (
              <FormError message={errorMessage(sessionsQuery.error)} />
            ) : (
              <ul className="mini-list">
                {(sessionsQuery.data?.items ?? []).map((row) => (
                  <li key={row.id}>
                    <button
                      type="button"
                      className={`mini-row linkish ${selectedSessionId === row.id ? "is-active" : ""}`}
                      onClick={() => setSelectedSessionId(row.id)}
                    >
                      <span className="mini-when">
                        <MessageSquare size={14} aria-hidden="true" /> {row.message_count} ·{" "}
                        {row.run_count} runs
                      </span>
                      <strong>{row.title || truncate(row.id, 8)}</strong>
                      <span className="muted small">
                        {row.owner_subject} · {row.owner_role} · {row.traffic_class}
                      </span>
                      <span className="muted small">{formatDateTime(row.updated_at, locale)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel stack">
            {!selectedSessionId ? (
              <Callout tone="info">{t("ops.selectSession")}</Callout>
            ) : detailQuery.isPending ? (
              <Spinner />
            ) : detailQuery.isError ? (
              <FormError message={errorMessage(detailQuery.error)} />
            ) : detailQuery.data ? (
              <>
                <div className="section-head">
                  <h2>{detailQuery.data.session.title}</h2>
                  <Badge tone="neutral">{detailQuery.data.session.status}</Badge>
                </div>
                <p className="muted small">
                  {detailQuery.data.session.owner_subject} · {detailQuery.data.session.id}
                </p>
                <div className="stat-grid">
                  <Stat
                    label={t("analytics.cost")}
                    value={formatCurrency(detailQuery.data.usage.cost_usd, "USD", locale)}
                  />
                  <Stat
                    label={t("analytics.tokens")}
                    value={formatNumber(
                      detailQuery.data.usage.prompt_tokens +
                        detailQuery.data.usage.completion_tokens,
                      locale,
                    )}
                  />
                  <Stat
                    label={t("ops.messages")}
                    value={formatNumber(detailQuery.data.messages.length, locale)}
                  />
                </div>
                <Callout tone="warning">{detailQuery.data.privacy_note}</Callout>
                <h3 className="section-title">{t("ops.messages")}</h3>
                <div className="stack">
                  {detailQuery.data.messages.map((msg) => (
                    <article key={msg.id} className="panel nested">
                      <div className="detail-row">
                        <Badge tone={msg.role === "user" ? "info" : "neutral"}>{msg.role}</Badge>
                        {msg.model_alias ? <span className="muted small">{msg.model_alias}</span> : null}
                        <span className="muted small">{formatDateTime(msg.created_at, locale)}</span>
                        {msg.trace_url ? (
                          <a href={msg.trace_url} target="_blank" rel="noreferrer" className="link">
                            Langfuse <ExternalLink size={12} aria-hidden="true" />
                          </a>
                        ) : null}
                      </div>
                      <pre className="ops-message-body">{msg.content ?? `[${msg.content_chars} chars hidden]`}</pre>
                      {msg.source_count ? (
                        <span className="muted small">{msg.source_count} sources</span>
                      ) : null}
                    </article>
                  ))}
                </div>
                <h3 className="section-title">{t("ops.tabRuns")}</h3>
                <div className="table-wrap">
                  <table className="data-table compact">
                    <thead>
                      <tr>
                        <th>Graph</th>
                        <th>{t("common.status")}</th>
                        <th>ms</th>
                        <th>Trace</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detailQuery.data.runs.map((run) => (
                        <tr key={run.id}>
                          <td>
                            <code className="mono">{run.graph}</code>
                          </td>
                          <td>
                            <StatusBadge status={run.status} />
                            {run.error_code ? (
                              <div className="muted small">{run.error_code}</div>
                            ) : null}
                          </td>
                          <td>{run.duration_ms ?? "—"}</td>
                          <td>
                            {run.trace_url ? (
                              <a href={run.trace_url} target="_blank" rel="noreferrer" className="link">
                                open
                              </a>
                            ) : (
                              "—"
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : null}
          </section>
        </div>
      ) : null}

      {tab === "runs" ? (
        <section className="panel stack">
          <div className="filter-row">
            <Field label={t("ops.searchRuns")}>
              <input
                value={runQ}
                onChange={(event) => setRunQ(event.target.value)}
                placeholder={t("ops.searchRunsHint")}
              />
            </Field>
            <Field label={t("common.status")}>
              <select value={runStatus} onChange={(event) => setRunStatus(event.target.value)}>
                <option value="">{t("common.all")}</option>
                {["running", "interrupted", "completed", "failed", "cancelled"].map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {runsQuery.isPending ? (
            <Spinner />
          ) : runsQuery.isError ? (
            <FormError message={errorMessage(runsQuery.error)} />
          ) : (
            <div className="table-wrap">
              <table className="data-table compact">
                <thead>
                  <tr>
                    <th>Graph</th>
                    <th>Owner</th>
                    <th>{t("common.status")}</th>
                    <th>ms</th>
                    <th>{t("common.date")}</th>
                    <th>Trace</th>
                    <th>Session</th>
                  </tr>
                </thead>
                <tbody>
                  {(runsQuery.data?.items ?? []).map((run) => (
                    <tr key={run.id}>
                      <td>
                        <code className="mono">{run.graph}</code>
                      </td>
                      <td className="muted small">{run.owner_subject}</td>
                      <td>
                        <StatusBadge status={run.status} />
                      </td>
                      <td>{run.duration_ms ?? "—"}</td>
                      <td className="muted small">
                        {run.started_at ? formatDateTime(run.started_at, locale) : "—"}
                      </td>
                      <td>
                        {run.trace_url ? (
                          <a href={run.trace_url} target="_blank" rel="noreferrer" className="link">
                            Langfuse
                          </a>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="link"
                          onClick={() => {
                            setSelectedSessionId(run.session_id);
                            setTab("conversations");
                          }}
                        >
                          {truncate(run.session_id, 8)}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {tab === "grafana" ? (
        <section className="panel stack">
          <Callout tone="info" title={t("ops.grafanaTitle")}>
            {t("ops.grafanaBody")}
          </Callout>
          <div className="filter-row">
            <ExternalChip href={links?.grafana.url ?? undefined} label={t("ops.openGrafana")} />
            <label className="filter-field checkbox-inline">
              <input
                type="checkbox"
                checked={showGrafana}
                onChange={(event) => setShowGrafana(event.target.checked)}
              />
              <span>{t("ops.embedGrafana")}</span>
            </label>
          </div>
          {showGrafana && grafanaEmbed ? (
            <iframe
              title="Grafana"
              src={grafanaEmbed}
              className="ops-embed"
              referrerPolicy="no-referrer"
            />
          ) : (
            <Callout tone="warning">
              {grafanaEmbed ? t("ops.embedOff") : t("ops.grafanaUnavailable")}
            </Callout>
          )}
          <div className="detail-row">
            <Activity size={16} aria-hidden="true" />
            <Radio size={16} aria-hidden="true" />
            <LineChart size={16} aria-hidden="true" />
            <span className="muted small">{t("ops.grafanaHint")}</span>
          </div>
        </section>
      ) : null}
    </div>
  );
}
