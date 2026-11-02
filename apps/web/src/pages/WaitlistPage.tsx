import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Hand, ListChecks, UserPlus } from "lucide-react";
import { useState } from "react";

import { Badge, StatusBadge } from "../components/Badge";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { IconButton } from "../components/IconButton";
import { Modal } from "../components/Modal";
import { PatientPicker } from "../components/PatientPicker";
import {
  Callout,
  DefinitionList,
  Field,
  FormError,
  PageHeader,
  Spinner,
  Stat,
} from "../components/primitives";
import { api, errorMessage, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, humanize } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type { GridResponse, Patient, WaitlistItem } from "../lib/types";

const STATUSES = ["active", "open", "claimed", "closed"] as const;

export function WaitlistPage() {
  const { t, locale } = useI18n();
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const grid = useGridState("starts_at", "asc");
  const [statusFilter, setStatusFilter] = useState<string>("active");
  const [detail, setDetail] = useState<WaitlistItem | null>(null);
  const [closeTarget, setCloseTarget] = useState<WaitlistItem | null>(null);
  const [resolution, setResolution] = useState<"kept" | "offered" | "dismissed">("kept");
  const [notes, setNotes] = useState("");
  const [offerPatient, setOfferPatient] = useState<Patient | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const queueQuery = useQuery({
    queryKey: ["waitlist", grid.params, statusFilter],
    queryFn: () =>
      api<GridResponse<WaitlistItem>>(
        `/api/v1/waitlist${qs({
          ...grid.params,
          status: statusFilter || "active",
        })}`,
      ),
    placeholderData: (previous) => previous,
    refetchInterval: 20_000,
  });

  const openCountQuery = useQuery({
    queryKey: ["waitlist", "open-count"],
    queryFn: () =>
      api<GridResponse<WaitlistItem>>(
        `/api/v1/waitlist${qs({ status: "open", page_size: 1, sort: "starts_at", order: "asc" })}`,
      ),
    refetchInterval: 30_000,
  });

  const claimedCountQuery = useQuery({
    queryKey: ["waitlist", "claimed-count"],
    queryFn: () =>
      api<GridResponse<WaitlistItem>>(
        `/api/v1/waitlist${qs({ status: "claimed", page_size: 1, sort: "starts_at", order: "asc" })}`,
      ),
    refetchInterval: 30_000,
  });

  const claimMutation = useMutation({
    mutationFn: (id: string) =>
      api<WaitlistItem>(`/api/v1/waitlist/${id}/claim`, { method: "POST" }),
    onSuccess: (row) => {
      setActionError(null);
      setNotice(t("waitlist.claimed"));
      setDetail(row);
      void queryClient.invalidateQueries({ queryKey: ["waitlist"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const closeMutation = useMutation({
    mutationFn: (payload: {
      id: string;
      resolution: "kept" | "offered" | "dismissed";
      notes?: string;
      offer_patient_id?: string;
    }) =>
      api<WaitlistItem>(`/api/v1/waitlist/${payload.id}/close`, {
        method: "POST",
        body: {
          resolution: payload.resolution,
          notes: payload.notes || undefined,
          offer_patient_id: payload.offer_patient_id,
        },
      }),
    onSuccess: () => {
      setCloseTarget(null);
      setDetail(null);
      setNotes("");
      setOfferPatient(null);
      setResolution("kept");
      setActionError(null);
      setNotice(t("waitlist.closed"));
      void queryClient.invalidateQueries({ queryKey: ["waitlist"] });
      void queryClient.invalidateQueries({ queryKey: ["appointments"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const columns: DataGridColumn<WaitlistItem>[] = [
    {
      key: "slot",
      header: t("waitlist.slot"),
      sortKey: "starts_at",
      render: (row) => (
        <div className="cell-stack">
          <strong>{row.doctor_name}</strong>
          <span className="muted small">
            {row.clinic_code} · {formatDateTime(row.starts_at, locale)}
          </span>
        </div>
      ),
    },
    {
      key: "patient",
      header: t("common.patient"),
      render: (row) => (
        <span>{row.patient_display_name ?? row.patient_id?.slice(0, 8) ?? "—"}</span>
      ),
    },
    {
      key: "risk",
      header: t("appointments.noShowRisk"),
      sortKey: "no_show_risk",
      render: (row) => (
        <div className="badge-row">
          <Badge
            tone={
              row.no_show_band === "high"
                ? "danger"
                : row.no_show_band === "medium"
                  ? "warning"
                  : "neutral"
            }
          >
            {row.no_show_band ?? "—"}
            {typeof row.no_show_risk === "number"
              ? ` ${Math.round(row.no_show_risk * 100)}%`
              : ""}
          </Badge>
        </div>
      ),
    },
    {
      key: "queue",
      header: t("common.status"),
      render: (row) => (
        <div className="badge-row">
          <StatusBadge status={row.waitlist_status ?? "open"} />
          {row.waitlist_resolution ? (
            <Badge tone="info">{humanize(row.waitlist_resolution)}</Badge>
          ) : null}
        </div>
      ),
    },
    {
      key: "owner",
      header: t("waitlist.owner"),
      hideOnMobile: true,
      render: (row) =>
        row.waitlist_owner_subject ? (
          <code className="mono">
            {row.waitlist_owner_subject === me.subject
              ? t("shell.signedInAs")
              : `${row.waitlist_owner_subject.slice(0, 8)}…`}
          </code>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "actions",
      header: t("common.actions"),
      align: "right",
      width: "140px",
      render: (row) =>
        row.waitlist_status === "closed" ? (
          <IconButton
            label={t("common.details")}
            icon={<ListChecks size={16} />}
            onClick={() => setDetail(row)}
          />
        ) : (
          <div className="row-actions">
            {row.waitlist_status === "open" ? (
              <IconButton
                label={t("waitlist.claim")}
                icon={<Hand size={16} />}
                disabled={claimMutation.isPending}
                onClick={() => claimMutation.mutate(row.id)}
              />
            ) : null}
            <IconButton
              label={t("waitlist.resolve")}
              icon={<CheckCircle2 size={16} />}
              onClick={() => {
                setCloseTarget(row);
                setResolution("kept");
                setNotes("");
                setOfferPatient(null);
                setActionError(null);
              }}
            />
          </div>
        ),
    },
  ];

  return (
    <div className="page">
      <PageHeader title={t("waitlist.title")} subtitle={t("waitlist.subtitle")} />

      <div className="stat-grid" data-testid="waitlist-stats">
        <Stat
          label={t("waitlist.open")}
          value={openCountQuery.isLoading ? "…" : String(openCountQuery.data?.meta.total ?? 0)}
          hint={t("waitlist.openHint")}
        />
        <Stat
          label={t("waitlist.claimedStat")}
          value={
            claimedCountQuery.isLoading ? "…" : String(claimedCountQuery.data?.meta.total ?? 0)
          }
          hint={t("waitlist.claimedHint")}
        />
        <Stat
          label={t("waitlist.inQueue")}
          value={queueQuery.isLoading ? "…" : String(queueQuery.data?.meta.total ?? 0)}
          hint={humanize(statusFilter)}
        />
      </div>

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

      <Callout tone="info" title={t("waitlist.howTitle")}>
        {t("waitlist.howBody")}
      </Callout>

      <DataGrid
        columns={columns}
        items={queueQuery.data?.items}
        meta={queueQuery.data?.meta}
        loading={queueQuery.isFetching}
        error={queueQuery.error}
        grid={grid}
        rowKey={(row) => row.id}
        onRetry={() => void queueQuery.refetch()}
        onRowClick={(row) => setDetail(row)}
        searchPlaceholder={t("waitlist.search")}
        filters={
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value);
              grid.setPage(1);
            }}
            aria-label={t("common.status")}
          >
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {t(`waitlist.status.${status}` as "waitlist.status.active")}
              </option>
            ))}
          </select>
        }
        emptyTitle={t("waitlist.empty")}
        emptyHint={t("waitlist.emptyHint")}
        emptyAction={<ListChecks size={20} aria-hidden="true" />}
      />

      <Modal
        open={Boolean(detail)}
        title={t("waitlist.detailTitle")}
        description={detail?.doctor_name}
        onClose={() => setDetail(null)}
        footer={
          detail && detail.waitlist_status !== "closed" ? (
            <>
              <button type="button" className="btn" onClick={() => setDetail(null)}>
                {t("common.close")}
              </button>
              {detail.waitlist_status === "open" ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={claimMutation.isPending}
                  onClick={() => claimMutation.mutate(detail.id)}
                >
                  {claimMutation.isPending ? <Spinner /> : <Hand size={16} aria-hidden="true" />}
                  {t("waitlist.claim")}
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => {
                    setCloseTarget(detail);
                    setResolution("kept");
                  }}
                >
                  <CheckCircle2 size={16} aria-hidden="true" />
                  {t("waitlist.resolve")}
                </button>
              )}
            </>
          ) : (
            <button type="button" className="btn" onClick={() => setDetail(null)}>
              {t("common.close")}
            </button>
          )
        }
      >
        {detail ? (
          <div className="stack">
            <DefinitionList
              items={[
                [
                  t("common.patient"),
                  detail.patient_display_name ?? detail.patient_id ?? "—",
                ],
                [t("common.status"), <StatusBadge status={detail.waitlist_status ?? "open"} />],
                [
                  t("appointments.noShowRisk"),
                  `${detail.no_show_band ?? "—"} (${
                    typeof detail.no_show_risk === "number"
                      ? `${Math.round(detail.no_show_risk * 100)}%`
                      : "—"
                  })`,
                ],
                [t("common.clinic"), detail.clinic_code],
                [t("waitlist.when"), formatDateTime(detail.starts_at, locale)],
                [
                  t("waitlist.owner"),
                  detail.waitlist_owner_subject === me.subject
                    ? t("shell.signedInAs")
                    : (detail.waitlist_owner_subject ?? "—"),
                ],
                [
                  t("waitlist.resolution"),
                  detail.waitlist_resolution ? humanize(detail.waitlist_resolution) : "—",
                ],
                [
                  t("waitlist.offerPatient"),
                  detail.offer_patient_display_name ??
                    detail.waitlist_offer_patient_id ??
                    "—",
                ],
                [t("waitlist.notes"), detail.waitlist_notes ?? "—"],
              ]}
            />
          </div>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(closeTarget)}
        title={t("waitlist.resolve")}
        description={closeTarget?.doctor_name}
        onClose={() => setCloseTarget(null)}
        busy={closeMutation.isPending}
        footer={
          <>
            <button
              type="button"
              className="btn"
              onClick={() => setCloseTarget(null)}
              disabled={closeMutation.isPending}
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={
                closeMutation.isPending ||
                (resolution === "offered" && !offerPatient)
              }
              onClick={() => {
                if (!closeTarget) return;
                closeMutation.mutate({
                  id: closeTarget.id,
                  resolution,
                  notes: notes.trim() || undefined,
                  offer_patient_id: offerPatient?.id,
                });
              }}
            >
              {closeMutation.isPending ? <Spinner /> : <UserPlus size={16} aria-hidden="true" />}
              {t("waitlist.confirmResolve")}
            </button>
          </>
        }
      >
        {closeTarget ? (
          <div className="stack">
            <Field label={t("waitlist.resolution")}>
              <select
                value={resolution}
                onChange={(event) =>
                  setResolution(event.target.value as "kept" | "offered" | "dismissed")
                }
              >
                <option value="kept">{t("waitlist.res.kept")}</option>
                <option value="offered">{t("waitlist.res.offered")}</option>
                <option value="dismissed">{t("waitlist.res.dismissed")}</option>
              </select>
            </Field>
            {resolution === "offered" ? (
              <Field label={t("waitlist.offerPatient")}>
                <PatientPicker value={offerPatient} onChange={setOfferPatient} />
                <span className="muted small">{t("waitlist.offerHint")}</span>
              </Field>
            ) : null}
            <Field label={t("waitlist.notes")}>
              <textarea
                value={notes}
                maxLength={500}
                rows={3}
                onChange={(event) => setNotes(event.target.value)}
                placeholder={t("waitlist.notesPlaceholder")}
              />
            </Field>
            {closeMutation.isError ? (
              <FormError message={errorMessage(closeMutation.error)} />
            ) : null}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
