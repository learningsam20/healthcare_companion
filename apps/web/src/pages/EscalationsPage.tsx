import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Hand, Siren } from "lucide-react";
import { useState } from "react";

import { Badge, StatusBadge } from "../components/Badge";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { IconButton } from "../components/IconButton";
import { Modal } from "../components/Modal";
import { Callout, Field, FormError, PageHeader, Spinner, Stat } from "../components/primitives";
import { api, errorMessage, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, formatNumber } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type { TranslationKey } from "../i18n/locales";
import type { GridResponse } from "../lib/types";

interface HandoffRow {
  id: string;
  patient_id: string | null;
  created_by_subject: string;
  assigned_to_subject: string | null;
  clinic_code: string;
  reason: string;
  status: "open" | "assigned" | "resolved";
  priority?: "normal" | "urgent" | "emergency";
  notes: string | null;
  resource_type: string | null;
  resource_id: string | null;
  rule_ids?: string[];
  sla_due_at?: string | null;
  notified_at?: string | null;
  delivery_status?: string;
  overdue?: boolean;
  acknowledged_at?: string | null;
  mtta_seconds?: number | null;
  mtta_within_sla?: boolean | null;
  created_at: string;
  resolved_at: string | null;
}

interface HandoffMttaSummary {
  window_hours: number;
  acknowledged_count: number;
  mean_seconds: number | null;
  p50_seconds: number | null;
  p95_seconds: number | null;
  max_seconds: number | null;
  within_sla_count: number;
  within_sla_ratio: number | null;
  sla_seconds_emergency: number;
  target_met: boolean | null;
}

const STATUSES = ["open", "assigned", "resolved"] as const;

function slaLabel(
  row: HandoffRow,
  locale: string,
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string,
): string {
  if (!row.sla_due_at) return "—";
  if (row.status === "resolved") return t("escalations.slaClosed");
  if (row.overdue) return t("escalations.slaOverdue");
  const due = new Date(row.sla_due_at).getTime();
  const secs = Math.max(0, Math.round((due - Date.now()) / 1000));
  if (secs < 60) return t("escalations.slaSeconds", { secs });
  return t("escalations.slaMinutes", {
    mins: Math.ceil(secs / 60),
    when: formatDateTime(row.sla_due_at, locale),
  });
}

