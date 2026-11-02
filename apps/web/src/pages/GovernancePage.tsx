import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCheck2, History, Lock, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Badge } from "../components/Badge";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { Modal } from "../components/Modal";
import {
  Callout,
  Field,
  FormError,
  PageHeader,
  Spinner,
  Tabs,
} from "../components/primitives";
import { api, errorMessage, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, humanize, truncate } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type { AuditChainStatus, AuditEvent, FlagRow, GridResponse } from "../lib/types";

interface AttestationView {
  kind: string;
  status: string;
  approver_name: string | null;
  approver_role: string | null;
  attested_at: string | null;
  has_report: boolean;
  report_filename: string | null;
  report_sha256?: string | null;
  notes: string | null;
  claim: string;
}

interface ComplianceResponse {
  clinical_validation: AttestationView;
  dpdp_audit: AttestationView;
  governance: Record<string, string | number | boolean>;
  pii: { status: string; engine?: string; composite_ready?: boolean; reason?: string };
  egress: {
    env_enabled: boolean;
    admin_toggle: boolean;
    may_enable: boolean;
    note: string;
  };
  disclaimer: string;
}

interface FlagsResponse {
  registry_version: number;
  items: FlagRow[];
  note: string;
}

interface FlagChange {
  id: string;
  flag_key: string;
  old_value: boolean;
  new_value: boolean;
  actor_subject: string;
  reason: string;
  created_at: string;
}

const ROLES = [
  "patient",
  "caregiver",
  "doctor",
  "front_desk",
  "pharmacist",
  "compliance",
  "admin",
  "service",
];

const CLASS_ORDER = ["runtime", "startup", "locked"];

