import { useQuery } from "@tanstack/react-query";
import { CalendarDays, ListChecks, Siren, Users } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, StatusBadge } from "../components/Badge";
import { Callout, EmptyState, PageHeader, Spinner } from "../components/primitives";
import { api, errorMessage, qs } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { Appointment, GridResponse, WaitlistItem } from "../lib/types";

interface HandoffRow {
  id: string;
  reason: string;
  status: "open" | "assigned" | "resolved";
  priority?: "normal" | "urgent" | "emergency";
  clinic_code: string;
  sla_due_at?: string | null;
  overdue?: boolean;
  created_at: string;
}

function clinicToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

/** Staff ops console: live handoffs, waitlist claims, and assistant bookings. */
export function FrontDeskPage() {
  const { t, locale } = useI18n();

  const handoffsQuery = useQuery({
    queryKey: ["front-desk", "handoffs"],
    queryFn: () =>
      api<GridResponse<HandoffRow>>(
        `/api/v1/handoffs${qs({
          page_size: 8,
          sort: "created_at",
          order: "desc",
          status: "open",
        })}`,
      ),
    refetchInterval: 15_000,
  });

  const assignedQuery = useQuery({
    queryKey: ["front-desk", "handoffs-assigned"],
    queryFn: () =>
      api<GridResponse<HandoffRow>>(
        `/api/v1/handoffs${qs({
          page_size: 8,
          sort: "created_at",
          order: "desc",
          status: "assigned",
        })}`,
      ),
    refetchInterval: 15_000,
  });

  const waitlistQuery = useQuery({
    queryKey: ["front-desk", "waitlist"],
    queryFn: () =>
      api<GridResponse<WaitlistItem>>(
        `/api/v1/waitlist${qs({
          page_size: 6,
          sort: "starts_at",
          order: "asc",
          status: "active",
        })}`,
      ),
    refetchInterval: 20_000,
  });

  const assistantBookingsQuery = useQuery({
    queryKey: ["front-desk", "assistant-bookings"],
    queryFn: () =>
      api<GridResponse<Appointment>>(
        `/api/v1/appointments${qs({
          page_size: 8,
          sort: "created_at",
          order: "desc",
          source: "assistant",
          date_from: clinicToday(),
        })}`,
      ),
    refetchInterval: 20_000,
  });

  const openHandoffs = [
    ...(handoffsQuery.data?.items ?? []),
    ...(assignedQuery.data?.items ?? []),
  ].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  const overdueCount = openHandoffs.filter((row) => row.overdue).length;
  const assistantBookings = assistantBookingsQuery.data?.items ?? [];
  const waitlistItems = waitlistQuery.data?.items ?? [];
  const waitlistOpen = waitlistItems.filter((row) => row.waitlist_status === "open").length;

  return (
    <div className="page">
      <PageHeader title={t("frontDesk.title")} subtitle={t("frontDesk.subtitle")} />

      <div className="stat-grid" data-testid="front-desk-stats">
        <div className="stat">
          <span className="stat-label">{t("frontDesk.openHandoffs")}</span>
          <span className="stat-value">
            {handoffsQuery.isLoading ? "…" : openHandoffs.length}
          </span>
          <span className="stat-hint">{t("frontDesk.slaHint")}</span>
        </div>
        <div className="stat">
          <span className="stat-label">{t("frontDesk.overdue")}</span>
          <span className="stat-value">{handoffsQuery.isLoading ? "…" : overdueCount}</span>
          <span className="stat-hint">{t("frontDesk.overdueHint")}</span>
        </div>
        <div className="stat waitlist-stat">
          <span className="stat-label">{t("frontDesk.waitlistOpen")}</span>
          <span className="stat-value">
            {waitlistQuery.isLoading ? "…" : waitlistQuery.data?.meta.total ?? waitlistOpen}
          </span>
          <span className="stat-hint">{t("frontDesk.waitlistHint")}</span>
        </div>
        <div className="stat">
          <span className="stat-label">{t("frontDesk.assistantBookings")}</span>
          <span className="stat-value">
            {assistantBookingsQuery.isLoading ? "…" : assistantBookings.length}
          </span>
          <span className="stat-hint">{t("frontDesk.assistantBookingsHint")}</span>
        </div>
      </div>

      <div className="card-grid" style={{ marginTop: 16 }}>
        <Link to="/waitlist" className="panel link-card link-card-accent" data-testid="front-desk-waitlist-link">
          <ListChecks size={20} aria-hidden="true" />
          <strong>{t("nav.waitlist")}</strong>
          <span className="muted small">{t("frontDesk.waitlistCardHint")}</span>
        </Link>
        <Link to="/appointments" className="panel link-card">
          <CalendarDays size={20} aria-hidden="true" />
          <strong>{t("nav.appointments")}</strong>
          <span className="muted small">{t("frontDesk.appointmentsHint")}</span>
        </Link>
        <Link to="/escalations" className="panel link-card">
          <Siren size={20} aria-hidden="true" />
          <strong>{t("nav.escalations")}</strong>
          <span className="muted small">{t("frontDesk.escalationsHint")}</span>
        </Link>
        <Link to="/patients" className="panel link-card">
          <Users size={20} aria-hidden="true" />
          <strong>{t("nav.patients")}</strong>
          <span className="muted small">{t("frontDesk.patientsHint")}</span>
        </Link>
      </div>

      <div className="front-desk-columns front-desk-columns-3" style={{ marginTop: 18 }}>
        <section className="panel stack" data-testid="front-desk-handoffs">
          <header className="panel-head">
            <h3>{t("frontDesk.liveHandoffs")}</h3>
            <Link to="/escalations" className="link">
              {t("dashboard.viewAll")}
            </Link>
          </header>
          {handoffsQuery.isError ? (
            <Callout tone="danger">{errorMessage(handoffsQuery.error)}</Callout>
          ) : null}
          {handoffsQuery.isFetching && !openHandoffs.length ? <Spinner /> : null}
          {!handoffsQuery.isFetching && openHandoffs.length === 0 ? (
            <EmptyState title={t("frontDesk.noHandoffs")} />
          ) : null}
          <ul className="plain-list">
            {openHandoffs.slice(0, 8).map((row) => (
              <li key={row.id}>
                <div className="cell-stack">
                  <strong>{row.reason}</strong>
                  <span className="muted small">
                    {row.clinic_code} · {formatDateTime(row.created_at, locale)}
                  </span>
                </div>
                <div className="badge-row">
                  <StatusBadge status={row.status} />
                  {row.priority ? (
                    <Badge tone={row.priority === "emergency" ? "danger" : "warning"}>
                      {row.priority}
                    </Badge>
                  ) : null}
                  {row.overdue ? <Badge tone="danger">{t("frontDesk.overdue")}</Badge> : null}
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel stack waitlist-panel" data-testid="front-desk-waitlist">
          <header className="panel-head">
            <h3>{t("frontDesk.liveWaitlist")}</h3>
            <Link to="/waitlist" className="link">
              {t("dashboard.viewAll")}
            </Link>
          </header>
          {waitlistQuery.isError ? (
            <Callout tone="danger">{errorMessage(waitlistQuery.error)}</Callout>
          ) : null}
          {waitlistQuery.isFetching && !waitlistItems.length ? <Spinner /> : null}
          {!waitlistQuery.isFetching && waitlistItems.length === 0 ? (
            <EmptyState title={t("frontDesk.noWaitlist")} />
          ) : null}
          <ul className="plain-list">
            {waitlistItems.map((row) => (
              <li key={row.id}>
                <div className="cell-stack">
                  <strong>{row.doctor_name}</strong>
                  <span className="muted small">
                    {row.clinic_code} · {formatDateTime(row.starts_at, locale)}
                  </span>
                </div>
                <div className="badge-row">
                  <StatusBadge status={row.waitlist_status ?? "open"} />
                  <Badge tone="danger">
                    {row.no_show_band ?? "high"}
                    {typeof row.no_show_risk === "number"
                      ? ` ${Math.round(row.no_show_risk * 100)}%`
                      : ""}
                  </Badge>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel stack" data-testid="front-desk-bookings">
          <header className="panel-head">
            <h3>{t("frontDesk.liveBookings")}</h3>
            <Link to="/appointments" className="link">
              {t("dashboard.viewAll")}
            </Link>
          </header>
          {assistantBookingsQuery.isError ? (
            <Callout tone="danger">{errorMessage(assistantBookingsQuery.error)}</Callout>
          ) : null}
          {assistantBookingsQuery.isFetching && !assistantBookings.length ? <Spinner /> : null}
          {!assistantBookingsQuery.isFetching && assistantBookings.length === 0 ? (
            <EmptyState title={t("frontDesk.noBookings")} />
          ) : null}
          <ul className="plain-list">
            {assistantBookings.map((row) => (
              <li key={row.id}>
                <div className="cell-stack">
                  <strong>{row.doctor_name}</strong>
                  <span className="muted small">
                    {row.clinic_code} · {formatDateTime(row.starts_at, locale)}
                  </span>
                </div>
                <div className="badge-row">
                  <StatusBadge status={row.status} />
                  <Badge tone="info">{t("appointments.sourceAssistant")}</Badge>
                  {row.waitlist_suggested ? (
                    <Badge tone="warning">{t("appointments.waitlistSuggested")}</Badge>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
