import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Eye, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge, StatusBadge } from "../components/Badge";
import { ConfirmDialog } from "../components/ConfirmDialog";
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
} from "../components/primitives";
import { api, errorMessage, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDate, formatDateTime, humanize } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type {
  Appointment,
  Doctor,
  GridResponse,
  Meta,
  Patient,
  SlotsResponse,
} from "../lib/types";

const STATUSES = ["held", "confirmed", "completed", "cancelled"] as const;

function localeKey(locale: string): "en" | "hi" | "mr" {
  if (locale.startsWith("hi")) return "hi";
  if (locale.startsWith("mr")) return "mr";
  return "en";
}

export function AppointmentsPage() {
  const { t, locale } = useI18n();
  const { me, hasRole } = useAuth();
  const queryClient = useQueryClient();
  const grid = useGridState("starts_at", "asc");
  const [statusFilter, setStatusFilter] = useState("");
  const [specialtyFilter, setSpecialtyFilter] = useState("");
  const [clinicFilter, setClinicFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [success, setSuccess] = useState<string | null>(null);

  const [detailId, setDetailId] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Appointment | null>(null);
  const [overrideTarget, setOverrideTarget] = useState<Appointment | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [rescheduleTarget, setRescheduleTarget] = useState<Appointment | null>(null);
  const [rescheduleSlot, setRescheduleSlot] = useState("");
  const [rescheduleDuration, setRescheduleDuration] = useState(20);
  const [actionError, setActionError] = useState<string | null>(null);

  const [bookOpen, setBookOpen] = useState(false);
  const [patient, setPatient] = useState<Patient | null>(null);
  const [clinic, setClinic] = useState("");
  const [doctorName, setDoctorName] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [slot, setSlot] = useState("");
  const [duration, setDuration] = useState(20);
  const [bookError, setBookError] = useState<string | null>(null);

  const canBook = hasRole("front_desk", "admin", "doctor");
  const canChange = hasRole("patient", "caregiver", "front_desk", "admin");
  const isDoctor = hasRole("doctor");
  const isPatientView = hasRole("patient", "caregiver");
  const myDoctorName = me.doctor_display_name?.trim() || "";
  const [slotDateFilter, setSlotDateFilter] = useState("");

  const metaQuery = useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/api/v1/meta"),
    staleTime: 5 * 60_000,
  });

  const clinics = useMemo(() => {
    const all = metaQuery.data?.clinics ?? [];
    if (hasRole("admin")) return all;
    return all.filter((item) => me.clinic_ids.includes(item.code));
  }, [metaQuery.data, hasRole, me.clinic_ids]);

  useEffect(() => {
    if (!clinic && clinics.length) setClinic(clinics[0].code);
  }, [clinic, clinics]);

  const appointmentsQuery = useQuery({
    queryKey: ["appointments", grid.params, statusFilter, specialtyFilter, clinicFilter, dateFrom, dateTo],
    queryFn: () =>
      api<GridResponse<Appointment>>(
        `/api/v1/appointments${qs({
          ...grid.params,
          status: statusFilter || undefined,
          specialty: specialtyFilter || undefined,
          clinic: clinicFilter || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        })}`,
      ),
  });

  const mySlotsClinic = clinicFilter || clinics[0]?.code || "";
  const mySlotsQuery = useQuery({
    queryKey: ["slots", "mine", myDoctorName, mySlotsClinic],
    queryFn: () =>
      api<SlotsResponse>(
        `/api/v1/doctors/${encodeURIComponent(myDoctorName)}/slots${qs({
          clinic: mySlotsClinic,
          days: 14,
        })}`,
      ),
    enabled: isDoctor && Boolean(myDoctorName) && Boolean(mySlotsClinic),
  });

  useEffect(() => {
    if (isDoctor && myDoctorName && doctorName !== myDoctorName) {
      setDoctorName(myDoctorName);
    }
  }, [isDoctor, myDoctorName, doctorName]);

  const doctorsQuery = useQuery({
    queryKey: ["doctors", "booking", clinic],
    queryFn: () =>
      api<GridResponse<Doctor>>(
        `/api/v1/doctors${qs({ page_size: 100, clinic: clinic || undefined })}`,
      ),
    enabled: bookOpen && Boolean(clinic),
  });

  /** Distinct specialties mapped to the currently selected doctor (same clinic list). */
  const doctorSpecialtyOptions = useMemo(() => {
    const name = doctorName.trim();
    if (!name) return [] as { code: string; label: string }[];
    const byCode = new Map<string, string>();
    for (const doctor of doctorsQuery.data?.items ?? []) {
      if (doctor.doctor_name !== name) continue;
      if (!byCode.has(doctor.specialty_code)) {
        byCode.set(doctor.specialty_code, doctor.specialty_label || doctor.specialty_code);
      }
    }
    return [...byCode.entries()].map(([code, label]) => ({ code, label }));
  }, [doctorName, doctorsQuery.data?.items]);

  // Only ask for specialty when the doctor maps to multiple codes, or the name is
  // free-typed / unknown (no catalogue rows) so front desk can still set one.
  const showSpecialtyPicker =
    doctorSpecialtyOptions.length > 1 ||
    (doctorName.trim().length >= 2 &&
      doctorSpecialtyOptions.length === 0 &&
      !doctorsQuery.isFetching);

  useEffect(() => {
    if (doctorSpecialtyOptions.length === 1) {
      const only = doctorSpecialtyOptions[0].code;
      if (specialty !== only) setSpecialty(only);
      return;
    }
    if (
      doctorSpecialtyOptions.length > 1 &&
      specialty &&
      !doctorSpecialtyOptions.some((entry) => entry.code === specialty)
    ) {
      setSpecialty(doctorSpecialtyOptions[0].code);
    }
  }, [doctorSpecialtyOptions, specialty]);

  const bookingSlotsQuery = useQuery({
    queryKey: ["slots", "booking", doctorName.trim(), clinic],
    queryFn: () =>
      api<SlotsResponse>(
        `/api/v1/doctors/${encodeURIComponent(doctorName.trim())}/slots${qs({
          clinic,
          days: 7,
        })}`,
      ),
    enabled: bookOpen && doctorName.trim().length >= 2 && Boolean(clinic),
  });

  const detailQuery = useQuery({
    queryKey: ["appointment", detailId],
    queryFn: () => api<Appointment>(`/api/v1/appointments/${detailId}`),
    enabled: Boolean(detailId),
  });

  const rescheduleSlotsQuery = useQuery({
    queryKey: ["slots", "reschedule", rescheduleTarget?.doctor_name, rescheduleTarget?.clinic_code],
    queryFn: () =>
      api<SlotsResponse>(
        `/api/v1/doctors/${encodeURIComponent(
          rescheduleTarget?.doctor_name ?? "",
        )}/slots${qs({ clinic: rescheduleTarget?.clinic_code ?? "", days: 7 })}`,
      ),
    enabled: Boolean(rescheduleTarget),
  });

  const bookingMutation = useMutation({
    mutationFn: () =>
      api<Appointment>("/api/v1/appointments", {
        method: "POST",
        body: {
          patient_id: patient?.id,
          clinic_code: clinic,
          doctor_name: doctorName.trim(),
          specialty_code: specialty,
          starts_at: slot,
          duration_minutes: duration,
        },
      }),
    onSuccess: () => {
      setSuccess(t("appointments.created"));
      setBookOpen(false);
      setBookError(null);
      setPatient(null);
      setSlot("");
      void queryClient.invalidateQueries({ queryKey: ["appointments"] });
      void queryClient.invalidateQueries({ queryKey: ["slots"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setBookError(errorMessage(error)),
  });

  const cancelMutation = useMutation({
    mutationFn: (appointment: Appointment) =>
      api<Appointment>(`/api/v1/appointments/${appointment.id}/cancel`, { method: "POST" }),
    onSuccess: () => {
      setSuccess(t("appointments.cancelled"));
      setCancelTarget(null);
      setDetailId(null);
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["appointments"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const overrideMutation = useMutation({
    mutationFn: () =>
      api<Appointment>(`/api/v1/appointments/${overrideTarget?.id}/override`, {
        method: "POST",
        body: { action: "cancel", reason: overrideReason.trim() },
      }),
    onSuccess: () => {
      setSuccess(t("appointments.cancelled"));
      setOverrideTarget(null);
      setOverrideReason("");
      setDetailId(null);
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["appointments"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const rescheduleMutation = useMutation({
    mutationFn: () =>
      api<Appointment>(`/api/v1/appointments/${rescheduleTarget?.id}/reschedule`, {
        method: "POST",
        body: { starts_at: rescheduleSlot, duration_minutes: rescheduleDuration },
      }),
    onSuccess: () => {
      setSuccess(t("appointments.rescheduled"));
      setRescheduleTarget(null);
      setDetailId(null);
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["appointments"] });
      void queryClient.invalidateQueries({ queryKey: ["slots"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const specialtyLabel = (code: string): string => {
    const item = metaQuery.data?.specialties.find((entry) => entry.code === code);
    return item ? item[localeKey(locale)] : humanize(code);
  };

  const resetFilters = () => {
    setStatusFilter("");
    setSpecialtyFilter("");
    setClinicFilter("");
    setDateFrom("");
    setDateTo("");
    grid.resetPage();
  };

  const submitBooking = () => {
    setBookError(null);
    if (!patient) {
      setBookError(t("appointments.patientRequired"));
      return;
    }
    if (!doctorName.trim()) {
      setBookError(t("appointments.doctorRequired"));
      return;
    }
    if (!slot) {
      setBookError(t("appointments.slotRequired"));
      return;
    }
    if (!specialty) {
      setBookError(t("common.required"));
      return;
    }
    bookingMutation.mutate();
  };

  const columns: DataGridColumn<Appointment>[] = [
    {
      key: "starts_at",
      header: t("common.date"),
      sortKey: "starts_at",
      render: (row) => (
        <div className="cell-stack">
          <strong>{formatDateTime(row.starts_at, locale, metaQuery.data?.app.timezone)}</strong>
          <span className="muted small">
            {row.duration_minutes} {t("appointments.minutes")}
          </span>
        </div>
      ),
    },
    ...(isDoctor
      ? []
      : [
          {
            key: "doctor",
            header: t("common.doctor"),
            sortKey: "doctor_name" as const,
            render: (row: Appointment) => (
              <div className="cell-stack">
                <strong>{row.doctor_name}</strong>
                <span className="muted small">
                  {row.specialty_label ?? specialtyLabel(row.specialty_code)}
                </span>
              </div>
            ),
          } satisfies DataGridColumn<Appointment>,
        ]),
    {
      key: "clinic",
      header: t("common.clinic"),
      sortKey: "clinic_code",
      hideOnMobile: true,
      render: (row) => <Badge tone="neutral">{row.clinic_code}</Badge>,
    },
    ...(isPatientView
      ? []
      : [
          {
            key: "patient",
            header: t("appointments.withPatient"),
            render: (row: Appointment) => (
              <div className="cell-stack">
                <strong>{row.patient_display_name ?? t("common.unknown")}</strong>
                <div className="tag-row">
                  {row.visit_kind === "first" ? (
                    <Badge tone="info">{t("appointments.visitFirst")}</Badge>
                  ) : row.visit_kind === "repeat" ? (
                    <Badge tone="neutral">{t("appointments.visitRepeat")}</Badge>
                  ) : null}
                </div>
              </div>
            ),
          } satisfies DataGridColumn<Appointment>,
          {
            key: "visit",
            header: t("appointments.forSpecialty"),
            hideOnMobile: true,
            render: (row: Appointment) => (
              <span>{row.specialty_label ?? specialtyLabel(row.specialty_code)}</span>
            ),
          } satisfies DataGridColumn<Appointment>,
        ]),
    ...(hasRole("front_desk", "admin")
      ? [
          {
            key: "source",
            header: "Source",
            hideOnMobile: true,
            render: (row: Appointment) => (
              <Badge tone={row.source === "assistant" ? "info" : "neutral"}>
                {row.source === "assistant" ? "Assistant" : "Front desk"}
              </Badge>
            ),
          } satisfies DataGridColumn<Appointment>,
        ]
      : []),
    {
      key: "status",
      header: t("appointments.status"),
      sortKey: "status",
      render: (row) => (
        <div className="cell-stack">
          <StatusBadge status={row.status} />
          {row.no_show_band ? (
            <Badge
              tone={
                row.no_show_band === "high"
                  ? "danger"
                  : row.no_show_band === "medium"
                    ? "warning"
                    : "neutral"
              }
            >
              {t("appointments.noShowRisk")}: {row.no_show_band}
              {typeof row.no_show_risk === "number" ? ` (${Math.round(row.no_show_risk * 100)}%)` : ""}
            </Badge>
          ) : null}
          {row.waitlist_suggested ? (
            <Badge tone="warning">{t("appointments.waitlistSuggested")}</Badge>
          ) : null}
          {row.confirm_by_reply ? (
            <Badge tone="info">{t("appointments.confirmByReply")}</Badge>
          ) : null}
        </div>
      ),
    },
    {
      key: "actions",
      header: t("common.actions"),
      align: "right",
      render: (row) => (
        <div className="row-actions">
          <IconButton
            label={t("common.details")}
            icon={<Eye size={15} />}
            onClick={(event) => {
              event.stopPropagation();
              setDetailId(row.id);
            }}
          />
          {canChange && ["held", "confirmed"].includes(row.status) ? (
            <IconButton
              label={t("appointments.cancelAppointment")}
              icon={<XCircle size={15} />}
              tone="danger"
              onClick={(event) => {
                event.stopPropagation();
                setCancelTarget(row);
              }}
            />
          ) : null}
        </div>
      ),
    },
  ];

  const detail = detailQuery.data;
  const bookingSlots = bookingSlotsQuery.data?.slots ?? [];
  const rescheduleSlots = rescheduleSlotsQuery.data?.slots ?? [];
  const timezone = metaQuery.data?.app.timezone ?? "Asia/Kolkata";
  const filteredDoctorSlots = useMemo(() => {
    const slots = mySlotsQuery.data?.slots ?? [];
    if (!slotDateFilter) return slots;
    return slots.filter((slot) => {
      const isoDay = new Intl.DateTimeFormat("en-CA", {
        timeZone: timezone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(new Date(slot));
      return isoDay === slotDateFilter;
    });
  }, [mySlotsQuery.data?.slots, slotDateFilter, timezone]);
  const openBookForSlot = (slotIso: string) => {
    setBookOpen(true);
    setSlot(slotIso);
    setClinic(mySlotsClinic);
    if (isDoctor && myDoctorName) setDoctorName(myDoctorName);
    setBookError(null);
  };
  const pageTitle = isDoctor
    ? t("appointments.titleMine")
    : isPatientView
      ? t("appointments.titlePatient")
      : t("appointments.title");
  const pageSubtitle = isDoctor
    ? t("appointments.subtitleDoctor")
    : isPatientView
      ? t("appointments.subtitlePatient")
      : t("appointments.subtitle");

  return (
    <div className="page">
      <PageHeader
        title={pageTitle}
        subtitle={pageSubtitle}
        actions={
          canBook ? (
            <button type="button" className="btn btn-primary" data-testid="appointments-book" onClick={() => setBookOpen(true)}>
              <CalendarPlus size={16} aria-hidden="true" /> {t("appointments.book")}
            </button>
          ) : null
        }
      />

      {success ? (
        <Callout tone="success" title={t("common.saved")}>
          {success}
        </Callout>
      ) : null}
      <FormError message={actionError} />

      {isDoctor ? (
        <section className="panel" data-testid="doctor-free-slots">
          <div className="section-head">
            <h2>{t("appointments.slotsByDate")}</h2>
            <span className="muted small">
              {myDoctorName || me.display_name || "—"} · {mySlotsClinic || "—"}
            </span>
          </div>
          <p className="muted small">{t("appointments.slotsByDateHint")}</p>
          <div className="filter-row">
            <label className="filter-field">
              <span>{t("appointments.filterDate")}</span>
              <input
                type="date"
                value={slotDateFilter}
                onChange={(event) => setSlotDateFilter(event.target.value)}
              />
            </label>
            {slotDateFilter ? (
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setSlotDateFilter("")}>
                {t("common.clear")}
              </button>
            ) : null}
          </div>
          {mySlotsQuery.isPending ? (
            <Spinner />
          ) : mySlotsQuery.isError ? (
            <FormError message={errorMessage(mySlotsQuery.error)} />
          ) : filteredDoctorSlots.length === 0 ? (
            <p className="muted">{t("appointments.noSlots")}</p>
          ) : (
            <div className="slot-calendar" data-testid="slot-calendar">
              <SlotGroups
                slots={filteredDoctorSlots}
                value={slot}
                onSelect={openBookForSlot}
                locale={locale}
              />
            </div>
          )}
        </section>
      ) : null}

      <DataGrid
        columns={columns}
        items={appointmentsQuery.data?.items}
        meta={appointmentsQuery.data?.meta}
        loading={appointmentsQuery.isFetching}
        error={appointmentsQuery.error}
        grid={grid}
        rowKey={(row) => row.id}
        onRetry={() => void appointmentsQuery.refetch()}
        onRowClick={(row) => setDetailId(row.id)}
        searchPlaceholder={t("appointments.searchPlaceholder")}
        filters={
          <div className="filter-row">
            <label className="filter-field">
              <span>{t("appointments.status")}</span>
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
                    {humanize(status)}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              <span>{t("common.specialty")}</span>
              <select
                value={specialtyFilter}
                onChange={(event) => {
                  setSpecialtyFilter(event.target.value);
                  grid.resetPage();
                }}
              >
                <option value="">{t("common.all")}</option>
                {(metaQuery.data?.specialties ?? []).map((entry) => (
                  <option key={entry.code} value={entry.code}>
                    {entry[localeKey(locale)]}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              <span>{t("common.clinic")}</span>
              <select
                value={clinicFilter}
                onChange={(event) => {
                  setClinicFilter(event.target.value);
                  grid.resetPage();
                }}
              >
                <option value="">{t("common.all")}</option>
                {clinics.map((entry) => (
                  <option key={entry.code} value={entry.code}>
                    {entry.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              <span>{t("appointments.dateFrom")}</span>
              <input
                type="date"
                value={dateFrom}
                onChange={(event) => {
                  setDateFrom(event.target.value);
                  grid.resetPage();
                }}
              />
            </label>
            <label className="filter-field">
              <span>{t("appointments.dateTo")}</span>
              <input
                type="date"
                value={dateTo}
                onChange={(event) => {
                  setDateTo(event.target.value);
                  grid.resetPage();
                }}
              />
            </label>
            <button type="button" className="btn btn-sm btn-ghost" onClick={resetFilters}>
              {t("common.clear")}
            </button>
          </div>
        }
        emptyTitle={t("common.emptyTitle")}
        emptyHint={t("common.emptyHint")}
      />

      <Modal
        open={Boolean(detailId)}
        title={t("appointments.title")}
        onClose={() => setDetailId(null)}
        size="md"
        footer={
          detail ? (
            <>
              <button type="button" className="btn" onClick={() => setDetailId(null)}>
                {t("common.close")}
              </button>
              {canChange && ["held", "confirmed"].includes(detail.status) ? (
                <>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setRescheduleTarget(detail);
                      setRescheduleSlot("");
                      setRescheduleDuration(detail.duration_minutes);
                      setDetailId(null);
                    }}
                  >
                    {t("appointments.reschedule")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-danger"
                    onClick={() => {
                      setCancelTarget(detail);
                      setDetailId(null);
                    }}
                  >
                    {t("appointments.cancelAppointment")}
                  </button>
                  {canBook ? (
                    <button
                      type="button"
                      className="btn btn-danger"
                      onClick={() => {
                        setOverrideTarget(detail);
                        setOverrideReason("");
                        setDetailId(null);
                      }}
                    >
                      {t("appointments.override")}
                    </button>
                  ) : null}
                </>
              ) : null}
            </>
          ) : null
        }
      >
        {detailQuery.isPending ? (
          <div className="mini-loading">{t("common.loading")}</div>
        ) : detailQuery.isError ? (
          <FormError message={errorMessage(detailQuery.error)} />
        ) : detail ? (
          <>
            <DefinitionList
              items={[
                [
                  t("common.patient"),
                  detail.patient_display_name ? (
                    <div className="cell-stack">
                      <strong>{detail.patient_display_name}</strong>
                      <code className="mono muted small">{detail.patient_id ?? "—"}</code>
                    </div>
                  ) : (
                    <code className="mono">{detail.patient_id ?? "—"}</code>
                  ),
                ],
                [
                  t("appointments.forSpecialty"),
                  <div className="cell-stack">
                    <span>{detail.specialty_label ?? specialtyLabel(detail.specialty_code)}</span>
                    {detail.visit_kind === "first" ? (
                      <Badge tone="info">{t("appointments.visitFirst")}</Badge>
                    ) : detail.visit_kind === "repeat" ? (
                      <Badge tone="neutral">{t("appointments.visitRepeat")}</Badge>
                    ) : null}
                  </div>,
                ],
                [t("common.doctor"), detail.doctor_name],
                [t("common.clinic"), detail.clinic_code],
                [
                  t("common.date"),
                  formatDateTime(detail.starts_at, locale, metaQuery.data?.app.timezone),
                ],
                [
                  t("appointments.duration"),
                  `${detail.duration_minutes} ${t("appointments.minutes")}`,
                ],
                [t("common.status"), <StatusBadge status={detail.status} />],
                [
                  t("appointments.created"),
                  formatDateTime(detail.created_at, locale, metaQuery.data?.app.timezone),
                ],
              ]}
            />
            <FormError message={actionError} />
          </>
        ) : null}
      </Modal>

      <Modal
        open={bookOpen}
        title={t("appointments.book")}
        description={t("appointments.slotsHint")}
        onClose={() => setBookOpen(false)}
        size="lg"
        busy={bookingMutation.isPending}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setBookOpen(false)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              data-testid="appointments-confirm-booking"
              onClick={submitBooking}
              disabled={bookingMutation.isPending}
            >
              {bookingMutation.isPending ? <Spinner /> : <CalendarPlus size={15} aria-hidden="true" />}
              {t("appointments.confirmBooking")}
            </button>
          </>
        }
      >
        <div className="form-grid">
          <Field label={t("appointments.patient")} required>
            <PatientPicker value={patient} onChange={setPatient} />
          </Field>
          <Field label={t("common.clinic")} required>
            <select
              value={clinic}
              onChange={(event) => {
                setClinic(event.target.value);
                setSlot("");
              }}
            >
              {clinics.map((entry) => (
                <option key={entry.code} value={entry.code}>
                  {entry.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("appointments.doctorName")} required>
            <input
              list="doctor-options"
              value={doctorName}
              onChange={(event) => {
                if (isDoctor) return;
                const next = event.target.value;
                setDoctorName(next);
                setSlot("");
                const matches = (doctorsQuery.data?.items ?? []).filter(
                  (doctor) => doctor.doctor_name === next,
                );
                const unique = [...new Set(matches.map((doctor) => doctor.specialty_code))];
                if (unique.length === 1) setSpecialty(unique[0]);
                else if (unique.length === 0) setSpecialty("");
              }}
              placeholder={t("appointments.chooseDoctor")}
              maxLength={120}
              readOnly={isDoctor}
              data-testid="appointments-doctor-input"
            />
            {!isDoctor ? (
              <datalist id="doctor-options">
                {(doctorsQuery.data?.items ?? []).map((doctor) => (
                  <option
                    key={`${doctor.doctor_name}-${doctor.specialty_code}-${doctor.clinic_code}`}
                    value={doctor.doctor_name}
                  >
                    {doctor.specialty_label}
                  </option>
                ))}
              </datalist>
            ) : null}
          </Field>
          {showSpecialtyPicker ? (
            <Field label={t("common.specialty")} required>
              <select value={specialty} onChange={(event) => setSpecialty(event.target.value)}>
                {doctorSpecialtyOptions.length > 0 ? (
                  doctorSpecialtyOptions.map((entry) => (
                    <option key={entry.code} value={entry.code}>
                      {entry.label ||
                        metaQuery.data?.specialties?.find((item) => item.code === entry.code)?.[
                          localeKey(locale)
                        ] ||
                        entry.code}
                    </option>
                  ))
                ) : (
                  <>
                    <option value="">{t("common.all")}</option>
                    {(metaQuery.data?.specialties ?? []).map((entry) => (
                      <option key={entry.code} value={entry.code}>
                        {entry[localeKey(locale)]}
                      </option>
                    ))}
                  </>
                )}
              </select>
            </Field>
          ) : null}
          <Field label={t("appointments.duration")}>
            <select value={duration} onChange={(event) => setDuration(Number(event.target.value))}>
              {[10, 15, 20, 30, 45, 60].map((minutes) => (
                <option key={minutes} value={minutes}>
                  {minutes} {t("appointments.minutes")}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="slot-section">
          <span className="field-label">{t("appointments.slot")}</span>
          {bookingSlotsQuery.isFetching ? (
            <div className="mini-loading">{t("common.loading")}</div>
          ) : bookingSlotsQuery.isError ? (
            <FormError message={errorMessage(bookingSlotsQuery.error)} />
          ) : bookingSlots.length === 0 ? (
            <p className="muted">{t("appointments.noSlots")}</p>
          ) : (
            <SlotGroups slots={bookingSlots} value={slot} onSelect={setSlot} locale={locale} />
          )}
          <p className="muted small">{t("appointments.timezone", { zone: "Asia/Kolkata" })}</p>
        </div>
        <FormError message={bookError} />
      </Modal>

      <Modal
        open={Boolean(rescheduleTarget)}
        title={t("appointments.reschedule")}
        description={t("appointments.rescheduleBody")}
        onClose={() => setRescheduleTarget(null)}
        size="lg"
        footer={
          <>
            <button type="button" className="btn" onClick={() => setRescheduleTarget(null)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!rescheduleSlot || rescheduleMutation.isPending}
              onClick={() => rescheduleMutation.mutate()}
            >
              {rescheduleMutation.isPending ? <Spinner /> : null}
              {t("appointments.reschedule")}
            </button>
          </>
        }
      >
        {rescheduleTarget ? (
          <DefinitionList
            items={[
              [t("common.doctor"), rescheduleTarget.doctor_name],
              [t("common.clinic"), rescheduleTarget.clinic_code],
              [
                t("common.date"),
                formatDateTime(rescheduleTarget.starts_at, locale, metaQuery.data?.app.timezone),
              ],
            ]}
          />
        ) : null}
        <Field label={t("appointments.duration")}>
          <select
            value={rescheduleDuration}
            onChange={(event) => setRescheduleDuration(Number(event.target.value))}
          >
            {[10, 15, 20, 30, 45, 60].map((minutes) => (
              <option key={minutes} value={minutes}>
                {minutes} {t("appointments.minutes")}
              </option>
            ))}
          </select>
        </Field>
        <div className="slot-section">
          <span className="field-label">{t("appointments.newTime")}</span>
          {rescheduleSlotsQuery.isFetching ? (
            <div className="mini-loading">{t("common.loading")}</div>
          ) : rescheduleSlots.length === 0 ? (
            <p className="muted">{t("appointments.noSlots")}</p>
          ) : (
            <SlotGroups
              slots={rescheduleSlots}
              value={rescheduleSlot}
              onSelect={setRescheduleSlot}
              locale={locale}
            />
          )}
          <p className="muted small">{t("appointments.timezone", { zone: "Asia/Kolkata" })}</p>
        </div>
        <FormError message={actionError} />
      </Modal>

      <ConfirmDialog
        open={Boolean(cancelTarget)}
        title={t("appointments.cancelAppointment")}
        body={<p>{t("appointments.cancelBody")}</p>}
        confirmLabel={t("appointments.cancelAppointment")}
        tone="danger"
        busy={cancelMutation.isPending}
        onClose={() => setCancelTarget(null)}
        onConfirm={() => {
          if (cancelTarget) cancelMutation.mutate(cancelTarget);
        }}
      />

      <Modal
        open={Boolean(overrideTarget)}
        title={t("appointments.override")}
        onClose={() => setOverrideTarget(null)}
        busy={overrideMutation.isPending}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setOverrideTarget(null)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-danger"
              disabled={overrideReason.trim().length < 5 || overrideMutation.isPending}
              onClick={() => overrideMutation.mutate()}
            >
              {overrideMutation.isPending ? <Spinner /> : null}
              {t("appointments.override")}
            </button>
          </>
        }
      >
        <p className="muted">{t("appointments.overrideBody")}</p>
        <Field label={t("appointments.overrideReason")}>
          <textarea
            value={overrideReason}
            onChange={(event) => setOverrideReason(event.target.value)}
            rows={3}
            maxLength={500}
          />
        </Field>
        <FormError message={actionError} />
      </Modal>
    </div>
  );
}

function SlotGroups({
  slots,
  value,
  onSelect,
  locale,
}: {
  slots: string[];
  value: string;
  onSelect: (slot: string) => void;
  locale: string;
}) {
  const groups = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const slot of slots) {
      const day = new Intl.DateTimeFormat("en-CA", {
        timeZone: "Asia/Kolkata",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(new Date(slot));
      const list = map.get(day) ?? [];
      list.push(slot);
      map.set(day, list);
    }
    return Array.from(map.entries());
  }, [slots]);

  return (
    <div className="slot-groups">
      {groups.map(([day, items]) => (
        <div className="slot-group" key={day}>
          <span className="slot-day">{formatDate(items[0], locale, "Asia/Kolkata")}</span>
          <div className="slot-buttons">
            {items.map((item) => (
              <button
                key={item}
                type="button"
                className={`slot ${value === item ? "is-selected" : ""}`}
                data-testid="appointments-slot"
                onClick={() => onSelect(item)}
                aria-pressed={value === item}
              >
                {new Intl.DateTimeFormat(locale, {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "Asia/Kolkata",
                }).format(new Date(item))}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
