import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Bell,
  CalendarDays,
  CalendarPlus,
  FolderUp,
  MessageCircle,
  Mic,
  ShieldAlert,
  Users,
} from "lucide-react";
import { Link } from "react-router-dom";

import { api, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, humanize, truncate } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type {
  Appointment,
  GridResponse,
  Meta,
  NotificationRow,
  OverviewResponse,
} from "../lib/types";
import { Badge, StatusBadge } from "../components/Badge";
import { MetricTiles } from "../components/MetricTiles";
import { RoleActivityChart } from "../components/RoleActivityChart";
import { Callout, EmptyState, PageHeader } from "../components/primitives";
import type { GridMeta } from "../lib/types";

interface UnreadPeek {
  items: NotificationRow[];
  meta: GridMeta;
}

function clinicToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export function DashboardPage() {
  const { me, name, hasRole } = useAuth();
  const { t, locale } = useI18n();
  const isAnalytics = hasRole("admin", "compliance");
  const canChat = hasRole("patient", "caregiver", "doctor", "front_desk", "admin");
  const canSchedule = hasRole("patient", "caregiver", "doctor", "front_desk", "admin");
  const canBook = hasRole("front_desk", "admin");
  const canUsePatients = hasRole("front_desk", "doctor", "compliance", "admin");
  const canUseRecords = hasRole("patient", "caregiver", "doctor", "front_desk", "admin");
  const isDoctor = hasRole("doctor");
  const isPatientView = hasRole("patient", "caregiver");
  const isFrontDesk = hasRole("front_desk");
  const isPharmacist = hasRole("pharmacist");
  const isCompliance = hasRole("compliance");

  const subtitle = isDoctor
    ? t("dashboard.subtitleDoctor")
    : isPatientView
      ? t("dashboard.subtitlePatient")
      : isFrontDesk
        ? t("dashboard.subtitleFrontDesk")
        : isPharmacist
          ? t("dashboard.subtitlePharmacist")
          : isCompliance
            ? t("dashboard.subtitleCompliance")
            : t("dashboard.subtitle");

  const metaQuery = useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/api/v1/meta"),
    staleTime: 5 * 60_000,
  });

  const appointmentsQuery = useQuery({
    queryKey: ["dashboard", "appointments"],
    queryFn: () =>
      api<GridResponse<Appointment>>(
        `/api/v1/appointments${qs({
          page_size: 5,
          sort: "starts_at",
          order: "asc",
          date_from: clinicToday(),
        })}`,
      ),
    enabled: canSchedule,
    staleTime: 30_000,
  });

  const notificationsQuery = useQuery({
    queryKey: ["dashboard", "notifications", me.subject],
    queryFn: () =>
      api<UnreadPeek>(`/api/v1/notifications${qs({ page_size: 5, sort: "created_at", order: "desc" })}`),
    staleTime: 30_000,
  });

  const overviewQuery = useQuery({
    queryKey: ["analytics", "overview", 30],
    queryFn: () => api<OverviewResponse>("/api/v1/analytics/overview?days=30"),
    enabled: isAnalytics,
  });

  const unread = notificationsQuery.data?.items.filter((item) => item.status !== "read").length ?? 0;
  const firstName = name.split(" ")[0];
  const app = metaQuery.data?.app;

  const quickActions = [
    canChat
      ? { to: "/chat", icon: MessageCircle, label: t("dashboard.newChat") }
      : null,
    canBook
      ? { to: "/appointments", icon: CalendarPlus, label: t("dashboard.bookAppointment") }
      : canSchedule
        ? { to: "/appointments", icon: CalendarDays, label: t("nav.appointments") }
        : null,
    canUseRecords
      ? { to: "/records", icon: FolderUp, label: t("dashboard.uploadRecord") }
      : null,
    isDoctor ? { to: "/scribe", icon: Mic, label: t("dashboard.openScribe") } : null,
    canUsePatients ? { to: "/patients", icon: Users, label: t("nav.patients") } : null,
    isAnalytics ? { to: "/analytics", icon: BarChart3, label: t("nav.analytics") } : null,
  ].filter((item): item is { to: string; icon: typeof MessageCircle; label: string } => item !== null);

  const roles = overviewQuery.data?.active_users_by_role ?? [];

  return (
    <div className="page">
      <PageHeader
        title={t("dashboard.greeting", { name: firstName })}
        subtitle={subtitle}
        actions={
          canBook ? (
            <Link className="btn btn-primary" to="/appointments">
              <CalendarPlus size={16} aria-hidden="true" /> {t("dashboard.bookAppointment")}
            </Link>
          ) : isDoctor ? (
            <Link className="btn btn-primary" to="/appointments">
              <CalendarDays size={16} aria-hidden="true" /> {t("dashboard.mySchedule")}
            </Link>
          ) : canChat ? (
            <Link className="btn btn-primary" to="/chat">
              <MessageCircle size={16} aria-hidden="true" /> {t("dashboard.newChat")}
            </Link>
          ) : null
        }
      />

      <section className="quick-actions" aria-label={t("dashboard.quickActions")}>
        {quickActions.map((action) => (
          <Link key={action.to} to={action.to} className="quick-action">
            <span className="quick-action-icon">
              <action.icon size={19} aria-hidden="true" />
            </span>
            <span>{action.label}</span>
          </Link>
        ))}
      </section>

      {isAnalytics && overviewQuery.data ? (
        <section className="section">
          <div className="section-head">
            <h2>{t("dashboard.overview")}</h2>
            <Link to="/analytics" className="link">
              {t("dashboard.viewAll")}
            </Link>
          </div>
          <MetricTiles tiles={overviewQuery.data.tiles} />
          {roles.length ? (
            <div className="panel role-activity">
              <RoleActivityChart rows={roles} title={t("analytics.activeByRole")} />
              <p className="muted small">
                {t("analytics.suppressed")} · {t("dashboard.syntheticNote")}
              </p>
            </div>
          ) : null}
        </section>
      ) : null}

      <div className="dashboard-columns">
        {canSchedule ? (
          <section className="panel">
            <div className="section-head">
              <h2>{isDoctor ? t("dashboard.mySchedule") : t("dashboard.upcomingAppointments")}</h2>
              <Link to="/appointments" className="link">
                {t("dashboard.viewAll")}
              </Link>
            </div>
            {appointmentsQuery.isPending ? (
              <div className="mini-loading">{t("common.loading")}</div>
            ) : appointmentsQuery.isError ? (
              <p className="muted">{t("common.errorTitle")}</p>
            ) : !appointmentsQuery.data?.items.length ? (
              <EmptyState title={t("dashboard.noUpcoming")} />
            ) : (
              <ul className="mini-list">
                {appointmentsQuery.data.items.map((appointment) => (
                  <li key={appointment.id} className="mini-row">
                    <span className="mini-when">
                      {formatDateTime(appointment.starts_at, locale, app?.timezone)}
                    </span>
                    <span className="mini-main">
                      <strong>
                        {isDoctor
                          ? (appointment.specialty_label ?? humanize(appointment.specialty_code))
                          : appointment.doctor_name}
                      </strong>
                      <span className="muted">
                        {isDoctor
                          ? appointment.clinic_code
                          : `${appointment.specialty_label ?? humanize(appointment.specialty_code)} · ${appointment.clinic_code}`}
                      </span>
                    </span>
                    <StatusBadge status={appointment.status} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        ) : null}

        <section className="panel">
          <div className="section-head">
            <h2>
              {t("dashboard.recentNotifications")}
              {unread > 0 ? <span className="count-pill">{unread}</span> : null}
            </h2>
            <Link to="/notifications" className="link">
              {t("dashboard.viewAll")}
            </Link>
          </div>
          {notificationsQuery.isPending ? (
            <div className="mini-loading">{t("common.loading")}</div>
          ) : notificationsQuery.isError ? (
            <p className="muted">{t("common.errorTitle")}</p>
          ) : !notificationsQuery.data?.items.length ? (
            <EmptyState title={t("dashboard.noNotifications")} />
          ) : (
            <ul className="mini-list">
              {notificationsQuery.data.items.map((item) => (
                <li key={item.id} className="mini-row">
                  <span className="mini-icon">
                    <Bell size={15} aria-hidden="true" />
                  </span>
                  <span className="mini-main">
                    <strong className={item.status === "read" ? "" : "unread-title"}>
                      {item.title}
                    </strong>
                    <span className="muted">{truncate(item.body, 90)}</span>
                  </span>
                  <span className="mini-time muted">
                    {formatDateTime(item.created_at, locale, app?.timezone)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="dashboard-columns">
        <section className="panel">
          <div className="section-head">
            <h2>{t("dashboard.platformStatus")}</h2>
            <Badge tone="violet">{app?.profile ?? me.traffic_class}</Badge>
          </div>
          <div className="status-grid">
            {Object.entries(metaQuery.data?.adapters ?? {}).map(([key, value]) => (
              <div className="status-row" key={key}>
                <span>
                  {humanize(key)} <span className="muted small">{value.adapter}</span>
                </span>
                <StatusBadge status={value.status} />
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="section-head">
            <h2>{t("dashboard.capabilities")}</h2>
            <span className="muted small">{app?.environment}</span>
          </div>
          <div className="status-grid">
            {Object.entries(metaQuery.data?.features ?? {}).map(([key, flag]) => (
              <div className="status-row" key={key}>
                <span>{humanize(key)}</span>
                <div className="status-inline">
                  <Badge tone={flag.class === "locked" ? "danger" : "neutral"}>
                    {humanize(flag.class)}
                  </Badge>
                  <StatusBadge status={flag.value ? "enabled" : "disabled"} />
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      {metaQuery.data?.capabilities?.dpdp_processing_allowed === false ? (
        <Callout tone="danger" title={t("admin.dpdpStopped")}>
          {t("admin.dpdpStopped")}
        </Callout>
      ) : null}
      {metaQuery.data?.capabilities?.clinically_validated != null ? (
        <Callout
          tone={metaQuery.data.capabilities.clinically_validated ? "success" : "warning"}
          title={t("dashboard.disclaimer")}
        >
          <span className="inline-icon">
            <ShieldAlert size={15} aria-hidden="true" />
          </span>
          {metaQuery.data.capabilities.clinically_validated
            ? `${t("admin.attested")} (${t("admin.notRegulatory")})`
            : t("admin.notAttested")}
        </Callout>
      ) : null}
    </div>
  );
}
