import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, Mail, Plus, Send } from "lucide-react";
import { useState } from "react";

import { Badge, StatusBadge } from "../components/Badge";
import { ContactVerify } from "../components/ContactVerify";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { Modal } from "../components/Modal";
import { PatientPicker } from "../components/PatientPicker";
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
import { formatDateTime, humanize } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type {
  ContactChannel,
  GridResponse,
  Meta,
  NotificationDetail,
  NotificationRow,
  Patient,
  Template,
} from "../lib/types";

interface NotificationList extends GridResponse<NotificationRow> {
  unread: number;
}

interface TemplatesResponse {
  version: string | null;
  templates: Template[];
}

interface SendResult {
  notification: NotificationDetail;
  queued_channels: number;
  suppressed_channels: number;
}

const STATUSES = ["unread", "read"];
const CHANNELS = ["email", "sms", "slack_staff", "slack_patient"];
const ROLES = ["patient", "caregiver", "doctor", "front_desk", "pharmacist", "compliance", "admin"];
const CONTACT_CHANNELS = ["email", "sms", "slack_staff", "slack_patient"];

export function NotificationsPage() {
  const { t, locale } = useI18n();
  const { me, hasRole } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = hasRole("admin");
  const [tab, setTab] = useState("inbox");

  const [statusFilter, setStatusFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const [allUsers, setAllUsers] = useState(false);
  const inboxGrid = useGridState("created_at", "desc");
  const [detailId, setDetailId] = useState<string | null>(null);

  const contactsGrid = useGridState("created_at", "desc");
  const [contactSubject, setContactSubject] = useState("");
  const [contactOpen, setContactOpen] = useState(false);
  const [contactPatient, setContactPatient] = useState<Patient | null>(null);
  const [contactSubjectValue, setContactSubjectValue] = useState("");
  const [contactChannel, setContactChannel] = useState("email");
  const [contactAddress, setContactAddress] = useState("");
  const [contactVerified, setContactVerified] = useState(false);
  const [contactOptIn, setContactOptIn] = useState(false);
  const [contactWorkspace, setContactWorkspace] = useState("");
  const [contactError, setContactError] = useState<string | null>(null);

  const [templateId, setTemplateId] = useState("");
  const [recipient, setRecipient] = useState("");
  const [recipientRole, setRecipientRole] = useState("patient");
  const [sendLocale, setSendLocale] = useState("en-IN");
  const [sendPatient, setSendPatient] = useState<Patient | null>(null);
  const [sendData, setSendData] = useState("{}");
  const [sendChannels, setSendChannels] = useState<string[]>([]);
  const [sendError, setSendError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const inboxQuery = useQuery({
    queryKey: ["notifications", "inbox", inboxGrid.params, statusFilter, channelFilter, allUsers],
    queryFn: () =>
      api<NotificationList>(
        `/api/v1/notifications${qs({
          ...inboxGrid.params,
          status: statusFilter || undefined,
          channel: channelFilter || undefined,
          all_users: allUsers || undefined,
        })}`,
      ),
    placeholderData: (previous) => previous,
  });

  const detailQuery = useQuery({
    queryKey: ["notifications", "detail", detailId],
    queryFn: () => api<NotificationDetail>(`/api/v1/notifications/${detailId}`),
    enabled: Boolean(detailId),
  });

  const metaQuery = useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/api/v1/meta"),
    enabled: isAdmin && tab === "contacts",
    staleTime: 120_000,
  });

  const templatesQuery = useQuery({
    queryKey: ["notifications", "templates"],
    queryFn: () => api<TemplatesResponse>("/api/v1/notifications/templates"),
    enabled: isAdmin && (tab === "send" || tab === "templates"),
    staleTime: 60_000,
  });

  const contactsQuery = useQuery({
    queryKey: ["notifications", "contacts", contactsGrid.params, contactSubject],
    queryFn: () =>
      api<GridResponse<ContactChannel>>(
        `/api/v1/notifications/contacts/list${qs({
          ...contactsGrid.params,
          subject: contactSubject || undefined,
        })}`,
      ),
    enabled: isAdmin && tab === "contacts",
    placeholderData: (previous) => previous,
  });

  const markRead = useMutation({
    mutationFn: (id: string) =>
      api<NotificationRow>(`/api/v1/notifications/${id}/read`, { method: "POST" }),
    onSuccess: (updated) => {
      queryClient.setQueryData<NotificationDetail | undefined>(
        ["notifications", "detail", updated.id],
        (current) => (current ? { ...current, ...updated } : current),
      );
      void queryClient.invalidateQueries({ queryKey: ["notifications", "inbox"] });
      void queryClient.invalidateQueries({ queryKey: ["notifications", "unread-count"] });
    },
    onError: (error) => setSendError(errorMessage(error)),
  });

  const saveContact = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<ContactChannel>("/api/v1/notifications/contacts", { method: "POST", body }),
    onSuccess: () => {
      setContactOpen(false);
      setContactSubjectValue("");
      setContactAddress("");
      setContactWorkspace("");
      setContactVerified(false);
      setContactOptIn(false);
      setContactPatient(null);
      setContactError(null);
      setNotice(t("notifications.contactSaved"));
      void queryClient.invalidateQueries({ queryKey: ["notifications", "contacts"] });
    },
    onError: (error) => setContactError(errorMessage(error)),
  });

  const sendNotification = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<SendResult>("/api/v1/notifications/send", { method: "POST", body }),
    onSuccess: (result) => {
      setSendError(null);
      setNotice(
        `${t("notifications.sent")} ${t("notifications.queued", {
          count: result.queued_channels,
        })} · ${t("notifications.suppressed", { count: result.suppressed_channels })}`,
      );
      setSendData("{}");
      setSendChannels([]);
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (error) => setSendError(errorMessage(error)),
  });

  const submitContact = () => {
    if (contactSubjectValue.trim().length < 2 || contactAddress.trim().length < 3) {
      setContactError(t("notifications.contactRequired"));
      return;
    }
    setContactError(null);
    saveContact.mutate({
      subject: contactSubjectValue.trim(),
      patient_id: contactPatient?.id,
      channel: contactChannel,
      address: contactAddress.trim(),
      verified: contactVerified,
      opt_in: contactOptIn,
      workspace_id: contactWorkspace.trim() || undefined,
    });
  };

  const submitSend = () => {
    if (!templateId) {
      setSendError(t("notifications.template"));
      return;
    }
    if (recipient.trim().length < 2) {
      setSendError(t("notifications.recipient"));
      return;
    }
    let data: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(sendData || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("not_object");
      }
      data = parsed as Record<string, unknown>;
    } catch {
      setSendError(t("notifications.invalidJson"));
      return;
    }
    setSendError(null);
    sendNotification.mutate({
      template_id: templateId,
      recipient_subject: recipient.trim(),
      recipient_role: recipientRole,
      patient_id: sendPatient?.id,
      locale: sendLocale,
      data,
      channels: sendChannels.length ? sendChannels : undefined,
    });
  };

  const openDetail = (row: NotificationRow) => {
    setDetailId(row.id);
    setSendError(null);
  };

  const columns: DataGridColumn<NotificationRow>[] = [
    {
      key: "title",
      header: t("notifications.detail"),
      render: (row) => (
        <div className="cell-stack">
          <strong>{row.title}</strong>
          <span className="muted truncate">{row.body}</span>
        </div>
      ),
    },
    {
      key: "channel",
      header: t("notifications.channel"),
      render: (row) => <Badge tone="neutral">{humanize(row.channel)}</Badge>,
    },
    {
      key: "status",
      header: t("common.status"),
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "recipient",
      header: t("notifications.recipient"),
      hideOnMobile: true,
      render: (row) => <code className="mono muted">{row.recipient_subject.slice(0, 12)}…</code>,
    },
    {
      key: "created_at",
      header: t("patients.created"),
      hideOnMobile: true,
      render: (row) => <span className="muted">{formatDateTime(row.created_at, locale)}</span>,
    },
  ];

  const contactColumns: DataGridColumn<ContactChannel>[] = [
    {
      key: "subject",
      header: t("notifications.recipient"),
      render: (row) => <code className="mono">{row.subject}</code>,
    },
    {
      key: "channel",
      header: t("notifications.channel"),
      render: (row) => <Badge tone="neutral">{humanize(row.channel)}</Badge>,
    },
    {
      key: "address",
      header: t("notifications.address"),
      render: (row) => <span>{row.address}</span>,
    },
    {
      key: "verified",
      header: t("notifications.verified"),
      render: (row) =>
        row.verified ? (
          <Badge tone="success">{t("notifications.verified")}</Badge>
        ) : (
          <Badge tone="warning">{t("common.unknown")}</Badge>
        ),
    },
    {
      key: "opt_in",
      header: t("notifications.optIn"),
      render: (row) =>
        row.opt_in ? (
          <Badge tone="success">{t("notifications.optIn")}</Badge>
        ) : (
          <Badge tone="neutral">{t("common.all")}</Badge>
        ),
    },
    {
      key: "workspace",
      header: t("notifications.workspace"),
      hideOnMobile: true,
      render: (row) => row.workspace_id ?? <span className="muted">—</span>,
    },
    {
      key: "verify",
      header: t("notifications.verifyContact"),
      render: (row) => (
        <ContactVerify
          contact={row}
          channelStatus={metaQuery.data?.adapters?.[row.channel]?.status}
          environment={metaQuery.data?.app.environment}
        />
      ),
    },
  ];

  const detail = detailQuery.data;
  const canMarkRead = detail && detail.recipient_subject === me.subject && detail.status !== "read";

  return (
    <>
      <PageHeader title={t("notifications.title")} subtitle={t("notifications.subtitle")} />

      {notice ? (
        <Callout tone="success" title={t("common.saved")}>
          {notice}
        </Callout>
      ) : null}
      {sendError && tab !== "send" ? <FormError message={sendError} /> : null}

      <Tabs
        items={[
          { id: "inbox", label: t("notifications.inbox") },
          ...(isAdmin
            ? [
                { id: "send", label: t("notifications.sendNotification") },
                { id: "contacts", label: t("notifications.contacts") },
              ]
            : []),
          { id: "templates", label: t("notifications.templates") },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === "inbox" ? (
        <DataGrid
          columns={columns}
          items={inboxQuery.data?.items}
          meta={inboxQuery.data?.meta}
          loading={inboxQuery.isFetching}
          error={inboxQuery.error}
          grid={inboxGrid}
          rowKey={(row) => row.id}
          onRetry={() => void inboxQuery.refetch()}
          onRowClick={openDetail}
          searchPlaceholder={t("common.searchPlaceholder")}
          filters={
            <>
              <select
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(event.target.value);
                  inboxGrid.setPage(1);
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
              <select
                value={channelFilter}
                onChange={(event) => {
                  setChannelFilter(event.target.value);
                  inboxGrid.setPage(1);
                }}
                aria-label={t("notifications.channel")}
              >
                <option value="">{t("common.all")}</option>
                {CHANNELS.map((channel) => (
                  <option key={channel} value={channel}>
                    {humanize(channel)}
                  </option>
                ))}
              </select>
              {isAdmin ? (
                <label className="check-row inline">
                  <input
                    type="checkbox"
                    checked={allUsers}
                    onChange={(event) => {
                      setAllUsers(event.target.checked);
                      inboxGrid.setPage(1);
                    }}
                  />
                  <span>{t("notifications.allUsers")}</span>
                </label>
              ) : null}
            </>
          }
          emptyTitle={t("notifications.noNotifications")}
        />
      ) : null}

      {tab === "send" && isAdmin ? (
        <section className="panel">
          <div className="panel-head">
            <h3>
              <Send size={17} aria-hidden="true" /> {t("notifications.sendNotification")}
            </h3>
            <span className="muted small">{t("notifications.contactsNote")}</span>
          </div>
          <div className="form-grid">
            <Field label={t("notifications.template")} required>
              <select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
                <option value="">{t("notifications.template")}</option>
                {(templatesQuery.data?.templates ?? []).map((template) => (
                  <option key={template.id} value={template.id}>
                    {humanize(template.id)} (v{template.version})
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("notifications.recipient")} required>
              <input
                value={recipient}
                maxLength={200}
                onChange={(event) => setRecipient(event.target.value)}
              />
            </Field>
            <Field label={t("notifications.recipientRole")}>
              <select value={recipientRole} onChange={(event) => setRecipientRole(event.target.value)}>
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {humanize(role)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("common.language")}>
              <select value={sendLocale} onChange={(event) => setSendLocale(event.target.value)}>
                {["en-IN", "hi-IN", "mr-IN"].map((code) => (
                  <option key={code} value={code}>
                    {humanize(code)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("common.patient")} hint={t("common.optional")}>
              <PatientPicker value={sendPatient} onChange={setSendPatient} />
            </Field>
            <Field label={t("notifications.channels")} hint={t("notifications.slackPatient")}>
              <div className="checkbox-row">
                {CHANNELS.map((channel) => (
                  <label key={channel} className="check-row inline">
                    <input
                      type="checkbox"
                      checked={sendChannels.includes(channel)}
                      onChange={(event) =>
                        setSendChannels((current) =>
                          event.target.checked
                            ? [...current, channel]
                            : current.filter((item) => item !== channel),
                        )
                      }
                    />
                    <span>{humanize(channel)}</span>
                  </label>
                ))}
              </div>
            </Field>
          </div>
          <Field label={t("notifications.data")} hint={t("notifications.dataHint")}>
            <textarea
              rows={6}
              value={sendData}
              onChange={(event) => setSendData(event.target.value)}
              spellCheck={false}
            />
          </Field>
          <FormError message={sendError} />
          <div className="form-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={sendNotification.isPending}
              onClick={submitSend}
            >
              {sendNotification.isPending ? <Spinner /> : <Send size={15} aria-hidden="true" />}
              {t("notifications.sendNow")}
            </button>
          </div>
        </section>
      ) : null}

      {tab === "contacts" && isAdmin ? (
        <>
          <section className="panel">
            <div className="panel-head">
              <h3>
                <Mail size={17} aria-hidden="true" /> {t("notifications.contacts")}
              </h3>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => setContactOpen(true)}>
                <Plus size={14} aria-hidden="true" /> {t("notifications.addContact")}
              </button>
            </div>
            <Field label={t("notifications.recipient")}>
              <input
                type="search"
                value={contactSubject}
                onChange={(event) => {
                  setContactSubject(event.target.value);
                  contactsGrid.setPage(1);
                }}
                placeholder={t("common.searchPlaceholder")}
              />
            </Field>
            <Callout tone="info">{t("notifications.slackPatient")}</Callout>
          </section>
          <DataGrid
            columns={contactColumns}
            items={contactsQuery.data?.items}
            meta={contactsQuery.data?.meta}
            loading={contactsQuery.isFetching}
            error={contactsQuery.error}
            grid={contactsGrid}
            rowKey={(row) => row.id}
            onRetry={() => void contactsQuery.refetch()}
            hideSearch
            emptyTitle={t("common.emptyTitle")}
          />
        </>
      ) : null}

      {tab === "templates" ? (
        <section className="panel">
          {templatesQuery.isPending ? (
            <Spinner />
          ) : templatesQuery.isError ? (
            <FormError message={errorMessage(templatesQuery.error)} />
          ) : (
            <div className="template-grid">
              {(templatesQuery.data?.templates ?? []).map((template) => (
                <article key={template.id} className="template-card">
                  <header>
                    <strong>{humanize(template.id)}</strong>
                    <Badge tone="neutral">v{template.version}</Badge>
                  </header>
                  <div className="tag-row">
                    {template.channels.map((channel) => (
                      <Badge key={channel} tone="info">
                        {humanize(channel)}
                      </Badge>
                    ))}
                    <Badge tone={template.clinical_detail ? "danger" : "success"}>
                      {template.clinical_detail ? t("common.required") : t("settings.noPhi")}
                    </Badge>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}

      <Modal
        open={Boolean(detailId)}
        title={detail?.title ?? t("notifications.detail")}
        onClose={() => setDetailId(null)}
        size="lg"
        footer={
          canMarkRead ? (
            <button
              type="button"
              className="btn btn-primary"
              disabled={markRead.isPending}
              onClick={() => detail && markRead.mutate(detail.id)}
            >
              {markRead.isPending ? <Spinner /> : <CheckCheck size={15} aria-hidden="true" />}
              {t("common.markRead")}
            </button>
          ) : null
        }
      >
        {detailQuery.isPending ? (
          <Spinner />
        ) : detailQuery.isError ? (
          <FormError message={errorMessage(detailQuery.error)} />
        ) : detail ? (
          <div className="stack">
            <div className="detail-row">
              <StatusBadge status={detail.status} />
              <Badge tone="neutral">{humanize(detail.channel)}</Badge>
              <span className="muted">{formatDateTime(detail.created_at, locale)}</span>
              <Badge tone="neutral">{humanize(detail.recipient_role)}</Badge>
            </div>
            <p className="notification-body">{detail.body}</p>
            <div className="detail-row muted">
              <span>
                {t("notifications.recipient")}: <code className="mono">{detail.recipient_subject}</code>
              </span>
              <span>
                {t("notifications.template")}: <code className="mono">{detail.template_id}</code> v
                {detail.template_version}
              </span>
            </div>
            <h3 className="section-title">{t("notifications.deliveries")}</h3>
            {detail.deliveries.length === 0 ? (
              <p className="muted">{t("common.emptyTitle")}</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table compact">
                  <thead>
                    <tr>
                      <th>{t("notifications.channel")}</th>
                      <th>{t("common.status")}</th>
                      <th className="align-right">{t("notifications.attempts")}</th>
                      <th>{t("notifications.scheduledAt")}</th>
                      <th>{t("notifications.sentAt")}</th>
                      <th>{t("notifications.lastError")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.deliveries.map((delivery) => (
                      <tr key={delivery.id}>
                        <td>{humanize(delivery.channel)}</td>
                        <td>
                          <StatusBadge status={delivery.status} />
                        </td>
                        <td className="align-right">{delivery.attempts}</td>
                        <td>{formatDateTime(delivery.scheduled_at, locale)}</td>
                        <td>{formatDateTime(delivery.sent_at, locale)}</td>
                        <td>
                          {delivery.last_error_code ? (
                            <code className="mono danger-text">{delivery.last_error_code}</code>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={contactOpen}
        title={t("notifications.addContact")}
        onClose={() => setContactOpen(false)}
        busy={saveContact.isPending}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setContactOpen(false)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={saveContact.isPending}
              onClick={submitContact}
            >
              {saveContact.isPending ? <Spinner /> : <Plus size={15} aria-hidden="true" />}
              {t("notifications.addContact")}
            </button>
          </>
        }
      >
        <div className="stack">
          <Field label={t("notifications.recipient")} required>
            <input
              value={contactSubjectValue}
              maxLength={200}
              onChange={(event) => setContactSubjectValue(event.target.value)}
            />
          </Field>
          <div className="field-row">
            <Field label={t("notifications.channel")} required>
              <select
                value={contactChannel}
                onChange={(event) => setContactChannel(event.target.value)}
              >
                {CONTACT_CHANNELS.map((channel) => (
                  <option key={channel} value={channel}>
                    {humanize(channel)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("notifications.workspace")}>
              <input
                value={contactWorkspace}
                maxLength={100}
                onChange={(event) => setContactWorkspace(event.target.value)}
              />
            </Field>
          </div>
          <Field
            label={t("notifications.address")}
            required
            hint={contactChannel === "slack_patient" ? t("notifications.slackMemberIdHint") : undefined}
          >
            <input
              value={contactAddress}
              maxLength={300}
              onChange={(event) => setContactAddress(event.target.value)}
            />
          </Field>
          <Field label={t("common.patient")} hint={t("common.optional")}>
            <PatientPicker value={contactPatient} onChange={setContactPatient} />
          </Field>
          <div className="checkbox-row">
            <label className="check-row inline">
              <input
                type="checkbox"
                checked={contactVerified}
                onChange={(event) => setContactVerified(event.target.checked)}
              />
              <span>{t("notifications.verified")}</span>
            </label>
            <label className="check-row inline">
              <input
                type="checkbox"
                checked={contactOptIn}
                onChange={(event) => setContactOptIn(event.target.checked)}
              />
              <span>{t("notifications.optIn")}</span>
            </label>
          </div>
          <Callout tone="warning">{t("notifications.slackPatient")}</Callout>
          <FormError message={contactError} />
        </div>
      </Modal>
    </>
  );
}
