import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileText, Hospital } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { Badge } from "../components/Badge";
import { FormError, PageHeader, Spinner } from "../components/primitives";
import { api, errorMessage, isApiError } from "../lib/api";
import { formatDate, formatDateTime, humanize } from "../lib/format";
import { useI18n } from "../lib/i18n";

interface FhirLink {
  patient_id: string;
  fhir_patient_id: string;
  system: string;
  updated_at: string;
}

interface FhirPatientPayload {
  patient_id: string;
  link: FhirLink;
  demographics: Record<string, unknown>;
  source: string;
}

interface FhirEncounterRow {
  /** API mapped shape from apps/api/.../fhir.py `_map_encounter`. */
  fhir_id?: string;
  status?: string;
  class_code?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  /** Legacy / raw FHIR resource fields (tolerated if present). */
  id?: string;
  class?: string | { code?: string; display?: string };
  period?: { start?: string; end?: string };
  [key: string]: unknown;
}

interface FhirEncountersPayload {
  patient_id: string;
  fhir_patient_id: string;
  encounters: FhirEncounterRow[];
  source: string;
}

interface FhirDocumentRow {
  fhir_id?: string;
  status?: string;
  doc_status?: string | null;
  type?: string | null;
  description?: string | null;
  date?: string | null;
  content_types?: string[];
  source?: "local" | "fhir" | string;
  local_document_id?: string;
  page_count?: number | null;
  [key: string]: unknown;
}

interface FhirDocumentsPayload {
  patient_id: string;
  fhir_patient_id: string | null;
  local_records: FhirDocumentRow[];
  fhir_records: FhirDocumentRow[];
  source: string;
}

function displayClass(row: FhirEncounterRow): string {
  if (typeof row.class_code === "string" && row.class_code.trim()) return row.class_code;
  const value = row.class;
  if (!value) return "—";
  if (typeof value === "string") return value;
  return value.display || value.code || "—";
}

function encounterId(row: FhirEncounterRow): string {
  const raw = row.fhir_id || row.id;
  return raw ? String(raw) : "—";
}

function periodStart(row: FhirEncounterRow): string | null {
  if (typeof row.period_start === "string" && row.period_start) return row.period_start;
  if (row.period?.start) return String(row.period.start);
  return null;
}

function periodEnd(row: FhirEncounterRow): string | null {
  if (typeof row.period_end === "string" && row.period_end) return row.period_end;
  if (row.period?.end) return String(row.period.end);
  return null;
}