export function EscalationsPage() {
  const { t, locale } = useI18n();
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const grid = useGridState("created_at", "desc");
  const [statusFilter, setStatusFilter] = useState("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [resolveTarget, setResolveTarget] = useState<HandoffRow | null>(null);
  const [notes, setNotes] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const handoffsQuery = useQuery({
    queryKey: ["handoffs", grid.params, statusFilter, overdueOnly],
    queryFn: () =>
      api<GridResponse<HandoffRow>>(
        `/api/v1/handoffs${qs({
          ...grid.params,
          status: statusFilter || undefined,
          overdue: overdueOnly ? true : undefined,
        })}`,
      ),
    placeholderData: (previous) => previous,
    refetchInterval: 15_000,
  });

  const mttaQuery = useQuery({
    queryKey: ["handoffs", "mtta"],
    queryFn: () => api<HandoffMttaSummary>("/api/v1/handoffs/mtta?window_hours=720"),
    refetchInterval: 30_000,
  });

  const assignMutation = useMutation({
    mutationFn: (handoffId: string) =>
      api<HandoffRow>(`/api/v1/handoffs/${handoffId}/assign`, {
        method: "POST",
        body: { assigned_to_subject: me.subject },
      }),
    onSuccess: () => {
      setActionError(null);
      setNotice(t("escalations.assigned"));
      void queryClient.invalidateQueries({ queryKey: ["handoffs"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const resolveMutation = useMutation({
    mutationFn: (payload: { id: string; notes: string }) =>
      api<HandoffRow>(`/api/v1/handoffs/${payload.id}/resolve`, {
        method: "POST",
        body: { notes: payload.notes },
      }),
    onSuccess: () => {
      setResolveTarget(null);
      setNotes("");
      setActionError(null);
      setNotice(t("escalations.resolved"));
      void queryClient.invalidateQueries({ queryKey: ["handoffs"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const columns: DataGridColumn<HandoffRow>[] = [
    {
      key: "reason",
      header: t("escalations.reason"),
      render: (row) => (
        <div className="cell-stack">
          <strong>{row.reason}</strong>
          <span className="muted small mono">
            {row.resource_type ?? "—"} · {row.resource_id?.slice(0, 8) ?? "—"}
          </span>
          {row.rule_ids?.length ? (
            <span className="muted small">Rules: {row.rule_ids.join(", ")}</span>
          ) : null}
        </div>
      ),
    },
    {
      key: "priority",
      header: t("escalations.priority"),
      sortKey: "priority",
      render: (row) => (
        <Badge tone={row.priority === "emergency" ? "danger" : "neutral"}>
          {row.priority ?? "normal"}
        </Badge>
      ),
    },
    {
      key: "sla",
      header: t("escalations.sla"),
      sortKey: "sla_due_at",
      render: (row) => (
        <Badge tone={row.overdue ? "danger" : "info"}>{slaLabel(row, locale, t)}</Badge>
      ),
    },
    {
      key: "mtta",
      header: t("escalations.mtta"),
      hideOnMobile: true,
      render: (row) =>
        row.mtta_seconds != null ? (
          <Badge tone={row.mtta_within_sla === false ? "danger" : "success"}>
            {t("escalations.mttaSeconds", { secs: row.mtta_seconds })}
          </Badge>
        ) : (
          <span className="muted">{t("escalations.mttaPending")}</span>
        ),
    },
    {
      key: "delivery",
      header: t("escalations.notify"),
      hideOnMobile: true,
      render: (row) => row.delivery_status ?? "pending",
    },
    {
      key: "clinic",
      header: t("common.clinic"),
      sortKey: "clinic_code",
      render: (row) => row.clinic_code,
    },
    {
      key: "status",
      header: t("common.status"),
      sortKey: "status",
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "assignee",
      header: t("escalations.assignee"),
      hideOnMobile: true,
      render: (row) =>
        row.assigned_to_subject ?? <span className="muted">{t("escalations.unassigned")}</span>,
    },
    {
      key: "created",
      header: t("common.date"),
      sortKey: "created_at",
      render: (row) => formatDateTime(row.created_at, locale),
    },
    {
      key: "actions",
      header: t("common.actions"),
      align: "right",
      render: (row) => (
        <div className="row-actions">
          {row.status === "open" ? (
            <IconButton
              label={t("escalations.assignToMe")}
              icon={<Hand size={15} />}
              onClick={(event) => {
                event.stopPropagation();
                assignMutation.mutate(row.id);
              }}
            />
          ) : null}
          {row.status !== "resolved" ? (
            <IconButton
              label={t("escalations.resolve")}
              icon={<CheckCircle2 size={15} />}
              onClick={(event) => {
                event.stopPropagation();
                setResolveTarget(row);
                setNotes(row.notes ?? "");
              }}
            />
          ) : null}
        </div>
      ),
    },
  ];

  const mtta = mttaQuery.data;
  const withinPct =
    mtta?.within_sla_ratio != null ? Math.round(mtta.within_sla_ratio * 1000) / 10 : null;

  return (
    <div className="page">
      <PageHeader title={t("escalations.title")} subtitle={t("escalations.subtitle")} />
      {notice ? <Callout tone="success">{notice}</Callout> : null}
      <FormError message={actionError} />

      <section className="panel stack" aria-label={t("escalations.mttaSummary")}>
        <div className="section-head">
          <h2>{t("escalations.mtta")}</h2>
          <span className="muted small">{t("escalations.mttaSummary")}</span>
        </div>
        {mttaQuery.isPending ? (
          <Spinner />
        ) : mttaQuery.isError ? (
          <FormError message={errorMessage(mttaQuery.error)} />
        ) : mtta && mtta.acknowledged_count > 0 ? (
          <div className="stat-grid">
            <Stat
              label={t("escalations.mtta")}
              value={t("escalations.mttaMean", {
                secs: formatNumber(mtta.mean_seconds ?? 0, locale),
              })}
              hint={
                mtta.target_met
                  ? `≤ ${mtta.sla_seconds_emergency}s`
                  : `SLA ${mtta.sla_seconds_emergency}s`
              }
            />
            <Stat
              label={t("escalations.mttaP50", {
                secs: formatNumber(mtta.p50_seconds ?? 0, locale),
              })}
              value={t("escalations.mttaSeconds", {
                secs: formatNumber(mtta.p50_seconds ?? 0, locale),
              })}
              hint={`p95 ${formatNumber(mtta.p95_seconds ?? 0, locale)}s`}
            />
            <Stat
              label={t("escalations.mttaWithinSla", {
                pct: withinPct ?? 0,
                count: mtta.acknowledged_count,
              })}
              value={`${withinPct ?? 0}%`}
              hint={`SLA ${mtta.sla_seconds_emergency}s`}
            />
          </div>
        ) : (
          <Callout tone="info">{t("escalations.mttaEmpty")}</Callout>
        )}
      </section>

      <DataGrid
        columns={columns}
        items={handoffsQuery.data?.items}
        meta={handoffsQuery.data?.meta}
        loading={handoffsQuery.isFetching}
        error={handoffsQuery.error}
        grid={grid}
        rowKey={(row) => row.id}
        onRetry={() => void handoffsQuery.refetch()}
        searchPlaceholder={t("escalations.searchPlaceholder")}
        emptyTitle={t("escalations.emptyTitle")}
        emptyHint={t("escalations.emptyHint")}
        emptyAction={<Siren size={24} aria-hidden="true" />}
        filters={
          <div className="filter-row">
            <label className="filter-field">
              <span>{t("common.status")}</span>
              <select
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(event.target.value);
                  grid.resetPage();
                }}
              >
                <option value="">{t("common.all")}</option>
                {STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field checkbox-inline">
              <input
                type="checkbox"
                checked={overdueOnly}
                onChange={(event) => {
                  setOverdueOnly(event.target.checked);
                  grid.resetPage();
                }}
              />
              <span>{t("escalations.overdueOnly")}</span>
            </label>
          </div>
        }
      />

      <Modal
        open={Boolean(resolveTarget)}
        title={t("escalations.resolveTitle")}
        onClose={() => setResolveTarget(null)}
        busy={resolveMutation.isPending}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setResolveTarget(null)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={notes.trim().length < 2 || resolveMutation.isPending}
              onClick={() => {
                if (!resolveTarget) return;
                resolveMutation.mutate({ id: resolveTarget.id, notes: notes.trim() });
              }}
            >
              {t("escalations.resolve")}
            </button>
          </>
        }
      >
        <Field label={t("escalations.resolveNotes")}>
          <textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            rows={4}
            required
          />
        </Field>
      </Modal>
    </div>
  );
}
