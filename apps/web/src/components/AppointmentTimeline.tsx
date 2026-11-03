import { ChevronLeft, ChevronRight, Eye, Search, X, XCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { errorMessage } from "../lib/api";
import { intlLocale } from "../lib/format";
import type { GridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type { Appointment, GridMeta } from "../lib/types";
import { Badge, StatusBadge } from "./Badge";
import { IconButton } from "./IconButton";
import { EmptyState, ErrorState } from "./primitives";

const PAGE_SIZES = [10, 20, 50, 100];

function clinicDayKey(iso: string, timeZone: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function addCalendarDays(dayKey: string, days: number): string {
  const [year, month, day] = dayKey.split("-").map(Number);
  if (!year || !month || !day) return dayKey;
  const date = new Date(Date.UTC(year, month - 1, day + days));
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, "0");
  const d = String(date.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function formatClock(iso: string, locale: string, timeZone: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(intlLocale(locale), {
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  }).format(date);
}

function formatDay(iso: string, locale: string, timeZone: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(intlLocale(locale), {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone,
  }).format(date);
}

function endIso(iso: string, minutes: number): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Date(date.getTime() + minutes * 60_000).toISOString();
}

export function AppointmentTimeline({
  items,
  meta,
  loading,
  error,
  grid,
  locale,
  timezone,
  filters,
  searchPlaceholder,
  showPatient,
  showDoctor,
  showSource,
  canCancel,
  specialtyLabel,
  onOpen,
  onCancel,
  onRetry,
  emptyTitle,
  emptyHint,
}: {
  items: Appointment[] | undefined;
  meta: GridMeta | null | undefined;
  loading: boolean;
  error: unknown;
  grid: GridState;
  locale: string;
  timezone: string;
  filters?: ReactNode;
  searchPlaceholder?: string;
  showPatient: boolean;
  showDoctor: boolean;
  showSource: boolean;
  canCancel: (appointment: Appointment) => boolean;
  specialtyLabel: (code: string) => string;
  onOpen: (appointment: Appointment) => void;
  onCancel: (appointment: Appointment) => void;
  onRetry?: () => void;
  emptyTitle?: string;
  emptyHint?: string;
}) {
  const { t } = useI18n();
  const [search, setSearch] = useState(grid.query);
  const editingSearch = useRef(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (search !== grid.query) grid.setQuery(search);
      editingSearch.current = false;
    }, 300);
    return () => window.clearTimeout(timer);
    // Push local typing into grid state; omit grid so a parent render does not reset the timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  useEffect(() => {
    if (!editingSearch.current) setSearch(grid.query);
  }, [grid.query]);

  const todayKey = clinicDayKey(new Date().toISOString(), timezone);
  const tomorrowKey = addCalendarDays(todayKey, 1);

  const groups = useMemo(() => {
    const map = new Map<string, Appointment[]>();
    for (const item of items ?? []) {
      const key = clinicDayKey(item.starts_at, timezone) || item.starts_at;
      const list = map.get(key) ?? [];
      list.push(item);
      map.set(key, list);
    }
    return Array.from(map.entries());
  }, [items, timezone]);

  const total = meta?.total ?? 0;
  const pages = meta?.pages ?? 0;
  const page = meta?.page ?? grid.page;
  const pageSize = meta?.page_size ?? grid.pageSize;
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  const busy = loading && !items;
  const failed = Boolean(error) && !items;

  return (
    <section className="grid-panel" aria-busy={loading} data-testid="appointment-timeline">
      <div className="grid-toolbar">
        <div className="search-box">
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            value={search}
            onChange={(event) => {
              editingSearch.current = true;
              setSearch(event.target.value);
            }}
            placeholder={searchPlaceholder ?? t("common.searchPlaceholder")}
            aria-label={searchPlaceholder ?? t("common.search")}
            maxLength={120}
          />
          {search ? (
            <button
              type="button"
              className="search-clear"
              aria-label={t("common.clear")}
              onClick={() => {
                editingSearch.current = false;
                setSearch("");
                grid.setQuery("");
              }}
            >
              <X size={14} aria-hidden="true" />
            </button>
          ) : null}
        </div>
        <div className="grid-toolbar-actions">
          <label className="page-size">
            <select
              value={grid.order}
              aria-label={
                grid.order === "asc" ? t("appointments.orderSoonest") : t("appointments.orderLatest")
              }
              onChange={(event) => grid.setOrder(event.target.value === "desc" ? "desc" : "asc")}
            >
              <option value="asc">{t("appointments.orderSoonest")}</option>
              <option value="desc">{t("appointments.orderLatest")}</option>
            </select>
          </label>
        </div>
      </div>

      {filters ? <div className="appt-filters">{filters}</div> : null}

      {failed ? (
        <ErrorState
          message={errorMessage(error) || t("common.errorTitle")}
          onRetry={onRetry}
          retryLabel={t("common.retry")}
        />
      ) : busy ? (
        <div className="appt-skeleton" aria-hidden="true">
          {Array.from({ length: 3 }).map((_, index) => (
            <span key={index} className="skeleton appt-skeleton-bar" />
          ))}
        </div>
      ) : !items || items.length === 0 ? (
        <EmptyState title={emptyTitle ?? t("common.emptyTitle")} hint={emptyHint ?? t("common.emptyHint")} />
      ) : (
        <div className="appt-timeline">
          {groups.map(([day, dayItems]) => {
            const kicker =
              day === todayKey
                ? t("appointments.today")
                : day === tomorrowKey
                  ? t("appointments.tomorrow")
                  : null;
            return (
              <section key={day} className={`appt-day ${day === todayKey ? "is-today" : ""}`}>
                <header className="appt-day-label">
                  {kicker ? <span className="appt-day-kicker">{kicker}</span> : null}
                  <h3>{formatDay(dayItems[0].starts_at, locale, timezone)}</h3>
                  <span className="appt-day-count">{dayItems.length}</span>
                </header>
                <ol className="appt-rail">
                  {dayItems.map((item) => {
                    const specialty = item.specialty_label ?? specialtyLabel(item.specialty_code);
                    const title = showPatient
                      ? (item.patient_display_name ?? t("common.unknown"))
                      : item.doctor_name;
                    const subtitle = [showPatient && showDoctor ? item.doctor_name : null, specialty]
                      .filter(Boolean)
                      .join(" · ");
                    const finish = endIso(item.starts_at, item.duration_minutes);
                    return (
                      <li
                        key={item.id}
                        className="appt-item"
                        data-status={item.status}
                        data-testid="appointment-timeline-item"
                      >
                        <time className="appt-time" dateTime={item.starts_at}>
                          <strong>{formatClock(item.starts_at, locale, timezone)}</strong>
                          <span>{formatClock(finish, locale, timezone)}</span>
                        </time>
                        <span className="appt-dot" aria-hidden="true" />
                        <div className="appt-card">
                          <button type="button" className="appt-card-open" onClick={() => onOpen(item)}>
                            <span className="appt-card-title">
                              <strong>{title}</strong>
                              <StatusBadge status={item.status} />
                            </span>
                            {subtitle ? <span className="muted small">{subtitle}</span> : null}
                            <span className="tag-row">
                              <Badge tone="neutral">{item.clinic_code}</Badge>
                              <span className="muted small">
                                {item.duration_minutes} {t("appointments.minutes")}
                              </span>
                              {showSource ? (
                                <Badge tone={item.source === "assistant" ? "info" : "neutral"}>
                                  {item.source === "assistant"
                                    ? t("appointments.sourceAssistant")
                                    : t("appointments.sourceFrontDesk")}
                                </Badge>
                              ) : null}
                              {showPatient && item.visit_kind === "first" ? (
                                <Badge tone="info">{t("appointments.visitFirst")}</Badge>
                              ) : null}
                              {showPatient && item.visit_kind === "repeat" ? (
                                <Badge tone="neutral">{t("appointments.visitRepeat")}</Badge>
                              ) : null}
                              {item.no_show_band ? (
                                <Badge
                                  tone={
                                    item.no_show_band === "high"
                                      ? "danger"
                                      : item.no_show_band === "medium"
                                        ? "warning"
                                        : "neutral"
                                  }
                                >
                                  {t("appointments.noShowRisk")}: {item.no_show_band}
                                  {typeof item.no_show_risk === "number"
                                    ? ` (${Math.round(item.no_show_risk * 100)}%)`
                                    : ""}
                                </Badge>
                              ) : null}
                              {item.waitlist_suggested ? (
                                <Badge tone="warning">{t("appointments.waitlistSuggested")}</Badge>
                              ) : null}
                              {item.confirm_by_reply ? (
                                <Badge tone="info">{t("appointments.confirmByReply")}</Badge>
                              ) : null}
                            </span>
                          </button>
                          <div className="appt-card-actions">
                            <IconButton label={t("common.details")} onClick={() => onOpen(item)} icon={<Eye size={15} />} />
                            {canCancel(item) ? (
                              <IconButton
                                label={t("appointments.cancelAppointment")}
                                tone="danger"
                                icon={<XCircle size={15} />}
                                onClick={() => onCancel(item)}
                              />
                            ) : null}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </section>
            );
          })}
        </div>
      )}

      <footer className="grid-footer">
        <div className="grid-count muted">
          {total === 0
            ? t("common.emptyTitle")
            : `${first}–${last} ${t("common.of")} ${total} ${t("common.rows")}`}
        </div>
        <div className="grid-pager">
          <label className="page-size">
            <span>{t("common.pageSize")}</span>
            <select
              value={grid.pageSize}
              onChange={(event) => grid.setPageSize(Number(event.target.value))}
              aria-label={t("common.pageSize")}
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
          <span className="muted">
            {t("common.page")} {page} {t("common.of")} {Math.max(pages, 1)}
          </span>
          <IconButton
            label={t("common.previous")}
            icon={<ChevronLeft size={16} />}
            disabled={page <= 1 || loading}
            onClick={() => grid.setPage(page - 1)}
          />
          <IconButton
            label={t("common.next")}
            icon={<ChevronRight size={16} />}
            disabled={page >= pages || loading || pages === 0}
            onClick={() => grid.setPage(page + 1)}
          />
        </div>
      </footer>
    </section>
  );
}
