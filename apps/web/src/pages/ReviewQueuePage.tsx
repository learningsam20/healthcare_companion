import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Eye, Hand, Inbox, Link2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { StatusBadge } from "../components/Badge";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { IconButton } from "../components/IconButton";
import { Modal } from "../components/Modal";
import { Callout, DefinitionList, Field, FormError, PageHeader, Spinner } from "../components/primitives";
import { api, errorMessage, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, humanize } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type { GridResponse, ReviewTask } from "../lib/types";

const STATUSES = ["open", "in_progress", "closed"];
const ROLES = ["doctor", "front_desk", "pharmacist", "compliance", "admin"];

function resourcePath(task: ReviewTask): string | null {
  if (!task.resource_type || !task.resource_id) return null;
  if (task.resource_type === "appointment") return `/appointments`;
  if (task.resource_type === "encounter") return `/scribe`;
  if (task.resource_type === "note") return `/notes`;
  return null;
}

export function ReviewQueuePage() {
  const { t, locale } = useI18n();
  const { me, hasRole } = useAuth();
  const queryClient = useQueryClient();
  const grid = useGridState("created_at", "desc");
  const [statusFilter, setStatusFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [detailTask, setDetailTask] = useState<ReviewTask | null>(null);
  const [closeTarget, setCloseTarget] = useState<ReviewTask | null>(null);
  const [resolution, setResolution] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const isOverseer = hasRole("admin", "compliance");

  const tasksQuery = useQuery({
    queryKey: ["review-queue", grid.params, statusFilter, roleFilter],
    queryFn: () =>
      api<GridResponse<ReviewTask>>(
        `/api/v1/review-queue${qs({
          ...grid.params,
          status: statusFilter || undefined,
          assigned_role: roleFilter || undefined,
        })}`,
      ),
    placeholderData: (previous) => previous,
  });

  const claimMutation = useMutation({
    mutationFn: (taskId: string) =>
      api<ReviewTask>(`/api/v1/review-queue/${taskId}/claim`, { method: "POST" }),
    onSuccess: (task) => {
      setActionError(null);
      setNotice(t("review.claimed"));
      setDetailTask(task);
      if (statusFilter === "open") setStatusFilter("in_progress");
      void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const closeMutation = useMutation({
    mutationFn: (payload: { taskId: string; resolution: string }) =>
      api<ReviewTask>(`/api/v1/review-queue/${payload.taskId}/close`, {
        method: "POST",
        body: { resolution: payload.resolution },
      }),
    onSuccess: () => {
      setCloseTarget(null);
      setDetailTask(null);
      setResolution("");
      setActionError(null);
      setNotice(t("common.saved"));
      void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const columns: DataGridColumn<ReviewTask>[] = [
    {
      key: "reason",
      header: t("review.reason"),
      render: (row) => (
        <div className="cell-stack">
          <strong>{row.reason}</strong>
          <span className="muted mono">
            {row.patient_display_name ?? row.patient_id?.slice(0, 8) ?? "—"}
          </span>
        </div>
      ),
    },
    {
      key: "assigned_role",
      header: t("review.assignedRole"),
      sortKey: "assigned_role",
      render: (row) => <span>{humanize(row.assigned_role)}</span>,
    },
    {
      key: "status",
      header: t("common.status"),
      sortKey: "status",
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "owner",
      header: t("review.owner"),
      hideOnMobile: true,
      render: (row) =>
        row.owner_subject ? (
          <code className="mono">
            {row.owner_subject === me.subject ? t("shell.signedInAs") : `${row.owner_subject.slice(0, 8)}…`}
          </code>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "due_at",
      header: t("review.due"),
      sortKey: "due_at",
      hideOnMobile: true,
      render: (row) =>
        row.due_at ? <span className="muted">{formatDateTime(row.due_at, locale)}</span> : <span className="muted">—</span>,
    },
    {
      key: "resource",
      header: t("review.resource"),
      hideOnMobile: true,
      render: (row) => (
        <div className="cell-stack">
          <span>{row.resource_type ? humanize(row.resource_type) : "—"}</span>
          {row.resource_id ? <code className="mono muted">{row.resource_id.slice(0, 8)}</code> : null}
        </div>
      ),
    },
    {
      key: "actions",
      header: t("common.actions"),
      align: "right",
      width: "140px",
      render: (row) =>
        row.status === "closed" ? (
          <IconButton
            label={t("common.details")}
            icon={<Eye size={16} />}
            onClick={() => setDetailTask(row)}
          />
        ) : (
          <div className="row-actions">
            <IconButton
              label={t("common.details")}
              icon={<Eye size={16} />}
              onClick={() => {
                setDetailTask(row);
                setActionError(null);
              }}
            />
            {!row.owner_subject && row.status === "open" ? (
              <IconButton
                label={t("review.claim")}
                icon={<Hand size={16} />}
                disabled={claimMutation.isPending}
                onClick={() => claimMutation.mutate(row.id)}
              />
            ) : null}
            <IconButton
              label={t("review.closeTask")}
              icon={<CheckCircle2 size={16} />}
              onClick={() => {
                setCloseTarget(row);
                setResolution("");
                setActionError(null);
              }}
            />
          </div>
        ),
    },
  ];

  const linkedPath = detailTask ? resourcePath(detailTask) : null;

  return (
    <>
      <PageHeader title={t("review.title")} subtitle={t("review.subtitle")} />
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
      <DataGrid
        columns={columns}
        items={tasksQuery.data?.items}
        meta={tasksQuery.data?.meta}
        loading={tasksQuery.isFetching}
        error={tasksQuery.error}
        grid={grid}
        rowKey={(row) => row.id}
        onRetry={() => void tasksQuery.refetch()}
        onRowClick={(row) => setDetailTask(row)}
        searchPlaceholder={t("common.searchPlaceholder")}
        filters={
          <>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                grid.setPage(1);
              }}
              aria-label={t("common.status")}
            >
              <option value="">{t("common.all")}</option>
              {STATUSES.map((status) => (
                <option key={status} value={status}>
                  {humanize(status)}
                </option>
              ))}
            </select>
            {isOverseer ? (
              <select
                value={roleFilter}
                onChange={(event) => {
                  setRoleFilter(event.target.value);
                  grid.setPage(1);
                }}
                aria-label={t("review.assignedRole")}
              >
                <option value="">{t("common.all")}</option>
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {humanize(role)}
                  </option>
                ))}
              </select>
            ) : null}
          </>
        }
        emptyTitle={t("review.noTasks")}
        emptyHint={t("common.emptyHint")}
        emptyAction={<Inbox size={20} aria-hidden="true" />}
      />

      <Modal
        open={Boolean(detailTask)}
        title={t("review.title")}
        description={detailTask?.reason}
        onClose={() => setDetailTask(null)}
        footer={
          detailTask && detailTask.status !== "closed" ? (
            <>
              <button type="button" className="btn" onClick={() => setDetailTask(null)}>
                {t("common.close")}
              </button>
              {!detailTask.owner_subject && detailTask.status === "open" ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={claimMutation.isPending}
                  onClick={() => claimMutation.mutate(detailTask.id)}
                >
                  {claimMutation.isPending ? <Spinner /> : <Hand size={16} aria-hidden="true" />}
                  {t("review.claim")}
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => {
                    setCloseTarget(detailTask);
                    setResolution("");
                  }}
                >
                  <CheckCircle2 size={16} aria-hidden="true" />
                  {t("review.closeTask")}
                </button>
              )}
            </>
          ) : (
            <button type="button" className="btn" onClick={() => setDetailTask(null)}>
              {t("common.close")}
            </button>
          )
        }
      >
        {detailTask ? (
          <div className="stack">
            {!detailTask.owner_subject && detailTask.status === "open" ? (
              <Callout tone="info" title={t("review.claim")}>
                {t("review.claimFirst")}
              </Callout>
            ) : null}
            <DefinitionList
              items={[
                [
                  t("common.patient"),
                  detailTask.patient_display_name ?? detailTask.patient_id ?? "—",
                ],
                [t("common.status"), <StatusBadge status={detailTask.status} />],
                [
                  t("review.owner"),
                  detailTask.owner_subject
                    ? detailTask.owner_subject === me.subject
                      ? t("shell.signedInAs")
                      : detailTask.owner_subject
                    : "—",
                ],
                [
                  t("review.due"),
                  detailTask.due_at ? formatDateTime(detailTask.due_at, locale) : "—",
                ],
                [
                  t("review.resource"),
                  detailTask.resource_type
                    ? `${humanize(detailTask.resource_type)} · ${detailTask.resource_id ?? "—"}`
                    : "—",
                ],
              ]}
            />
            {linkedPath ? (
              <Link className="btn btn-sm" to={linkedPath}>
                <Link2 size={14} aria-hidden="true" /> {t("review.openResource")}
              </Link>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(closeTarget)}
        title={t("review.closeTask")}
        description={closeTarget?.reason}
        onClose={() => setCloseTarget(null)}
        busy={closeMutation.isPending}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setCloseTarget(null)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={closeMutation.isPending || resolution.trim().length < 5}
              onClick={() =>
                closeTarget &&
                closeMutation.mutate({ taskId: closeTarget.id, resolution: resolution.trim() })
              }
            >
              {closeMutation.isPending ? <Spinner /> : <CheckCircle2 size={16} aria-hidden="true" />}
              {t("review.closeTask")}
            </button>
          </>
        }
      >
        <div className="stack">
          <Field label={t("review.resolution")} required hint={t("review.resolutionPlaceholder")}>
            <textarea
              rows={4}
              value={resolution}
              maxLength={500}
              onChange={(event) => setResolution(event.target.value)}
              placeholder={t("review.resolutionPlaceholder")}
            />
          </Field>
          <FormError message={actionError} />
        </div>
      </Modal>
    </>
  );
}