export function GovernancePage() {
  const { t, locale } = useI18n();
  const { hasRole, me } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = hasRole("admin");
  const isCompliance = hasRole("compliance") || isAdmin;
  const [tab, setTab] = useState(isAdmin ? "flags" : isCompliance ? "compliance" : "audit");
  const [notice, setNotice] = useState<string | null>(null);

  const [selected, setSelected] = useState<FlagRow | null>(null);
  const [nextValue, setNextValue] = useState(false);
  const [reason, setReason] = useState("");
  const [flagError, setFlagError] = useState<string | null>(null);

  const auditGrid = useGridState("created_at", "desc");
  const [action, setAction] = useState("");
  const [actorRole, setActorRole] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const flagsQuery = useQuery({
    queryKey: ["admin", "flags"],
    queryFn: () => api<FlagsResponse>("/api/v1/admin/flags"),
    enabled: isAdmin,
  });

  const changesQuery = useQuery({
    queryKey: ["admin", "flag-changes"],
    queryFn: () => api<FlagChange[]>("/api/v1/admin/flags/changes"),
    enabled: isAdmin && tab === "flags",
  });

  const auditQuery = useQuery({
    queryKey: ["admin", "audit", auditGrid.params, action, actorRole, dateFrom, dateTo],
    queryFn: () =>
      api<GridResponse<AuditEvent>>(
        `/api/v1/admin/audit${qs({
          ...auditGrid.params,
          action: action || undefined,
          actor_role: actorRole || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        })}`,
      ),
    enabled: tab === "audit",
    placeholderData: (previous) => previous,
  });

  const chainQuery = useQuery({
    queryKey: ["admin", "audit-chain"],
    queryFn: () => api<AuditChainStatus>("/api/v1/admin/audit/chain"),
    enabled: tab === "audit",
    refetchInterval: 60_000,
  });

  const verifyChainMutation = useMutation({
    mutationFn: () =>
      api<{ status: string; detail: AuditChainStatus["detail"]; error?: string }>(
        "/api/v1/admin/audit/chain/verify",
        { method: "POST" },
      ),
    onSuccess: (payload) => {
      setNotice(
        payload.status === "ok" || payload.status === "empty" || payload.status === "unhashed"
          ? t("admin.chainVerifyOk")
          : t("admin.chainVerifyBroken"),
      );
      void queryClient.invalidateQueries({ queryKey: ["admin", "audit-chain"] });
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const complianceQuery = useQuery({
    queryKey: ["admin", "compliance"],
    queryFn: () => api<ComplianceResponse>("/api/v1/admin/compliance"),
    enabled: isCompliance && tab === "compliance",
  });

  const [attestKind, setAttestKind] = useState<"clinical_validation" | "dpdp_audit">(
    "clinical_validation",
  );
  const [approverName, setApproverName] = useState("");
  const [approverRole, setApproverRole] = useState("");
  const [attestChecked, setAttestChecked] = useState(false);
  const [attestStatus, setAttestStatus] = useState("attested");
  const [attestNotes, setAttestNotes] = useState("");
  const [attestFile, setAttestFile] = useState<File | null>(null);
  const [attestError, setAttestError] = useState<string | null>(null);

  const [finopsDays, setFinopsDays] = useState(90);
  const [chatRetention, setChatRetention] = useState(365);
  const [memoryRetention, setMemoryRetention] = useState(180);
  const [judgeKappa, setJudgeKappa] = useState(0.6);
  const [judgeRequire, setJudgeRequire] = useState(true);
  const [dpdpEnforce, setDpdpEnforce] = useState(false);
  const [govError, setGovError] = useState<string | null>(null);

  const attestMutation = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.set("status", attestStatus);
      form.set("approver_name", approverName);
      form.set("approver_role", approverRole);
      form.set("attestation_checked", attestChecked ? "true" : "false");
      form.set("notes", attestNotes);
      if (attestFile) form.set("report", attestFile);
      return api<AttestationView>(`/api/v1/admin/compliance/${attestKind}/attest`, {
        method: "POST",
        form,
      });
    },
    onSuccess: () => {
      setAttestError(null);
      setNotice(t("admin.attestSaved"));
      setAttestChecked(false);
      setAttestFile(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "compliance"] });
      void queryClient.invalidateQueries({ queryKey: ["meta"] });
    },
    onError: (error) => setAttestError(errorMessage(error)),
  });

  const govMutation = useMutation({
    mutationFn: () =>
      api<{ settings: Record<string, string | number | boolean> }>("/api/v1/admin/governance", {
        method: "PATCH",
        body: {
          finops_history_days: finopsDays,
          chat_retention_days: chatRetention,
          memory_retention_days: memoryRetention,
          judge_min_kappa: judgeKappa,
          judge_require_attested_human: judgeRequire,
          dpdp_enforce: dpdpEnforce,
        },
      }),
    onSuccess: () => {
      setGovError(null);
      setNotice(t("admin.governanceSaved"));
      void queryClient.invalidateQueries({ queryKey: ["admin", "compliance"] });
    },
    onError: (error) => setGovError(errorMessage(error)),
  });

  const syncGovForm = (settings: Record<string, string | number | boolean> | undefined) => {
    if (!settings) return;
    if (typeof settings.finops_history_days === "number") setFinopsDays(settings.finops_history_days);
    if (typeof settings.chat_retention_days === "number") setChatRetention(settings.chat_retention_days);
    if (typeof settings.memory_retention_days === "number")
      setMemoryRetention(settings.memory_retention_days);
    if (typeof settings.judge_min_kappa === "number") setJudgeKappa(settings.judge_min_kappa);
    if (typeof settings.judge_require_attested_human === "boolean")
      setJudgeRequire(settings.judge_require_attested_human);
    if (typeof settings.dpdp_enforce === "boolean") setDpdpEnforce(settings.dpdp_enforce);
  };

  useEffect(() => {
    if (complianceQuery.data?.governance) {
      syncGovForm(complianceQuery.data.governance);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync when query payload changes
  }, [complianceQuery.data]);

  const updateFlag = useMutation({
    mutationFn: (input: { key: string; value: boolean; reason: string }) =>
      api<FlagRow>(`/api/v1/admin/flags/${encodeURIComponent(input.key)}`, {
        method: "PATCH",
        body: { value: input.value, reason: input.reason },
      }),
    onSuccess: () => {
      setSelected(null);
      setReason("");
      setFlagError(null);
      setNotice(t("admin.flagSaved"));
      void queryClient.invalidateQueries({ queryKey: ["admin", "flags"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "flag-changes"] });
      void queryClient.invalidateQueries({ queryKey: ["meta"] });
    },
    onError: (error) => setFlagError(errorMessage(error)),
  });

  const grouped = useMemo(() => {
    const groups = new Map<string, FlagRow[]>();
    for (const flag of flagsQuery.data?.items ?? []) {
      const key = flag.flag_class;
      groups.set(key, [...(groups.get(key) ?? []), flag]);
    }
    const ordered = [...groups.keys()].sort(
      (a, b) => CLASS_ORDER.indexOf(a) - CLASS_ORDER.indexOf(b) || a.localeCompare(b),
    );
    return ordered.map((key) => ({ key, flags: groups.get(key) ?? [] }));
  }, [flagsQuery.data]);

  const openChange = (flag: FlagRow) => {
    setSelected(flag);
    setNextValue(!flag.value);
    setReason("");
    setFlagError(null);
    setNotice(null);
  };

  const submitChange = () => {
    if (!selected) return;
    if (reason.trim().length < 5) {
      setFlagError(t("admin.reasonHint"));
      return;
    }
    setFlagError(null);
    updateFlag.mutate({ key: selected.key, value: nextValue, reason: reason.trim() });
  };

  const auditColumns: DataGridColumn<AuditEvent>[] = [
    {
      key: "created_at",
      header: t("analytics.asOf"),
      sortKey: "created_at",
      render: (row) => <span className="muted nowrap">{formatDateTime(row.created_at, locale)}</span>,
    },
    {
      key: "action",
      header: t("admin.action"),
      sortKey: "action",
      render: (row) => <code className="mono">{row.action}</code>,
    },
    {
      key: "actor_role",
      header: t("admin.actorRole"),
      sortKey: "actor_role",
      render: (row) => <Badge tone="info">{humanize(row.actor_role)}</Badge>,
    },
    {
      key: "actor_subject",
      header: t("admin.actor"),
      hideOnMobile: true,
      render: (row) => (
        <code className="mono muted" title={row.actor_subject}>
          {truncate(row.actor_subject, 24)}
        </code>
      ),
    },
    {
      key: "resource",
      header: t("admin.resource"),
      hideOnMobile: true,
      render: (row) => (
        <div className="cell-stack">
          <span>{humanize(row.resource_type)}</span>
          {row.resource_id ? (
            <code className="mono muted">{truncate(row.resource_id, 24)}</code>
          ) : null}
        </div>
      ),
    },
    {
      key: "trace",
      header: t("admin.traceId"),
      hideOnMobile: true,
      render: (row) =>
        row.trace_id ? (
          <code className="mono muted">{row.trace_id.slice(0, 12)}…</code>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "metadata",
      header: t("admin.metadata"),
      hideOnMobile: true,
      render: (row) =>
        isAdmin && row.metadata ? (
          <code className="mono muted" title={JSON.stringify(row.metadata, null, 2)}>
            {truncate(JSON.stringify(row.metadata), 48)}
          </code>
        ) : (
          <span className="muted">{t("admin.metadataHidden")}</span>
        ),
    },
  ];

  return (
    <>
      <PageHeader title={t("admin.title")} subtitle={t("admin.subtitle")} />

      {notice ? (
        <Callout tone="success" title={t("common.saved")}>
          {notice}
        </Callout>
      ) : null}

      <Tabs
        items={[
          ...(isAdmin ? [{ id: "flags", label: t("admin.flags") }] : []),
          ...(isCompliance ? [{ id: "compliance", label: t("admin.compliance") }] : []),
          { id: "audit", label: t("admin.audit") },
        ]}
        active={tab}
        onChange={(next) => {
          setTab(next);
          if (next === "compliance" && complianceQuery.data) {
            syncGovForm(complianceQuery.data.governance);
          }
        }}
      />

      {tab === "flags" && isAdmin ? (
        <>
          <Callout tone="info" title={t("admin.flagNote")}>
            {t("admin.startupHint")}
          </Callout>

          {flagsQuery.isPending ? (
            <Spinner />
          ) : flagsQuery.isError ? (
            <FormError message={errorMessage(flagsQuery.error)} />
          ) : grouped.length === 0 ? (
            <p className="muted">{t("admin.noFlags")}</p>
          ) : (
            grouped.map((group) => (
              <section key={group.key} className="panel">
                <div className="panel-head">
                  <h3>
                    <ShieldCheck size={17} aria-hidden="true" /> {humanize(group.key)}
                  </h3>
                  <Badge
                    tone={
                      group.key === "locked"
                        ? "danger"
                        : group.key === "startup"
                          ? "warning"
                          : "info"
                    }
                  >
                    {humanize(group.key)}
                  </Badge>
                </div>
                <div className="flag-grid">
                  {group.flags.map((flag) => (
                    <article key={flag.key} className="flag-card">
                      <header>
                        <div>
                          <code className="mono flag-key">{flag.key}</code>
                          <p className="muted small">{flag.description}</p>
                        </div>
                        <Badge tone={flag.value ? "success" : "neutral"}>
                          {flag.value ? t("admin.enabled") : t("admin.disabled")}
                        </Badge>
                      </header>
                      <div className="flag-meta">
                        <span>
                          {t("common.source")}: <strong>{humanize(flag.source)}</strong>
                        </span>
                        <span>
                          {t("admin.flagOwner")}: <strong>{flag.owner}</strong>
                        </span>
                        {flag.expires ? (
                          <span>
                            {t("admin.flagExpires")}: <strong>{flag.expires}</strong>
                          </span>
                        ) : null}
                      </div>
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={!flag.runtime_changeable}
                        title={flag.runtime_changeable ? t("admin.toggleFlag") : t("admin.startupHint")}
                        onClick={() => openChange(flag)}
                      >
                        {flag.runtime_changeable ? (
                          <SlidersHorizontal size={14} aria-hidden="true" />
                        ) : (
                          <Lock size={14} aria-hidden="true" />
                        )}
                        {flag.runtime_changeable ? t("admin.toggleFlag") : t("admin.locked")}
                      </button>
                    </article>
                  ))}
                </div>
              </section>
            ))
          )}

          <section className="panel">
            <div className="panel-head">
              <h3>
                <History size={17} aria-hidden="true" /> {t("admin.flagChanges")}
              </h3>
              <span className="muted small">{t("admin.auditHint")}</span>
            </div>
            {changesQuery.isPending ? (
              <Spinner />
            ) : changesQuery.isError ? (
              <FormError message={errorMessage(changesQuery.error)} />
            ) : (changesQuery.data ?? []).length === 0 ? (
              <p className="muted">{t("admin.noFlags")}</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table compact">
                  <thead>
                    <tr>
                      <th>{t("admin.flagKey")}</th>
                      <th>{t("common.status")}</th>
                      <th>{t("admin.changedBy")}</th>
                      <th>{t("admin.changeReason")}</th>
                      <th>{t("analytics.asOf")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(changesQuery.data ?? []).map((change) => (
                      <tr key={change.id}>
                        <td>
                          <code className="mono">{change.flag_key}</code>
                        </td>
                        <td>
                          <span className="detail-row">
                            <Badge tone={change.old_value ? "success" : "neutral"}>
                              {change.old_value ? t("admin.enabled") : t("admin.disabled")}
                            </Badge>
                            <span aria-hidden="true">→</span>
                            <Badge tone={change.new_value ? "success" : "neutral"}>
                              {change.new_value ? t("admin.enabled") : t("admin.disabled")}
                            </Badge>
                          </span>
                        </td>
                        <td>
                          <code className="mono muted">{truncate(change.actor_subject, 28)}</code>
                        </td>
                        <td>{change.reason}</td>
                        <td className="muted nowrap">{formatDateTime(change.created_at, locale)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}

      {tab === "compliance" && isCompliance ? (
        <>
          <Callout tone="warning" title={t("admin.notRegulatory")}>
            {t("admin.complianceSubtitle")}
          </Callout>
          {complianceQuery.isPending ? (
            <Spinner />
          ) : complianceQuery.isError ? (
            <FormError message={errorMessage(complianceQuery.error)} />
          ) : complianceQuery.data ? (
            <>
              {!complianceQuery.data.dpdp_audit ||
              complianceQuery.data.dpdp_audit.status === "disapproved" ? (
                <Callout tone="danger" title={t("admin.dpdpStopped")}>
                  {complianceQuery.data.disclaimer}
                </Callout>
              ) : null}
              <section className="panel">
                <div className="panel-head">
                  <h3>
                    <FileCheck2 size={17} aria-hidden="true" /> {t("admin.clinicalValidation")}
                  </h3>
                  <Badge
                    tone={
                      complianceQuery.data.clinical_validation.status === "attested"
                        ? "success"
                        : "warning"
                    }
                  >
                    {humanize(complianceQuery.data.clinical_validation.status)}
                  </Badge>
                </div>
                <p className="muted small">
                  {complianceQuery.data.clinical_validation.approver_name
                    ? `${complianceQuery.data.clinical_validation.approver_name} · ${complianceQuery.data.clinical_validation.approver_role ?? ""}`
                    : t("admin.notAttested")}
                  {complianceQuery.data.clinical_validation.has_report
                    ? ` · ${complianceQuery.data.clinical_validation.report_filename}`
                    : ""}
                </p>
              </section>
              <section className="panel">
                <div className="panel-head">
                  <h3>{t("admin.dpdpAudit")}</h3>
                  <Badge
                    tone={
                      complianceQuery.data.dpdp_audit.status === "attested"
                        ? "success"
                        : complianceQuery.data.dpdp_audit.status === "disapproved"
                          ? "danger"
                          : "warning"
                    }
                  >
                    {humanize(complianceQuery.data.dpdp_audit.status)}
                  </Badge>
                </div>
                <p className="muted small">
                  {complianceQuery.data.dpdp_audit.approver_name
                    ? `${complianceQuery.data.dpdp_audit.approver_name} · ${complianceQuery.data.dpdp_audit.approver_role ?? ""}`
                    : t("admin.notAttested")}
                </p>
              </section>
              <section className="panel">
                <div className="panel-head">
                  <h3>{t("admin.piiHealth")}</h3>
                  <Badge tone={complianceQuery.data.pii.composite_ready ? "success" : "warning"}>
                    {complianceQuery.data.pii.engine ?? complianceQuery.data.pii.status}
                  </Badge>
                </div>
                <p className="muted small">{complianceQuery.data.egress.note}</p>
                <p className="muted small">
                  env egress: {complianceQuery.data.egress.env_enabled ? "on" : "off"} · may_enable:{" "}
                  {complianceQuery.data.egress.may_enable ? "yes" : "no"}
                </p>
              </section>
              <section className="panel">
                <div className="panel-head">
                  <h3>{t("admin.attestSubmit")}</h3>
                </div>
                <form
                  className="stack"
                  onSubmit={(event: FormEvent) => {
                    event.preventDefault();
                    attestMutation.mutate();
                  }}
                >
                  <Field label={t("admin.compliance")}>
                    <select
                      value={attestKind}
                      onChange={(event) =>
                        setAttestKind(event.target.value as "clinical_validation" | "dpdp_audit")
                      }
                    >
                      <option value="clinical_validation">{t("admin.clinicalValidation")}</option>
                      <option value="dpdp_audit">{t("admin.dpdpAudit")}</option>
                    </select>
                  </Field>
                  <Field label={t("common.status")}>
                    <select value={attestStatus} onChange={(event) => setAttestStatus(event.target.value)}>
                      <option value="attested">{t("admin.attested")}</option>
                      <option value="pending">{t("admin.pending")}</option>
                      <option value="revoked">{t("admin.revoked")}</option>
                      {attestKind === "dpdp_audit" ? (
                        <option value="disapproved">{t("admin.disapproved")}</option>
                      ) : null}
                      <option value="not_attested">{t("admin.notAttested")}</option>
                    </select>
                  </Field>
                  <Field label={t("admin.approverName")} required>
                    <input
                      value={approverName}
                      onChange={(event) => setApproverName(event.target.value)}
                      maxLength={200}
                      required
                    />
                  </Field>
                  <Field label={t("admin.approverRole")}>
                    <input
                      value={approverRole}
                      onChange={(event) => setApproverRole(event.target.value)}
                      maxLength={120}
                    />
                  </Field>
                  <Field label={t("admin.uploadReport")}>
                    <input
                      type="file"
                      accept=".pdf,.json,.md,.txt,application/pdf,application/json,text/plain,text/markdown"
                      onChange={(event) => setAttestFile(event.target.files?.[0] ?? null)}
                    />
                  </Field>
                  <label className="check-row inline">
                    <input
                      type="checkbox"
                      checked={attestChecked}
                      onChange={(event) => setAttestChecked(event.target.checked)}
                    />
                    <span>{t("admin.attestCheckbox")}</span>
                  </label>
                  <Field label={t("admin.changeReason")}>
                    <textarea
                      rows={3}
                      value={attestNotes}
                      onChange={(event) => setAttestNotes(event.target.value)}
                    />
                  </Field>
                  <FormError message={attestError} />
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={attestMutation.isPending}
                  >
                    {attestMutation.isPending ? <Spinner /> : null}
                    {t("admin.attestSubmit")}
                  </button>
                </form>
              </section>
              {isAdmin ? (
                <section className="panel">
                  <div className="panel-head">
                    <h3>{t("admin.retention")}</h3>
                  </div>
                  <form
                    className="stack"
                    onSubmit={(event: FormEvent) => {
                      event.preventDefault();
                      govMutation.mutate();
                    }}
                  >
                    <Field label={t("admin.finopsDays")}>
                      <input
                        type="number"
                        min={7}
                        max={3650}
                        value={finopsDays}
                        onChange={(event) => setFinopsDays(Number(event.target.value))}
                      />
                    </Field>
                    <Field label={t("admin.chatRetention")}>
                      <input
                        type="number"
                        min={1}
                        max={3650}
                        value={chatRetention}
                        onChange={(event) => setChatRetention(Number(event.target.value))}
                      />
                    </Field>
                    <Field label={t("admin.memoryRetention")}>
                      <input
                        type="number"
                        min={1}
                        max={3650}
                        value={memoryRetention}
                        onChange={(event) => setMemoryRetention(Number(event.target.value))}
                      />
                    </Field>
                    <Field label={t("admin.judgeKappa")}>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={judgeKappa}
                        onChange={(event) => setJudgeKappa(Number(event.target.value))}
                      />
                    </Field>
                    <label className="check-row inline">
                      <input
                        type="checkbox"
                        checked={judgeRequire}
                        onChange={(event) => setJudgeRequire(event.target.checked)}
                      />
                      <span>{t("admin.judgeRequireHuman")}</span>
                    </label>
                    <label className="check-row inline">
                      <input
                        type="checkbox"
                        checked={dpdpEnforce}
                        onChange={(event) => setDpdpEnforce(event.target.checked)}
                      />
                      <span>{t("admin.dpdpEnforce")}</span>
                    </label>
                    <FormError message={govError} />
                    <button type="submit" className="btn btn-primary" disabled={govMutation.isPending}>
                      {govMutation.isPending ? <Spinner /> : null}
                      {t("common.save")}
                    </button>
                  </form>
                </section>
              ) : null}
            </>
          ) : null}
        </>
      ) : null}

      {tab === "audit" ? (
        <>
          {me.primary_role === "compliance" ? (
            <Callout tone="warning" title={t("admin.auditPrivate")}>
              {t("admin.auditHint")}
            </Callout>
          ) : null}
          <section className="panel stack audit-chain-panel" data-testid="audit-chain-status">
            <header className="panel-head">
              <h3>{t("admin.chainTitle")}</h3>
              {isAdmin ? (
                <button
                  type="button"
                  className="btn"
                  disabled={verifyChainMutation.isPending}
                  onClick={() => verifyChainMutation.mutate()}
                >
                  {verifyChainMutation.isPending ? <Spinner /> : null}
                  {t("admin.chainVerifyNow")}
                </button>
              ) : null}
            </header>
            {chainQuery.isError ? (
              <Callout tone="danger">{errorMessage(chainQuery.error)}</Callout>
            ) : chainQuery.isLoading ? (
              <Spinner />
            ) : (
              <div className="chain-status-row">
                <Badge
                  tone={
                    chainQuery.data?.status === "ok"
                      ? "success"
                      : chainQuery.data?.status === "broken"
                        ? "danger"
                        : "warning"
                  }
                >
                  {humanize(chainQuery.data?.status ?? "never_run")}
                </Badge>
                <span className="muted small">
                  {t("admin.chainChecked", {
                    n: chainQuery.data?.detail?.checked ?? 0,
                  })}
                  {chainQuery.data?.detail?.broken_count
                    ? ` · ${t("admin.chainBroken", {
                        n: chainQuery.data.detail.broken_count,
                      })}`
                    : ""}
                </span>
                <span className="muted small">
                  {chainQuery.data?.finished_at
                    ? `${t("admin.chainLastRun")}: ${formatDateTime(chainQuery.data.finished_at, locale)}`
                    : t("admin.chainNever")}
                </span>
                {chainQuery.data?.detail?.tip_hash ? (
                  <code className="mono muted small">
                    tip {chainQuery.data.detail.tip_hash.slice(0, 12)}…
                  </code>
                ) : null}
              </div>
            )}
            <p className="muted small">{t("admin.chainHint")}</p>
          </section>
          <DataGrid
            columns={auditColumns}
            items={auditQuery.data?.items}
            meta={auditQuery.data?.meta}
            loading={auditQuery.isFetching}
            error={auditQuery.error}
            grid={auditGrid}
            rowKey={(row) => row.id}
            onRetry={() => void auditQuery.refetch()}
            searchPlaceholder={t("admin.auditSearch")}
            filters={
              <>
                <Field label={t("admin.action")}>
                  <input
                    value={action}
                    maxLength={80}
                    onChange={(event) => {
                      setAction(event.target.value);
                      auditGrid.setPage(1);
                    }}
                    placeholder="scribe.note_signed"
                  />
                </Field>
                <Field label={t("admin.actorRole")}>
                  <select
                    value={actorRole}
                    onChange={(event) => {
                      setActorRole(event.target.value);
                      auditGrid.setPage(1);
                    }}
                  >
                    <option value="">{t("common.all")}</option>
                    {ROLES.map((role) => (
                      <option key={role} value={role}>
                        {humanize(role)}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={t("common.from")}>
                  <input
                    type="date"
                    value={dateFrom}
                    onChange={(event) => {
                      setDateFrom(event.target.value);
                      auditGrid.setPage(1);
                    }}
                  />
                </Field>
                <Field label={t("common.to")}>
                  <input
                    type="date"
                    value={dateTo}
                    onChange={(event) => {
                      setDateTo(event.target.value);
                      auditGrid.setPage(1);
                    }}
                  />
                </Field>
              </>
            }
            emptyTitle={t("common.emptyTitle")}
          />
        </>
      ) : null}

      <Modal
        open={Boolean(selected)}
        title={selected ? humanize(selected.key) : t("admin.toggleFlag")}
        description={selected?.description}
        onClose={() => setSelected(null)}
        busy={updateFlag.isPending}
        footer={
          <>
            <button
              type="button"
              className="btn"
              onClick={() => setSelected(null)}
              disabled={updateFlag.isPending}
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className={`btn ${nextValue ? "btn-primary" : "btn-danger"}`}
              onClick={submitChange}
              disabled={updateFlag.isPending}
            >
              {updateFlag.isPending ? <Spinner /> : null}
              {t("common.save")}
            </button>
          </>
        }
      >
        {selected ? (
          <div className="stack">
            <div className="detail-row">
              <Badge tone={selected.value ? "success" : "neutral"}>
                {selected.value ? t("admin.enabled") : t("admin.disabled")}
              </Badge>
              <span aria-hidden="true">→</span>
              <Badge tone={nextValue ? "success" : "danger"}>
                {nextValue ? t("admin.enabled") : t("admin.disabled")}
              </Badge>
            </div>
            <label className="check-row inline">
              <input
                type="checkbox"
                checked={nextValue}
                onChange={(event) => setNextValue(event.target.checked)}
              />
              <span>{t("admin.changeTo")}</span>
            </label>
            <Field label={t("admin.changeReason")} required hint={t("admin.reasonHint")}>
              <textarea
                rows={4}
                maxLength={300}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </Field>
            <Callout tone="warning">{t("admin.flagNote")}</Callout>
            <FormError message={flagError} />
          </div>
        ) : null}
      </Modal>
    </>
  );
}
