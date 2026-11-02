import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Cpu, Globe2, Palette, Plug, ShieldCheck, UserRound } from "lucide-react";
import { useState } from "react";

import { Badge } from "../components/Badge";
import { ContactRegistration } from "../components/ContactRegistration";
import { SlackCoverageTile } from "../components/SlackCoverageTile";
import { FormError, PageHeader, Spinner, Stat } from "../components/primitives";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { humanize } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { useTheme, type ThemeMode } from "../lib/theme";
import type { Meta } from "../lib/types";
import type { Locale } from "../i18n/locales";

interface MemoryItem {
  id: string;
  key: string;
  value: string;
  updated_at: string;
}

const ADAPTER_TONES: Record<string, "success" | "warning" | "neutral"> = {
  configured: "success",
  enabled: "success",
  unconfigured: "warning",
  disabled: "neutral",
};

export function SettingsPage() {
  const { t, locale, setLocale, locales } = useI18n();
  const { me, name, email, hasRole } = useAuth();
  const { preference, resolved, setPreference } = useTheme();
  const queryClient = useQueryClient();
  const [memoryKey, setMemoryKey] = useState("preferred_clinic");
  const [memoryValue, setMemoryValue] = useState("");
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoryNotice, setMemoryNotice] = useState<string | null>(null);

  const metaQuery = useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/api/v1/meta"),
    staleTime: 120_000,
  });

  const memoryEnabled = Boolean(metaQuery.data?.capabilities?.memory_preferences);
  const memoryQuery = useQuery({
    queryKey: ["memory"],
    queryFn: () => api<MemoryItem[]>("/api/v1/me/memory"),
    enabled: memoryEnabled,
  });

  const saveMemory = useMutation({
    mutationFn: () =>
      api<MemoryItem>("/api/v1/me/memory", {
        method: "PUT",
        body: { key: memoryKey, value: memoryValue.trim() },
      }),
    onSuccess: () => {
      setMemoryValue("");
      setMemoryError(null);
      void queryClient.invalidateQueries({ queryKey: ["memory"] });
    },
    onError: (error) => setMemoryError(errorMessage(error)),
  });

  const forgetMemory = useMutation({
    mutationFn: (key: string) =>
      api<void>(`/api/v1/me/memory/${encodeURIComponent(key)}`, { method: "DELETE" }),
    onSuccess: () => {
      setMemoryError(null);
      void queryClient.invalidateQueries({ queryKey: ["memory"] });
    },
    onError: (error) => setMemoryError(errorMessage(error)),
  });

  const purgeMemory = useMutation({
    mutationFn: () => api<void>("/api/v1/me/memory/purge", { method: "POST" }),
    onSuccess: () => {
      setMemoryError(null);
      setMemoryNotice(t("settings.purgeMemoryDone"));
      void queryClient.invalidateQueries({ queryKey: ["memory"] });
    },
    onError: (error) => {
      setMemoryNotice(null);
      setMemoryError(errorMessage(error));
    },
  });

  const meta = metaQuery.data;
  const selfService = hasRole("patient") || hasRole("caregiver");
  const clinics = (meta?.clinics ?? []).filter((clinic) => me.clinic_ids.includes(clinic.code));
  const purposeRows = Object.entries(meta?.purposes ?? {});
  const showDemoAccounts = ["local", "dev", "minimal", "full", "acceptance"].includes(
    meta?.app.profile ?? "",
  ) || ["dev", "local", "test"].includes(meta?.app.environment ?? "");
  const demoAccounts = [
    { username: "patient.priya", role: "patient", focus: "Own appointments & records (Priya)" },
    { username: "patient.arjun", role: "patient", focus: "Second patient scenario (Arjun)" },
    { username: "caregiver.meena", role: "caregiver", focus: "Consent-scoped view of Priya" },
    { username: "doctor.rao", role: "doctor", focus: "Dr. Ananya Rao schedule only" },
    { username: "doctor.kulkarni", role: "doctor", focus: "Dr. Vikram Kulkarni schedule only" },
    { username: "frontdesk.imran", role: "front_desk", focus: "Clinic-wide bookings & queue" },
    { username: "pharmacist.kavita", role: "pharmacist", focus: "Pharmacy stock & review" },
    { username: "compliance.auditor", role: "compliance", focus: "Audit & analytics" },
    { username: "admin.ops", role: "admin", focus: "Ops console & config" },
  ];

  return (
    <>
      <PageHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />

      <div className="settings-grid">
        <section className="panel">
          <div className="panel-head">
            <h3>
              <UserRound size={17} aria-hidden="true" /> {t("settings.profile")}
            </h3>
            <Badge tone="info">{humanize(me.primary_role)}</Badge>
          </div>
          <div className="profile-block">
            <div className="avatar" aria-hidden="true">
              {name.slice(0, 1).toUpperCase()}
            </div>
            <div>
              <strong>{name}</strong>
              <p className="muted small">{email ?? t("common.unknown")}</p>
              <code className="mono muted small">{me.subject}</code>
            </div>
          </div>
          <div className="tag-row">
            {me.roles.map((role) => (
              <Badge key={role} tone={role === me.primary_role ? "violet" : "neutral"}>
                {humanize(role)}
              </Badge>
            ))}
          </div>
          <div className="stat-grid">
            <Stat
              label={t("settings.clinics")}
              value={
                clinics.length ? (
                  <span className="tag-row">
                    {clinics.map((clinic) => (
                      <Badge key={clinic.code} tone="neutral">
                        {clinic.name}
                      </Badge>
                    ))}
                  </span>
                ) : (
                  t("shell.noClinic")
                )
              }
            />
            <Stat
              label={t("settings.trafficClass")}
              value={
                <Badge tone={me.traffic_class === "real" ? "success" : "warning"}>
                  {humanize(me.traffic_class)}
                </Badge>
              }
              hint={t("dashboard.syntheticNote")}
            />
          </div>
          {me.clinic_ids.length === 0 ? (
            <p className="muted small">{t("shell.clinicScope")}: {t("shell.noClinic")}</p>
          ) : null}
          {me.preferred_username ? (
            <p className="muted small mono">{me.preferred_username}</p>
          ) : null}
        </section>

        {showDemoAccounts ? (
          <section className="panel" data-testid="demo-accounts">
            <div className="panel-head">
              <h3>
                <ShieldCheck size={17} aria-hidden="true" /> {t("settings.demoAccounts")}
              </h3>
            </div>
            <p className="muted small">{t("settings.demoAccountsHint")}</p>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t("settings.demoUsername")}</th>
                    <th>{t("settings.demoRole")}</th>
                    <th>{t("settings.demoFocus")}</th>
                  </tr>
                </thead>
                <tbody>
                  {demoAccounts.map((account) => (
                    <tr key={account.username}>
                      <td>
                        <code className="mono">{account.username}</code>
                      </td>
                      <td>
                        <Badge tone={account.username === me.preferred_username ? "violet" : "neutral"}>
                          {humanize(account.role)}
                        </Badge>
                      </td>
                      <td className="muted small">{account.focus}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}

        <section className="panel">
          <div className="panel-head">
            <h3>
              <Palette size={17} aria-hidden="true" /> {t("settings.themePref")}
            </h3>
          </div>
          <div className="preference-list">
            <label className="field">
              <span className="field-label">{t("settings.localePref")}</span>
              <select
                value={locale}
                onChange={(event) => setLocale(event.target.value as Locale)}
              >
                {locales.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">{t("settings.themePref")}</span>
              <select
                value={preference}
                onChange={(event) => setPreference(event.target.value as ThemeMode)}
              >
                <option value="system">{t("settings.system")}</option>
                <option value="light">{t("settings.light")}</option>
                <option value="dark">{t("settings.dark")}</option>
              </select>
              <span className="field-hint">
                {t("settings.themePref")}: {humanize(resolved)}
              </span>
            </label>
          </div>
        </section>

        {memoryEnabled ? (
          <section className="panel" data-testid="memory-preferences">
            <div className="panel-head">
              <h3>
                <Globe2 size={17} aria-hidden="true" /> Preferences
              </h3>
            </div>
            <p className="muted small" role="note">
              Preference memory is not clinical evidence. Values are non-clinical only; use Forget to
              purge. Opt-out stops Mem0 sync.
            </p>
            <div className="preference-list">
              <label className="field">
                <span className="field-label">Key</span>
                <select value={memoryKey} onChange={(event) => setMemoryKey(event.target.value)}>
                  <option value="preferred_locale">preferred_locale</option>
                  <option value="preferred_clinic">preferred_clinic</option>
                  <option value="preferred_channel">preferred_channel</option>
                  <option value="appointment_reminder">appointment_reminder</option>
                  <option value="ui_density">ui_density</option>
                  <option value="opt_out">opt_out</option>
                </select>
              </label>
              <label className="field">
                <span className="field-label">Value</span>
                <input
                  value={memoryValue}
                  onChange={(event) => setMemoryValue(event.target.value)}
                  maxLength={500}
                />
              </label>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!memoryValue.trim() || saveMemory.isPending}
                onClick={() => saveMemory.mutate()}
              >
                Save preference
              </button>
            </div>
            {memoryError ? <FormError message={memoryError} /> : null}
            {memoryNotice ? (
              <p className="muted small" role="status">
                {memoryNotice}
              </p>
            ) : null}
            <ul className="muted small" style={{ marginTop: 12 }}>
              {(memoryQuery.data ?? []).map((item) => (
                <li key={item.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span>
                    <code>{item.key}</code>: {item.value}
                  </span>
                  <button
                    type="button"
                    className="btn"
                    disabled={forgetMemory.isPending}
                    onClick={() => forgetMemory.mutate(item.key)}
                  >
                    Forget
                  </button>
                </li>
              ))}
            </ul>
            <p className="muted small">{t("settings.memoryRetentionNote")}</p>
            <button
              type="button"
              className="btn btn-danger"
              data-testid="purge-memory"
              disabled={purgeMemory.isPending}
              onClick={() => {
                if (window.confirm(t("settings.purgeMemoryConfirm"))) purgeMemory.mutate();
              }}
            >
              {purgeMemory.isPending ? <Spinner /> : null}
              {t("settings.purgeMemory")}
            </button>
          </section>
        ) : null}
        {selfService ? (
          <ContactRegistration adapters={meta?.adapters} environment={meta?.app.environment} />
        ) : null}
        {hasRole("admin") ? <SlackCoverageTile /> : null}
      </div>

      <section className="panel">
        <div className="panel-head">
          <h3>
            <Building2 size={17} aria-hidden="true" /> {t("settings.about")}
          </h3>
          {meta?.app.version ? <Badge tone="neutral">v{meta.app.version}</Badge> : null}
        </div>
        {metaQuery.isPending ? (
          <Spinner />
        ) : metaQuery.isError ? (
          <FormError message={errorMessage(metaQuery.error)} />
        ) : meta ? (
          <>
            <dl className="definition-list">
              <div className="definition-row">
                <dt>{t("settings.version")}</dt>
                <dd>{meta.app.version}</dd>
              </div>
              <div className="definition-row">
                <dt>{t("settings.environment")}</dt>
                <dd>
                  <Badge tone={meta.app.environment === "production" ? "success" : "warning"}>
                    {meta.app.environment}
                  </Badge>
                  <span className="muted small"> · {meta.app.profile}</span>
                </dd>
              </div>
              <div className="definition-row">
                <dt>{t("settings.defaultLocale")}</dt>
                <dd>{meta.app.default_locale}</dd>
              </div>
              <div className="definition-row">
                <dt>{t("settings.supportedLocales")}</dt>
                <dd>{meta.app.locales.join(" · ")}</dd>
              </div>
              <div className="definition-row">
                <dt>{t("settings.timezone")}</dt>
                <dd>{meta.app.timezone ?? "Asia/Kolkata"}</dd>
              </div>
            </dl>
            <div className="callout callout-info">
              <strong className="callout-title">
                <ShieldCheck size={15} aria-hidden="true" /> {t("settings.noPhi")}
              </strong>
              <div>{meta.disclaimer}</div>
            </div>
          </>
        ) : null}
      </section>

      <div className="settings-grid">
        <section className="panel">
          <div className="panel-head">
            <h3>
              <Plug size={17} aria-hidden="true" /> {t("settings.integrations")}
            </h3>
          </div>
          <p className="muted small">{t("settings.adaptersHint")}</p>
          <ul className="plain-list">
            {Object.entries(meta?.adapters ?? {}).map(([key, adapter]) => (
              <li key={key}>
                <div>
                  <strong>{humanize(key)}</strong>
                  <span className="muted small">
                    {" "}
                    · {adapter.adapter}
                    {adapter.mode ? ` · ${adapter.mode}` : ""}
                  </span>
                </div>
                <span>
                  {adapter.certified === false ? (
                    <Badge tone="warning">{t("settings.notCertified")}</Badge>
                  ) : null}{" "}
                  <Badge tone={ADAPTER_TONES[adapter.status] ?? "neutral"}>
                    {humanize(adapter.status)}
                  </Badge>
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h3>
              <Cpu size={17} aria-hidden="true" /> {t("settings.capabilities")}
            </h3>
          </div>
          <p className="muted small">{t("settings.capabilitiesHint")}</p>
          <ul className="plain-list">
            {Object.entries(meta?.capabilities ?? {}).map(([key, enabled]) => (
              <li key={key}>
                <span>{humanize(key)}</span>
                <Badge tone={enabled ? "success" : "neutral"}>
                  {enabled ? t("dashboard.configured") : t("dashboard.disabled")}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h3>
            <Globe2 size={17} aria-hidden="true" /> {t("settings.purposes")}
          </h3>
          <span className="muted small">{t("settings.purposesHint")}</span>
        </div>
        <div className="table-wrap">
          <table className="data-table compact">
            <thead>
              <tr>
                <th>{t("settings.purposes")}</th>
                <th>{t("settings.purposeAlias")}</th>
                <th>{t("settings.purposeEgress")}</th>
              </tr>
            </thead>
            <tbody>
              {purposeRows.map(([purpose, config]) => (
                <tr key={purpose}>
                  <td>
                    <strong>{humanize(purpose)}</strong>
                  </td>
                  <td>
                    <code className="mono">{config.alias ?? "—"}</code>
                  </td>
                  <td>
                    <Badge
                      tone={
                        config.egress === "external"
                          ? "warning"
                          : config.egress === "local"
                            ? "success"
                            : "neutral"
                      }
                    >
                      {humanize(config.egress ?? "unknown")}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
