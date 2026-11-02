import { useQuery } from "@tanstack/react-query";
import { FolderOpen, Hospital } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "../components/Badge";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { PageHeader } from "../components/primitives";
import { api, qs } from "../lib/api";
import { formatDate, humanize } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type { GridResponse, Patient } from "../lib/types";

export function PatientsPage() {
  const { t, locale } = useI18n();
  const grid = useGridState("display_name", "asc");

  const patientsQuery = useQuery({
    queryKey: ["patients", grid.params],
    queryFn: () => api<GridResponse<Patient>>(`/api/v1/patients${qs(grid.params)}`),
    placeholderData: (previous) => previous,
  });

  const columns: DataGridColumn<Patient>[] = [
    {
      key: "display_name",
      header: t("patients.displayName"),
      sortKey: "display_name",
      render: (row) => (
        <div className="cell-stack">
          <strong>{row.display_name ?? <span className="muted">{t("common.unknown")}</span>}</strong>
          <code className="mono muted">{row.id.slice(0, 8)}</code>
        </div>
      ),
    },
    {
      key: "locale",
      header: t("patients.locale"),
      sortKey: "locale",
      hideOnMobile: true,
      render: (row) => <span>{humanize(row.locale)}</span>,
    },
    {
      key: "linked",
      header: t("patients.linked"),
      render: (row) =>
        row.linked ? (
          <Badge tone="success">{humanize("verified")}</Badge>
        ) : (
          <Badge tone="neutral">{t("patients.unlinked")}</Badge>
        ),
    },
    {
      key: "created_at",
      header: t("patients.created"),
      sortKey: "created_at",
      hideOnMobile: true,
      render: (row) => <span className="muted">{formatDate(row.created_at, locale)}</span>,
    },
    {
      key: "actions",
      header: t("common.actions"),
      align: "right",
      width: "110px",
      render: (row) => (
        <div className="row-actions">
          <Link
            to={`/patients/${row.id}/fhir`}
            className="icon-btn"
            aria-label={t("fhir.open")}
            data-tooltip={t("fhir.open")}
          >
            <Hospital size={16} aria-hidden="true" />
          </Link>
          <Link
            to="/records"
            state={{ patient: row }}
            className="icon-btn"
            aria-label={t("records.viewDocument")}
            data-tooltip={t("nav.records")}
          >
            <FolderOpen size={16} aria-hidden="true" />
          </Link>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader title={t("patients.title")} subtitle={t("patients.subtitle")} />
      <DataGrid
        columns={columns}
        items={patientsQuery.data?.items}
        meta={patientsQuery.data?.meta}
        loading={patientsQuery.isFetching}
        error={patientsQuery.error}
        grid={grid}
        rowKey={(row) => row.id}
        onRetry={() => void patientsQuery.refetch()}
        searchPlaceholder={t("patients.searchPlaceholder")}
        emptyTitle={t("common.emptyTitle")}
      />
    </>
  );
}
