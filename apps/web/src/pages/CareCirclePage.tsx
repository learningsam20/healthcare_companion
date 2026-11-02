import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  HeartHandshake,
  ShieldCheck,
  Trash2,
  UserCheck,
  UserMinus,
} from "lucide-react";
import { useState } from "react";

import { Badge } from "../components/Badge";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { IconButton } from "../components/IconButton";
import { Modal } from "../components/Modal";
import {
  Callout,
  EmptyState,
  Field,
  FormError,
  PageHeader,
  Spinner,
} from "../components/primitives";
import { api, apiDownload, errorMessage, qs, saveBlob } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useCareContext } from "../lib/careContext";
import { formatDate, formatDateTime, humanize } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type { TranslationKey } from "../i18n/locales";
import type { Consent, DeletionRequest, GridResponse } from "../lib/types";

const SCOPES = ["chat", "records", "scheduling", "notifications"] as const;

function scopeLabel(t: (key: TranslationKey) => string, scope: string): string {
  return t(`careCircle.scope.${scope}` as TranslationKey);
}

export function CareCirclePage() {
  const { t, locale } = useI18n();
  const { me } = useAuth();
  const care = useCareContext();
  const queryClient = useQueryClient();
  const isPatient = me.primary_role === "patient";
  const isCaregiver = me.primary_role === "caregiver";
  const canManage = isPatient || me.primary_role === "admin";

  const grid = useGridState("granted_at", "desc");
  const [grantOpen, setGrantOpen] = useState(false);
  const [caregiverSubject, setCaregiverSubject] = useState("");
  const [purpose, setPurpose] = useState("care");
  const [expires, setExpires] = useState("");
  const [scopes, setScopes] = useState<string[]>(["chat", "records"]);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<Consent | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteReason, setDeleteReason] = useState("");

  const consentsQuery = useQuery({
    queryKey: ["consents", grid.params],
    queryFn: () =>
      api<GridResponse<Consent>>(`/api/v1/consents${qs({ ...grid.params })}`),
    enabled: canManage,
    placeholderData: (previous) => previous,
  });

  const deletionQuery = useQuery({
    queryKey: ["me", "deletion-request"],
    queryFn: () => api<{ request: DeletionRequest | null }>("/api/v1/me/deletion-request"),
    enabled: isPatient,
  });

  const refreshConsents = () => {
    void queryClient.invalidateQueries({ queryKey: ["consents"] });
    void queryClient.invalidateQueries({ queryKey: ["me", "contexts"] });
  };

  const grantMutation = useMutation({
    mutationFn: () =>
      api<Consent>("/api/v1/consents", {
        method: "POST",
        body: {
          caregiver_subject: caregiverSubject.trim(),
          purpose: purpose.trim() || "care",
          scopes,
          expires_at: expires ? new Date(`${expires}T23:59:59`).toISOString() : null,
        },
      }),
    onSuccess: () => {
      setGrantOpen(false);
      setCaregiverSubject("");
      setPurpose("care");
      setExpires("");
      setScopes(["chat", "records"]);
      setFormError(null);
      setNotice(t("careCircle.granted"));
      refreshConsents();
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  const revokeMutation = useMutation({
    mutationFn: (consent: Consent) =>
      api<Consent>(`/api/v1/consents/${consent.id}/revoke`, { method: "POST" }),
    onSuccess: () => {
      setRevoking(null);
      setNotice(t("careCircle.revoked"));
      refreshConsents();
    },
    onError: (error) => {
      setRevoking(null);
      setNotice(errorMessage(error));
    },
  });

  const exportMutation = useMutation({
    mutationFn: async () => {
      const { blob, filename } = await apiDownload("/api/v1/me/export");
      saveBlob(blob, filename);
    },
    onSuccess: () => setNotice(t("careCircle.exportDone")),
    onError: (error) => setNotice(errorMessage(error)),
  });

  const requestDeletionMutation = useMutation({
    mutationFn: () =>
      api<DeletionRequest>("/api/v1/me/deletion-request", {
        method: "POST",
        body: { reason: deleteReason.trim() || null },
      }),
    onSuccess: () => {
      setDeleteOpen(false);
      setDeleteReason("");
      setNotice(t("careCircle.deletionRequested"));
      void queryClient.invalidateQueries({ queryKey: ["me", "deletion-request"] });
    },
    onError: (error) => {
      setDeleteOpen(false);
      setNotice(errorMessage(error));
    },
  });

  const cancelDeletionMutation = useMutation({
    mutationFn: () => api<void>("/api/v1/me/deletion-request", { method: "DELETE" }),
    onSuccess: () => {
      setNotice(t("careCircle.deletionCancelled"));
      void queryClient.invalidateQueries({ queryKey: ["me", "deletion-request"] });
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const toggleScope = (scope: string) => {
    setScopes((current) =>
      current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope],
    );
  };

  const submitGrant = () => {
    if (caregiverSubject.trim().length < 3) {
      setFormError(t("careCircle.caregiverRequired"));
      return;
    }
    if (!scopes.length) {
      setFormError(t("careCircle.scopeRequired"));
      return;
    }
    setFormError(null);
    grantMutation.mutate();
  };

  const rows = canManage ? (consentsQuery.data?.items ?? []) : [];
  const openDeletion = deletionQuery.data?.request ?? null;

  const columns: DataGridColumn<Consent>[] = [
    {
      key: "caregiver",
      header: t("careCircle.caregiver"),
      render: (row) => (
        <div className="cell-stack">
          <strong className="mono">{row.caregiver_subject.slice(0, 12)}…</strong>
          {row.patient_name ? <span className="muted">{row.patient_name}</span> : null}
        </div>
      ),
    },
    {
      key: "scopes",
      header: t("careCircle.scopes"),
      render: (row) => (
        <div className="badge-row">
          {row.scopes.map((scope) => (
            <Badge key={scope} tone="info">
              {scopeLabel(t, scope)}
            </Badge>
          ))}
        </div>
      ),
    },
    {
      key: "purpose",
      header: t("careCircle.purpose"),
      hideOnMobile: true,
      render: (row) => <span>{humanize(row.purpose)}</span>,
    },
    {
      key: "status",
      header: t("common.status"),
      render: (row) => (
        <Badge
          tone={
            row.status === "active" ? "success" : row.status === "expired" ? "warning" : "neutral"
          }
        >
          {t(`careCircle.status.${row.status}` as TranslationKey)}
        </Badge>
      ),
    },
    {
      key: "granted_at",
      header: t("careCircle.expires"),
      sortKey: "expires_at",
      hideOnMobile: true,
      render: (row) => (
        <div className="cell-stack">
          <span className="muted">{formatDate(row.granted_at, locale)}</span>
          <span className="muted">
            {row.expires_at ? formatDate(row.expires_at, locale) : "—"}
          </span>
        </div>
      ),
    },
    {
      key: "actions",
      header: t("common.actions"),
      align: "right",
      width: "80px",
      render: (row) =>
        row.status === "active" ? (
          <IconButton
            label={t("careCircle.revoke")}
            icon={<UserMinus size={16} />}
            onClick={() => setRevoking(row)}
          />
        ) : null,
    },
  ];

  return (
    <>
      <PageHeader
        title={t("careCircle.title")}
        subtitle={t("careCircle.subtitle")}
        actions={
          isPatient ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setGrantOpen(true);
                setNotice(null);
              }}
            >
              <UserCheck size={16} aria-hidden="true" /> {t("careCircle.share")}
            </button>
          ) : null
        }
      />

      {notice ? (
        <Callout tone="success" title={t("common.saved")}>
          {notice}
        </Callout>
      ) : null}

      {isCaregiver ? (
        <section className="panel stack">
          <h2 className="section-title">{t("careCircle.contexts")}</h2>
          <p className="muted">{t("careCircle.contextHint")}</p>
          {care.loading ? <Spinner /> : null}
          {!care.loading && care.contexts.length === 0 ? (
            <EmptyState
              title={t("careCircle.noContexts")}
              icon={<HeartHandshake size={22} aria-hidden="true" />}
            />
          ) : null}
          <div className="card-grid">
            {care.contexts.map((context) => {
              const active = care.active?.consent_id === context.consent_id;
              return (
                <article key={context.consent_id} className="panel card">
                  <header className="card-head">
                    <strong>{context.patient_name ?? context.patient_id.slice(0, 8)}</strong>
                    {active ? <Badge tone="success">{t("careCircle.active")}</Badge> : null}
                  </header>
                  <div className="badge-row">
                    {context.scopes.map((scope) => (
                      <Badge key={scope} tone="info">
                        {scopeLabel(t, scope)}
                      </Badge>
                    ))}
                  </div>
                  <p className="muted">
                    {context.expires_at
                      ? t("careCircle.expiresOn", {
                          date: formatDate(context.expires_at, locale),
                        })
                      : t("careCircle.noExpiry")}
                  </p>
                  <div className="row-actions">
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={active}
                      onClick={() => void care.select(context).catch(() => undefined)}
                    >
                      {active ? t("careCircle.active") : t("careCircle.activate")}
                    </button>
                    {active ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => void care.select(null).catch(() => undefined)}
                      >
                        {t("careCircle.clear")}
                      </button>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

      {canManage ? (
        <DataGrid
          columns={columns}
          items={rows}
          meta={consentsQuery.data?.meta}
          loading={consentsQuery.isFetching}
          error={consentsQuery.error}
          grid={grid}
          rowKey={(row) => row.id}
          onRetry={() => void consentsQuery.refetch()}
          searchPlaceholder={t("common.searchPlaceholder")}
          emptyTitle={isPatient ? t("careCircle.noConsents") : t("common.emptyTitle")}
        />
      ) : null}

      {isPatient ? (
        <section className="panel stack">
          <header className="card-head">
            <h2 className="section-title">
              <ShieldCheck size={18} aria-hidden="true" /> {t("careCircle.dataRights")}
            </h2>
          </header>
          <div className="card-grid">
            <article className="panel card">
              <strong>{t("careCircle.export")}</strong>
              <p className="muted">{t("careCircle.exportHint")}</p>
              <button
                type="button"
                className="btn btn-sm"
                disabled={exportMutation.isPending}
                onClick={() => exportMutation.mutate()}
              >
                {exportMutation.isPending ? <Spinner /> : <Download size={15} aria-hidden="true" />}
                {t("careCircle.export")}
              </button>
            </article>
            <article className="panel card">
              <strong>{t("careCircle.deleteRequest")}</strong>
              <p className="muted">{t("careCircle.deleteHint")}</p>
              {openDeletion ? (
                <>
                  <Callout tone="warning" title={t("careCircle.deletionPending")}>
                    {t("careCircle.deletionScheduled", {
                      date: formatDateTime(openDeletion.scheduled_for, locale),
                    })}
                  </Callout>
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={cancelDeletionMutation.isPending}
                    onClick={() => cancelDeletionMutation.mutate()}
                  >
                    {t("careCircle.cancelDeletion")}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  onClick={() => setDeleteOpen(true)}
                >
                  <Trash2 size={15} aria-hidden="true" /> {t("careCircle.deleteRequest")}
                </button>
              )}
            </article>
          </div>
        </section>
      ) : null}

      <Modal
        open={grantOpen}
        title={t("careCircle.share")}
        description={t("careCircle.caregiverHint")}
        onClose={() => setGrantOpen(false)}
        busy={grantMutation.isPending}
        footer={
          <>
            <button
              type="button"
              className="btn"
              onClick={() => setGrantOpen(false)}
              disabled={grantMutation.isPending}
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={submitGrant}
              disabled={grantMutation.isPending}
            >
              {grantMutation.isPending ? <Spinner /> : <UserCheck size={16} aria-hidden="true" />}
              {t("careCircle.share")}
            </button>
          </>
        }
      >
        <div className="stack">
          <Field label={t("careCircle.caregiver")} required hint={t("careCircle.caregiverHint")}>
            <input
              value={caregiverSubject}
              onChange={(event) => setCaregiverSubject(event.target.value)}
              maxLength={200}
              placeholder="caregiver.subject-id"
            />
          </Field>
          <Field label={t("careCircle.purpose")}>
            <input
              value={purpose}
              onChange={(event) => setPurpose(event.target.value)}
              maxLength={200}
            />
          </Field>
          <Field label={t("careCircle.expires")} hint={t("common.optional")}>
            <input
              type="date"
              value={expires}
              onChange={(event) => setExpires(event.target.value)}
            />
          </Field>
          <fieldset className="field">
            <span className="field-label">{t("careCircle.scopes")}</span>
            <div className="checkbox-grid">
              {SCOPES.map((scope) => (
                <label key={scope} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={scopes.includes(scope)}
                    onChange={() => toggleScope(scope)}
                  />
                  <span>{scopeLabel(t, scope)}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <Callout tone="info">{t("careCircle.consentAuditHint")}</Callout>
          <FormError message={formError} />
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(revoking)}
        title={t("careCircle.revoke")}
        body={t("careCircle.revokeConfirm")}
        confirmLabel={t("careCircle.revoke")}
        tone="danger"
        busy={revokeMutation.isPending}
        onConfirm={() => revoking && revokeMutation.mutate(revoking)}
        onClose={() => setRevoking(null)}
      />

      <ConfirmDialog
        open={deleteOpen}
        title={t("careCircle.deleteRequest")}
        body={t("careCircle.deleteConfirm")}
        confirmLabel={t("careCircle.deleteRequest")}
        tone="danger"
        busy={requestDeletionMutation.isPending}
        onConfirm={() => requestDeletionMutation.mutate()}
        onClose={() => setDeleteOpen(false)}
      >
        <Field label={t("careCircle.deleteReason")}>
          <textarea
            value={deleteReason}
            onChange={(event) => setDeleteReason(event.target.value)}
            maxLength={500}
            rows={3}
          />
        </Field>
      </ConfirmDialog>
    </>
  );
}