function RecordsTable({
  rows,
  locale,
  emptyLabel,
  showSource,
}: {
  rows: FhirDocumentRow[];
  locale: string;
  emptyLabel: string;
  showSource?: boolean;
}) {
  const { t } = useI18n();
  if (rows.length === 0) {
    return <p className="muted">{emptyLabel}</p>;
  }
  return (
    <div className="table-wrap">
      <table className="data-table compact">
        <thead>
          <tr>
            <th scope="col">{t("fhir.recordTitle")}</th>
            <th scope="col">{t("fhir.recordType")}</th>
            <th scope="col">{t("fhir.status")}</th>
            <th scope="col">{t("fhir.recordDate")}</th>
            {showSource ? <th scope="col">{t("fhir.recordSource")}</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const id = String(row.local_document_id || row.fhir_id || index);
            const title = row.description || row.type || id;
            const status = row.doc_status || row.status || "unknown";
            return (
              <tr key={`${id}-${index}`}>
                <td>
                  <div className="cell-stack">
                    <strong>{title}</strong>
                    <code className="mono muted">{id.slice(0, 16)}</code>
                  </div>
                </td>
                <td>{row.type ? humanize(String(row.type)) : "—"}</td>
                <td>
                  <Badge tone="neutral">{humanize(String(status))}</Badge>
                </td>
                <td className="muted">
                  {row.date ? formatDateTime(String(row.date), locale) : "—"}
                </td>
                {showSource ? (
                  <td>
                    <Badge tone={row.source === "local" ? "violet" : "neutral"}>
                      {row.source === "local" ? t("fhir.sourceLocal") : t("fhir.sourceFhir")}
                    </Badge>
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function PatientFhirPage() {
  const { patientId = "" } = useParams<{ patientId: string }>();
  const { t, locale } = useI18n();

  const demographicsQuery = useQuery({
    queryKey: ["fhir-patient", patientId],
    queryFn: () => api<FhirPatientPayload>(`/api/v1/fhir/patients/${patientId}`),
    enabled: Boolean(patientId),
    retry: false,
  });

  const encountersQuery = useQuery({
    queryKey: ["fhir-encounters", patientId],
    queryFn: () =>
      api<FhirEncountersPayload>(`/api/v1/fhir/patients/${patientId}/encounters?count=20`),
    enabled: Boolean(patientId) && demographicsQuery.isSuccess,
    retry: false,
  });

  const recordsQuery = useQuery({
    queryKey: ["fhir-document-references", patientId],
    queryFn: () =>
      api<FhirDocumentsPayload>(
        `/api/v1/fhir/patients/${patientId}/document-references?count=50`,
      ),
    enabled: Boolean(patientId),
    retry: false,
  });

  const demogError = demographicsQuery.error;
  const missingLink =
    isApiError(demogError) &&
    (demogError.code === "fhir_link_missing" || demogError.status === 404);
  const unconfigured =
    isApiError(demogError) &&
    (demogError.code === "fhir_unconfigured" || demogError.code === "fhir_disabled");

  const demo = demographicsQuery.data?.demographics ?? {};
  const name =
    (typeof demo.display_name === "string" && demo.display_name) ||
    (typeof demo.name === "string" && demo.name) ||
    null;

  const encounters = encountersQuery.data?.encounters ?? [];
  const localRecords = recordsQuery.data?.local_records ?? [];
  const fhirRecords = recordsQuery.data?.fhir_records ?? [];
  const combinedRecords = [...localRecords, ...fhirRecords];

  return (
    <>
      <PageHeader
        title={t("fhir.title")}
        subtitle={t("fhir.subtitle")}
        actions={
          <Link to="/patients" className="btn ghost">
            <ArrowLeft size={16} aria-hidden="true" />
            {t("fhir.backToPatients")}
          </Link>
        }
      />

      <section className="panel" data-testid="fhir-demographics">
        <div className="panel-head">
          <h3>
            <Hospital size={18} aria-hidden="true" />
            {t("fhir.demographics")}
          </h3>
          <Badge tone="neutral">{t("fhir.readOnly")}</Badge>
        </div>

        {!patientId ? <FormError message={t("fhir.missingPatient")} /> : null}
        {demographicsQuery.isLoading ? <Spinner /> : null}

        {unconfigured ? (
          <p className="muted">{t("fhir.unconfigured")}</p>
        ) : missingLink ? (
          <p className="muted">{t("fhir.noLink")}</p>
        ) : demogError ? (
          <FormError message={errorMessage(demogError)} />
        ) : demographicsQuery.data ? (
          <div className="stat-grid">
            <div className="stat">
              <span className="stat-label">{t("fhir.localPatient")}</span>
              <span className="stat-value mono">{demographicsQuery.data.patient_id.slice(0, 8)}</span>
            </div>
            <div className="stat">
              <span className="stat-label">{t("fhir.fhirPatientId")}</span>
              <span className="stat-value mono">
                {demographicsQuery.data.link.fhir_patient_id}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">{t("fhir.name")}</span>
              <span className="stat-value">{name ?? t("common.unknown")}</span>
            </div>
            <div className="stat">
              <span className="stat-label">{t("fhir.gender")}</span>
              <span className="stat-value">{humanize(String(demo.gender ?? "unknown"))}</span>
            </div>
            <div className="stat">
              <span className="stat-label">{t("fhir.birthDate")}</span>
              <span className="stat-value">
                {demo.birth_date || demo.birthDate
                  ? formatDate(String(demo.birth_date ?? demo.birthDate), locale)
                  : "—"}
              </span>
            </div>
          </div>
        ) : null}
      </section>

      <section className="panel" data-testid="fhir-patient-records">
        <div className="panel-head">
          <h3>
            <FileText size={18} aria-hidden="true" />
            {t("fhir.patientRecords")}
          </h3>
          {combinedRecords.length > 0 ? (
            <Badge tone="neutral">
              {t("fhir.recordCount", { count: String(combinedRecords.length) })}
            </Badge>
          ) : null}
        </div>
        <p className="muted small">{t("fhir.patientRecordsHint")}</p>
        {recordsQuery.isLoading ? <Spinner /> : null}
        {recordsQuery.error ? (
          <FormError message={errorMessage(recordsQuery.error)} />
        ) : recordsQuery.isSuccess ? (
          <RecordsTable
            rows={combinedRecords}
            locale={locale}
            emptyLabel={t("fhir.noRecords")}
            showSource
          />
        ) : null}
        {patientId && localRecords.length > 0 ? (
          <p className="muted small" style={{ marginTop: 12 }}>
            <Link to={`/records?patient_id=${encodeURIComponent(patientId)}`}>
              {t("fhir.openInRecords")}
            </Link>
          </p>
        ) : null}
      </section>

      <section className="panel" data-testid="fhir-encounters">
        <div className="panel-head">
          <h3>{t("fhir.encounters")}</h3>
        </div>
        {encountersQuery.isLoading ? <Spinner /> : null}
        {encountersQuery.error ? (
          <FormError message={errorMessage(encountersQuery.error)} />
        ) : demographicsQuery.isSuccess && encounters.length === 0 ? (
          <p className="muted">{t("fhir.noEncounters")}</p>
        ) : encounters.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table compact">
              <thead>
                <tr>
                  <th scope="col">{t("fhir.encounterId")}</th>
                  <th scope="col">{t("fhir.status")}</th>
                  <th scope="col">{t("fhir.class")}</th>
                  <th scope="col">{t("fhir.period")}</th>
                </tr>
              </thead>
              <tbody>
                {encounters.map((row, index) => {
                  const id = encounterId(row);
                  const start = periodStart(row);
                  const end = periodEnd(row);
                  return (
                    <tr key={`${id}-${index}`}>
                      <td>
                        <code className="mono muted">{id.slice(0, 16)}</code>
                      </td>
                      <td>
                        <Badge tone="neutral">{humanize(String(row.status ?? "unknown"))}</Badge>
                      </td>
                      <td>{displayClass(row)}</td>
                      <td className="muted">
                        {start ? formatDate(start, locale) : "—"}
                        {end ? ` → ${formatDate(end, locale)}` : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : missingLink || unconfigured ? (
          <p className="muted">{t("fhir.encountersNeedLink")}</p>
        ) : null}
      </section>
    </>
  );
}
