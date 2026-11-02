import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Calculator,
  Info,
  LineChart,
  Lock,
  Sparkles,
} from "lucide-react";
import { useState } from "react";

import { Badge, StatusBadge } from "../components/Badge";
import { MetricTiles } from "../components/MetricTiles";
import {
  Callout,
  Field,
  FormError,
  PageHeader,
  Spinner,
  Stat,
  Tabs,
} from "../components/primitives";
import { api, errorMessage, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import {
  formatCurrency,
  formatDateTime,
  formatNumber,
  humanize,
} from "../lib/format";
import { useI18n } from "../lib/i18n";
import type {
  EvaluationsResponse,
  FinOpsResponse,
  InsightResponse,
  MetricTile,
  OverviewResponse,
  WhatIfResponse,
} from "../lib/types";

interface QualityResponse {
  period: { days: number; start: string; end: string };
  tiles: MetricTile[];
  zero_tolerance_note: string;
}

interface ComplianceResponse {
  tiles: MetricTile[];
  as_of: string;
  latest_audit_event_at: string | null;
}

interface WhatIfForm {
  profile: "P" | "S" | "M" | "L";
  hosting: "laptop" | "colo" | "on_prem" | "india_cloud" | "hybrid";
  horizonMonths: number;
  registeredUsers: number;
  monthlyActiveUsers: number;
  peakRequestsPerHour: number;
  documentsPerMonth: number;
  audioHoursPerMonth: number;
  chatTurnsPerDay: number;
  externalLlmShare: number;
  gpu: boolean;
  fxUsdInr: number;
  revenuePerActiveUser: number;
  pricePerChatTurn: number;
  smsPerMonth: number;
  emailsPerMonth: number;
}

const DEFAULT_FORM: WhatIfForm = {
  profile: "P",
  hosting: "laptop",
  horizonMonths: 36,
  registeredUsers: 1000,
  monthlyActiveUsers: 400,
  peakRequestsPerHour: 60,
  documentsPerMonth: 200,
  audioHoursPerMonth: 20,
  chatTurnsPerDay: 300,
  externalLlmShare: 0.2,
  gpu: false,
  fxUsdInr: 83,
  revenuePerActiveUser: 0,
  pricePerChatTurn: 0,
  smsPerMonth: 0,
  emailsPerMonth: 0,
};

export function AnalyticsPage() {
  const { t, locale } = useI18n();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");
  const [tab, setTab] = useState("overview");
  const [days, setDays] = useState(30);
  const [form, setForm] = useState<WhatIfForm>(DEFAULT_FORM);
  const [whatIfResult, setWhatIfResult] = useState<WhatIfResponse | null>(null);
  const [whatIfError, setWhatIfError] = useState<string | null>(null);

  const overviewQuery = useQuery({
    queryKey: ["analytics", "overview", days],
    queryFn: () => api<OverviewResponse>(`/api/v1/analytics/overview${qs({ days })}`),
    enabled: tab === "overview",
  });

  const qualityQuery = useQuery({
    queryKey: ["analytics", "quality", days],
    queryFn: () => api<QualityResponse>(`/api/v1/analytics/quality${qs({ days })}`),
    enabled: tab === "quality",
  });

  const complianceQuery = useQuery({
    queryKey: ["analytics", "compliance"],
    queryFn: () => api<ComplianceResponse>("/api/v1/analytics/compliance"),
    enabled: tab === "compliance",
  });

  const evaluationsQuery = useQuery({
    queryKey: ["analytics", "evaluations"],
    queryFn: () => api<EvaluationsResponse>("/api/v1/analytics/evaluations"),
    enabled: tab === "evaluations",
  });

  const finopsQuery = useQuery({
    queryKey: ["analytics", "finops", days],
    queryFn: () => api<FinOpsResponse>(`/api/v1/analytics/finops${qs({ days })}`),
    enabled: tab === "finops" && isAdmin,
  });

  const insightsQuery = useQuery({
    queryKey: ["analytics", "insights", days],
    queryFn: () => api<InsightResponse>(`/api/v1/analytics/insights${qs({ days })}`),
    enabled: tab === "insights" && isAdmin,
  });

  const whatIfMutation = useMutation({
    mutationFn: (payload: WhatIfForm) =>
      api<WhatIfResponse>("/api/v1/analytics/finops/what-if", {
        method: "POST",
        body: {
          profile: payload.profile,
          hosting: payload.hosting,
          horizon_months: payload.horizonMonths,
          registered_users: payload.registeredUsers,
          monthly_active_users: payload.monthlyActiveUsers,
          peak_requests_per_hour: payload.peakRequestsPerHour,
          documents_per_month: payload.documentsPerMonth,
          audio_hours_per_month: payload.audioHoursPerMonth,
          chat_turns_per_day: payload.chatTurnsPerDay,
          external_llm_share: payload.externalLlmShare,
          gpu: payload.gpu,
          fx_usd_inr: payload.fxUsdInr,
          revenue_per_active_user_inr_month: payload.revenuePerActiveUser,
          price_per_chat_turn_inr: payload.pricePerChatTurn,
          sms_per_month: payload.smsPerMonth,
          emails_per_month: payload.emailsPerMonth,
        },
      }),
    onSuccess: (data) => {
      setWhatIfResult(data);
      setWhatIfError(null);
    },
    onError: (error) => {
      setWhatIfResult(null);
      setWhatIfError(errorMessage(error));
    },
  });

  const update = <K extends keyof WhatIfForm>(key: K, value: WhatIfForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const tabs = [
    { id: "overview", label: t("analytics.overview") },
    { id: "quality", label: t("analytics.quality") },
    { id: "compliance", label: t("analytics.compliance") },
    { id: "evaluations", label: t("analytics.evaluations") },
    ...(isAdmin
      ? [
          { id: "finops", label: t("analytics.finops") },
          { id: "insights", label: t("analytics.insights") },
        ]
      : []),
  ];

  const periodSelect = (
    <label className="inline-field">
      <span>{t("analytics.period")}</span>
      <select
        value={days}
        onChange={(event) => setDays(Number(event.target.value))}
        aria-label={t("analytics.period")}
      >
        {[7, 30, 90, 365].map((value) => (
          <option key={value} value={value}>
            {t("analytics.days", { days: value })}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <>
      <PageHeader
        title={t("analytics.title")}
        subtitle={t("analytics.subtitle")}
        actions={["overview", "quality", "finops", "insights"].includes(tab) ? periodSelect : null}
      />
      <Tabs items={tabs} active={tab} onChange={setTab} />

      {tab === "overview" ? (
        <section className="panel">
          {overviewQuery.isPending ? (
            <Spinner />
          ) : overviewQuery.isError ? (
            <FormError message={errorMessage(overviewQuery.error)} />
          ) : overviewQuery.data ? (
            <div className="stack">
              <MetricTiles tiles={overviewQuery.data.tiles} />
              <div className="split-grid">
                <div>
                  <h3 className="section-title">{t("analytics.activeByRole")}</h3>
                  <ul className="bar-list">
                    {overviewQuery.data.active_users_by_role.map((row) => {
                      const max = Math.max(
                        ...overviewQuery.data.active_users_by_role.map((item) => item.count ?? 0),
                        1,
                      );
                      return (
                        <li key={row.role ?? "unknown"}>
                          <span className="bar-label">{humanize(row.role)}</span>
                          <span className="bar-track">
                            <span
                              className="bar-fill"
                              style={{ width: `${((row.count ?? 0) / max) * 100}%` }}
                            />
                          </span>
                          <span className="bar-value">{formatNumber(row.count ?? 0, locale)}</span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
                <div className="callout-stack">
                  <Callout tone="info" title={t("dashboard.dataScope")}>
                    {t("dashboard.syntheticNote")} Traffic class:{" "}
                    <Badge tone="violet">{overviewQuery.data.traffic_class}</Badge>
                  </Callout>
                  <Callout tone="warning">{t("analytics.notConfigured")}</Callout>
                </div>
              </div>
              <p className="muted small">
                {t("analytics.asOf")}: {formatDateTime(overviewQuery.data.as_of, locale)}
              </p>
            </div>
          ) : null}
        </section>
      ) : null}

      {tab === "quality" ? (
        <section className="panel">
          {qualityQuery.isPending ? (
            <Spinner />
          ) : qualityQuery.isError ? (
            <FormError message={errorMessage(qualityQuery.error)} />
          ) : qualityQuery.data ? (
            <div className="stack">
              <Callout tone="warning">{qualityQuery.data.zero_tolerance_note}</Callout>
              <MetricTiles tiles={qualityQuery.data.tiles} />
            </div>
          ) : null}
        </section>
      ) : null}

      {tab === "compliance" ? (
        <section className="panel">
          {complianceQuery.isPending ? (
            <Spinner />
          ) : complianceQuery.isError ? (
            <FormError message={errorMessage(complianceQuery.error)} />
          ) : complianceQuery.data ? (
            <div className="stack">
              <MetricTiles tiles={complianceQuery.data.tiles} />
              <p className="muted small">
                {t("analytics.asOf")}: {formatDateTime(complianceQuery.data.as_of, locale)}
                {complianceQuery.data.latest_audit_event_at
                  ? ` · ${formatDateTime(complianceQuery.data.latest_audit_event_at, locale)}`
                  : ""}
              </p>
            </div>
          ) : null}
        </section>
      ) : null}

      {tab === "evaluations" ? (
        <section className="panel">
          {evaluationsQuery.isPending ? (
            <Spinner />
          ) : evaluationsQuery.isError ? (
            <FormError message={errorMessage(evaluationsQuery.error)} />
          ) : evaluationsQuery.data ? (
            <div className="stack">
              {evaluationsQuery.data.runs.length === 0 ? (
                <Callout tone="warning" title={t("analytics.evaluations")}>
                  {t("analytics.noRuns")}
                </Callout>
              ) : (
                <div className="table-wrap">
                  <table className="data-table compact">
                    <thead>
                      <tr>
                        <th>{t("analytics.suite")}</th>
                        <th>{t("analytics.framework")}</th>
                        <th>{t("common.status")}</th>
                        <th>{t("analytics.cases")}</th>
                        <th>{t("analytics.judgeAlias")}</th>
                        <th>{t("analytics.asOf")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {evaluationsQuery.data.runs.map((run) => (
                        <tr key={run.id}>
                          <td>{run.suite}</td>
                          <td>
                            {run.framework} {run.framework_version}
                          </td>
                          <td>
                            <StatusBadge status={run.status} />
                          </td>
                          <td>
                            {run.passed_cases}/{run.case_count}
                          </td>
                          <td>{run.judge_alias ?? "—"}</td>
                          <td>{formatDateTime(run.created_at, locale)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="split-grid">
                <Stat label={t("analytics.rag")} value={evaluationsQuery.data.frameworks.rag} />
                <Stat label={t("analytics.nonRag")} value={evaluationsQuery.data.frameworks.non_rag} />
                <Stat label={t("common.status")} value={<StatusBadge status={evaluationsQuery.data.status} />} />
              </div>
              <MetricTiles tiles={evaluationsQuery.data.metrics} />
            </div>
          ) : null}
        </section>
      ) : null}

      {tab === "finops" && isAdmin ? (
        <>
          <section className="panel">
            {finopsQuery.isPending ? (
              <Spinner />
            ) : finopsQuery.isError ? (
              <FormError message={errorMessage(finopsQuery.error)} />
            ) : finopsQuery.data ? (
              <div className="stack">
                <div className="stat-grid">
                  <Stat
                    label={t("analytics.calls")}
                    value={formatNumber(finopsQuery.data.observed.calls, locale)}
                  />
                  <Stat
                    label={t("analytics.tokens")}
                    value={formatNumber(
                      finopsQuery.data.observed.prompt_tokens +
                        finopsQuery.data.observed.completion_tokens,
                      locale,
                    )}
                    hint={`${formatNumber(finopsQuery.data.observed.prompt_tokens, locale)} / ${formatNumber(
                      finopsQuery.data.observed.completion_tokens,
                      locale,
                    )}`}
                  />
                  <Stat
                    label={t("analytics.cost")}
                    value={formatCurrency(finopsQuery.data.observed.cost_usd, "USD", locale)}
                  />
                  <Stat
                    label={t("analytics.runRate")}
                    value={formatCurrency(finopsQuery.data.monthly_run_rate_usd, "USD", locale)}
                  />
                </div>
                <div className="detail-row">
                  <StatusBadge status={finopsQuery.data.status} />
                  <Badge tone="violet">{finopsQuery.data.traffic_class}</Badge>
                  <span className="muted">
                    {t("analytics.priceBasis")}: {finopsQuery.data.price_basis_date} ·{" "}
                    {finopsQuery.data.price_version}
                  </span>
                  <span className="muted">
                    {t("analytics.fx")}: {finopsQuery.data.fx_usd_inr}
                  </span>
                </div>

                <h3 className="section-title">{t("analytics.byPurpose")}</h3>
                {finopsQuery.data.by_purpose.length === 0 ? (
                  <p className="muted">{t("analytics.noRuns")}</p>
                ) : (
                  <div className="table-wrap">
                    <table className="data-table compact">
                      <thead>
                        <tr>
                          <th>{t("common.details")}</th>
                          <th className="align-right">{t("analytics.calls")}</th>
                          <th className="align-right">{t("analytics.cost")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {finopsQuery.data.by_purpose.map((row) => (
                          <tr key={row.purpose}>
                            <td>{humanize(row.purpose)}</td>
                            <td className="align-right">{formatNumber(row.calls, locale)}</td>
                            <td className="align-right">
                              {formatCurrency(row.cost_usd, "USD", locale)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <h3 className="section-title">{t("analytics.budgets")}</h3>
                <div className="stat-grid">
                  {Object.entries(finopsQuery.data.budgets_usd).map(([key, value]) => (
                    <Stat
                      key={key}
                      label={humanize(key)}
                      value={formatCurrency(value, "USD", locale)}
                    />
                  ))}
                </div>

                <Callout
                  tone={finopsQuery.data.reconciliation.status === "unavailable" ? "warning" : "info"}
                  title={t("analytics.reconciliation")}
                >
                  {finopsQuery.data.reconciliation.note}
                </Callout>
              </div>
            ) : null}
          </section>

          <section className="panel">
            <div className="panel-head">
              <h3>
                <Calculator size={17} aria-hidden="true" /> {t("analytics.whatIf")}
              </h3>
              <span className="muted small">{t("analytics.whatIfNote")}</span>
            </div>
            <div className="whatif-form">
              <Field label={t("analytics.profile")}>
                <select
                  value={form.profile}
                  onChange={(event) => update("profile", event.target.value as WhatIfForm["profile"])}
                >
                  {(["P", "S", "M", "L"] as const).map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t("analytics.hosting")}>
                <select
                  value={form.hosting}
                  onChange={(event) =>
                    update("hosting", event.target.value as WhatIfForm["hosting"])
                  }
                >
                  {(["laptop", "colo", "on_prem", "india_cloud", "hybrid"] as const).map((value) => (
                    <option key={value} value={value}>
                      {humanize(value)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t("analytics.horizon")}>
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={form.horizonMonths}
                  onChange={(event) => update("horizonMonths", Number(event.target.value))}
                />
              </Field>
              <Field label={t("analytics.registeredUsers")}>
                <input
                  type="number"
                  min={1}
                  value={form.registeredUsers}
                  onChange={(event) => update("registeredUsers", Number(event.target.value))}
                />
              </Field>
              <Field label={t("analytics.mau")}>
                <input
                  type="number"
                  min={1}
                  value={form.monthlyActiveUsers}
                  onChange={(event) => update("monthlyActiveUsers", Number(event.target.value))}
                />
              </Field>
              <Field label={t("analytics.peakRph")}>
                <input
                  type="number"
                  min={1}
                  value={form.peakRequestsPerHour}
                  onChange={(event) => update("peakRequestsPerHour", Number(event.target.value))}
                />
              </Field>
              <Field label={t("analytics.documents")}>
                <input
                  type="number"
                  min={0}
                  value={form.documentsPerMonth}
                  onChange={(event) => update("documentsPerMonth", Number(event.target.value))}
                />
              </Field>
              <Field label={t("analytics.audioHours")}>
                <input
                  type="number"
                  min={0}
                  value={form.audioHoursPerMonth}
                  onChange={(event) => update("audioHoursPerMonth", Number(event.target.value))}
                />
              </Field>
              <Field label={t("analytics.chatTurns")}>
                <input
                  type="number"
                  min={0}
                  value={form.chatTurnsPerDay}
                  onChange={(event) => update("chatTurnsPerDay", Number(event.target.value))}
                />
              </Field>
              <Field label={t("analytics.externalShare")} hint="0 – 1">
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={form.externalLlmShare}
                  onChange={(event) => update("externalLlmShare", Number(event.target.value))}
                />
              </Field>
              <Field label={t("analytics.fx")}>
                <input
                  type="number"
                  min={1}
                  value={form.fxUsdInr}
                  onChange={(event) => update("fxUsdInr", Number(event.target.value))}
                />
              </Field>
              <Field label={t("analytics.revenue")}>
                <input
                  type="number"
                  min={0}
                  value={form.revenuePerActiveUser}
                  onChange={(event) => update("revenuePerActiveUser", Number(event.target.value))}
                />
              </Field>
              <Field label={t("analytics.gpu")}>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={form.gpu}
                    onChange={(event) => update("gpu", event.target.checked)}
                  />
                  <span>{t("analytics.gpu")}</span>
                </label>
              </Field>
              <div className="form-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={whatIfMutation.isPending}
                  onClick={() => whatIfMutation.mutate(form)}
                >
                  {whatIfMutation.isPending ? <Spinner /> : <LineChart size={15} aria-hidden="true" />}
                  {t("analytics.runWhatIf")}
                </button>
              </div>
            </div>
            <FormError message={whatIfError} />
            {whatIfResult ? (
              <div className="stack whatif-result">
                <div className="detail-row">
                  <Badge tone="warning">{whatIfResult.label}</Badge>
                  <span className="muted">{whatIfResult.model_version}</span>
                  <span className="muted">
                    {whatIfResult.profile} · {humanize(whatIfResult.hosting)} ·{" "}
                    {whatIfResult.horizon_months} mo
                  </span>
                </div>
                <div className="tri-grid">
                  <div>
                    <h4 className="section-title">{t("analytics.capex")}</h4>
                    <ul className="kv-list">
                      {Object.entries(whatIfResult.capex_inr_lakh).map(([key, value]) => (
                        <li key={key}>
                          <span>{humanize(key)}</span>
                          <strong>{formatNumber(value, locale)}</strong>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h4 className="section-title">{t("analytics.opex")}</h4>
                    <ul className="kv-list">
                      {Object.entries(whatIfResult.opex_inr_month).map(([key, value]) => (
                        <li key={key}>
                          <span>{humanize(key)}</span>
                          <strong>{formatNumber(value, locale)}</strong>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h4 className="section-title">{t("analytics.tco")}</h4>
                    <ul className="kv-list">
                      {Object.entries(whatIfResult.tco_inr_lakh).map(([key, value]) => (
                        <li key={key}>
                          <span>{humanize(key)}</span>
                          <strong>{formatNumber(value, locale)}</strong>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                <div className="stat-grid">
                  <Stat
                    label={t("analytics.revenue")}
                    value={formatNumber(whatIfResult.revenue_inr_lakh, locale)}
                  />
                  <Stat
                    label={t("analytics.grossMargin")}
                    value={
                      whatIfResult.gross_margin_pct === null
                        ? "—"
                        : `${formatNumber(whatIfResult.gross_margin_pct, locale)}%`
                    }
                  />
                  {Object.entries(whatIfResult.unit_economics)
                    .slice(0, 4)
                    .map(([key, value]) => (
                      <Stat key={key} label={humanize(key)} value={formatNumber(value, locale)} />
                    ))}
                </div>
                <h4 className="section-title">{t("analytics.growthCurve")}</h4>
                <div className="table-wrap">
                  <table className="data-table compact">
                    <thead>
                      <tr>
                        <th>Month</th>
                        <th className="align-right">Users</th>
                        <th className="align-right">Cost (USD)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {whatIfResult.growth_curve.map((row) => (
                        <tr key={String(row.month)}>
                          <td>{String(row.month ?? "—")}</td>
                          <td className="align-right">
                            {formatNumber(
                              typeof row.users === "number" ? row.users : null,
                              locale,
                            )}
                          </td>
                          <td className="align-right">
                            {formatCurrency(
                              typeof row.cost_usd === "number" ? row.cost_usd : null,
                              "USD",
                              locale,
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <details>
                  <summary>{t("analytics.assumptions")}</summary>
                  <pre className="json-block">{JSON.stringify(whatIfResult.assumptions, null, 2)}</pre>
                </details>
                {whatIfResult.notes.length ? (
                  <Callout tone="info" title={t("analytics.whatIfNote")}>
                    <ul className="plain-list">
                      {whatIfResult.notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  </Callout>
                ) : null}
              </div>
            ) : null}
          </section>
        </>
      ) : null}

      {tab === "insights" && isAdmin ? (
        <section className="panel">
          {insightsQuery.isPending ? (
            <Spinner />
          ) : insightsQuery.isError ? (
            <FormError message={errorMessage(insightsQuery.error)} />
          ) : insightsQuery.data ? (
            <div className="stack">
              <Callout tone="info" title={t("analytics.advisory")}>
                {insightsQuery.data.note} <Badge tone="neutral">{insightsQuery.data.generator}</Badge>
              </Callout>
              {insightsQuery.data.items.length === 0 ? (
                <p className="muted">{t("analytics.noInsights")}</p>
              ) : (
                <div className="insight-list">
                  {insightsQuery.data.items.map((item) => (
                    <article key={item.id} className="insight-card">
                      <header>
                        <Badge tone="violet">
                          <Sparkles size={12} aria-hidden="true" /> {humanize(item.area)}
                        </Badge>
                        <StatusBadge status={item.status} />
                        {item.advisory ? (
                          <Badge tone="neutral">
                            <Lock size={11} aria-hidden="true" /> {t("analytics.advisory")}
                          </Badge>
                        ) : null}
                      </header>
                      <p>{item.recommendation}</p>
                      <dl className="insight-meta">
                        <div>
                          <dt>{t("analytics.impact")}</dt>
                          <dd>{item.impact}</dd>
                        </div>
                        <div>
                          <dt>{t("analytics.confidence")}</dt>
                          <dd>{humanize(item.confidence)}</dd>
                        </div>
                        <div>
                          <dt>{t("analytics.effort")}</dt>
                          <dd>{humanize(item.effort)}</dd>
                        </div>
                        <div>
                          <dt>{t("analytics.owner")}</dt>
                          <dd>{humanize(item.owner)}</dd>
                        </div>
                      </dl>
                      <div className="evidence-chips">
                        {item.evidence.map((evidence) => (
                          <Badge key={evidence} tone="neutral">
                            {evidence}
                          </Badge>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </div>
          ) : null}
        </section>
      ) : null}

      <p className="muted small footer-note">
        <Info size={13} aria-hidden="true" /> {t("analytics.notConfigured")}
      </p>
    </>
  );
}
