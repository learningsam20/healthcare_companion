import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Package, Plus, Trash2, Upload } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import { Badge } from "../components/Badge";
import { DataGrid, type DataGridColumn } from "../components/DataGrid";
import { PageHeader } from "../components/primitives";
import { api, qs } from "../lib/api";
import { formatDate, humanize } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import type { GridResponse } from "../lib/types";

interface StockItem {
  id: string;
  sku: string;
  drug_name: string;
  form: string;
  strength: string;
  quantity: number;
  clinic_code: string;
  updated_at: string;
  source: string;
  status?: string | null;
  stale?: boolean | null;
}

interface StockForm {
  sku: string;
  drug_name: string;
  form: string;
  strength: string;
  quantity: number;
  clinic_code: string;
  source: string;
}

const emptyForm: StockForm = {
  sku: "",
  drug_name: "",
  form: "",
  strength: "",
  quantity: 0,
  clinic_code: "BANER",
  source: "manual",
};

export function PharmacyPage() {
  const { t, locale } = useI18n();
  const { hasRole } = useAuth();
  const canWrite = hasRole("pharmacist") || hasRole("admin");
  const grid = useGridState("drug_name", "asc");
  const [clinic, setClinic] = useState("");
  const [draft, setDraft] = useState<StockForm>(emptyForm);
  const deferredQ = useDeferredValue(grid.query);
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: ["pharmacy", "stock", grid.params, clinic],
    queryFn: () =>
      api<GridResponse<StockItem>>(
        `/api/v1/pharmacy/stock${qs({
          ...grid.params,
          clinic_code: clinic || undefined,
        })}`,
      ),
    placeholderData: (previous) => previous,
  });

  const [comboOpen, setComboOpen] = useState(false);

  const suggestionsQuery = useQuery({
    queryKey: ["pharmacy", "typeahead", deferredQ, clinic],
    queryFn: () =>
      api<{ items: StockItem[]; total: number; limit: number; q: string }>(
        `/api/v1/pharmacy/stock/typeahead${qs({
          q: deferredQ,
          clinic_code: clinic || undefined,
          limit: 8,
        })}`,
      ),
    enabled: deferredQ.trim().length >= 2,
  });

  const suggestionItems = suggestionsQuery.data?.items ?? [];
  const suggestionTotal = suggestionsQuery.data?.total ?? 0;

  const saveMutation = useMutation({
    mutationFn: (body: StockForm) =>
      api<StockItem>("/api/v1/pharmacy/stock", { method: "POST", body }),
    onSuccess: () => {
      setDraft(emptyForm);
      void queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      api<void>(`/api/v1/pharmacy/stock/${id}`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pharmacy"] }),
  });

  const importMutation = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<{ row_count: number; status: string }>("/api/v1/pharmacy/stock/import", {
        method: "POST",
        form,
      });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pharmacy"] }),
  });

  const columns: DataGridColumn<StockItem>[] = useMemo(
    () => [
      {
        key: "drug_name",
        header: t("pharmacy.drug"),
        sortKey: "drug_name",
        render: (row) => (
          <div className="cell-stack">
            <strong>{row.drug_name}</strong>
            <span className="muted">
              {[row.form, row.strength].filter(Boolean).join(" · ") || row.sku}
            </span>
          </div>
        ),
      },
      {
        key: "clinic_code",
        header: t("pharmacy.clinic"),
        render: (row) => <code className="mono">{row.clinic_code}</code>,
      },
      {
        key: "quantity",
        header: t("pharmacy.qty"),
        render: (row) => <span>{row.quantity}</span>,
      },
      {
        key: "status",
        header: t("pharmacy.status"),
        render: (row) => (
          <Badge
            tone={
              row.stale || row.status === "unknown"
                ? "warning"
                : row.status === "in_stock"
                  ? "success"
                  : row.status === "low"
                    ? "warning"
                    : "danger"
            }
          >
            {humanize(row.status ?? "unknown")}
          </Badge>
        ),
      },
      {
        key: "updated_at",
        header: t("pharmacy.updated"),
        hideOnMobile: true,
        render: (row) => <span className="muted">{formatDate(row.updated_at, locale)}</span>,
      },
      ...(canWrite
        ? [
            {
              key: "actions",
              header: t("common.actions"),
              align: "right" as const,
              width: "80px",
              render: (row: StockItem) => (
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={t("common.delete")}
                  onClick={() => deleteMutation.mutate(row.id)}
                >
                  <Trash2 size={16} aria-hidden="true" />
                </button>
              ),
            },
          ]
        : []),
    ],
    [canWrite, deleteMutation, locale, t],
  );

  return (
    <>
      <PageHeader
        title={t("pharmacy.title")}
        subtitle={t("pharmacy.subtitle")}
        actions={
          canWrite ? (
            <label className="btn secondary">
              <Upload size={16} aria-hidden="true" />
              {t("pharmacy.importCsv")}
              <input
                type="file"
                accept=".csv,text/csv"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) importMutation.mutate(file);
                  event.currentTarget.value = "";
                }}
              />
            </label>
          ) : null
        }
      />

      <div className="toolbar-row" style={{ alignItems: "flex-start" }}>
        <div className="combobox" style={{ position: "relative", flex: 1, minWidth: 220 }}>
          <input
            className="input"
            role="combobox"
            aria-expanded={comboOpen && deferredQ.trim().length >= 2}
            aria-controls="pharmacy-typeahead-list"
            aria-autocomplete="list"
            placeholder={t("pharmacy.search")}
            value={grid.query}
            onChange={(event) => {
              grid.setQuery(event.target.value);
              setComboOpen(true);
            }}
            onFocus={() => setComboOpen(true)}
            onBlur={() => {
              // Allow click on option before closing.
              window.setTimeout(() => setComboOpen(false), 120);
            }}
          />
          <p className="muted small" style={{ margin: "4px 0 0" }}>
            {deferredQ.trim().length >= 2
              ? suggestionsQuery.isFetching
                ? t("common.loading")
                : suggestionTotal > 0
                  ? t("pharmacy.matchCount", {
                      shown: String(suggestionItems.length),
                      total: String(suggestionTotal),
                    })
                  : t("pharmacy.noMatches")
              : t("pharmacy.typeaheadHint")}
          </p>
          {comboOpen && deferredQ.trim().length >= 2 && suggestionItems.length > 0 ? (
            <ul
              id="pharmacy-typeahead-list"
              role="listbox"
              className="combo-list"
              style={{
                position: "absolute",
                zIndex: 20,
                left: 0,
                right: 0,
                top: "100%",
                margin: 0,
                padding: 0,
                listStyle: "none",
                background: "var(--surface, #fff)",
                border: "1px solid var(--border, #d0d5dd)",
                maxHeight: 240,
                overflow: "auto",
              }}
            >
              {suggestionItems.map((item) => (
                <li key={item.id} role="option">
                  <button
                    type="button"
                    className="combo-option"
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      padding: "8px 10px",
                      border: 0,
                      background: "transparent",
                      cursor: "pointer",
                    }}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      grid.setQuery(item.drug_name);
                      setClinic(item.clinic_code);
                      setComboOpen(false);
                    }}
                  >
                    <strong>{item.drug_name}</strong>
                    <span className="muted small" style={{ display: "block" }}>
                      {item.clinic_code} · qty {item.quantity}
                      {item.strength ? ` · ${item.strength}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <select
          className="input"
          value={clinic}
          onChange={(event) => setClinic(event.target.value)}
          aria-label={t("pharmacy.clinic")}
        >
          <option value="">{t("pharmacy.allClinics")}</option>
          <option value="BANER">BANER</option>
          <option value="KOTHRUD">KOTHRUD</option>
        </select>
      </div>

      {canWrite ? (
        <form
          className="panel stack-form"
          onSubmit={(event) => {
            event.preventDefault();
            saveMutation.mutate(draft);
          }}
        >
          <h3 className="section-title">
            <Plus size={16} aria-hidden="true" /> {t("pharmacy.addItem")}
          </h3>
          <div className="form-grid">
            <input
              className="input"
              required
              placeholder="SKU"
              value={draft.sku}
              onChange={(e) => setDraft({ ...draft, sku: e.target.value })}
            />
            <input
              className="input"
              required
              placeholder={t("pharmacy.drug")}
              value={draft.drug_name}
              onChange={(e) => setDraft({ ...draft, drug_name: e.target.value })}
            />
            <input
              className="input"
              placeholder={t("pharmacy.form")}
              value={draft.form}
              onChange={(e) => setDraft({ ...draft, form: e.target.value })}
            />
            <input
              className="input"
              placeholder={t("pharmacy.strength")}
              value={draft.strength}
              onChange={(e) => setDraft({ ...draft, strength: e.target.value })}
            />
            <input
              className="input"
              type="number"
              min={0}
              required
              placeholder={t("pharmacy.qty")}
              value={draft.quantity}
              onChange={(e) => setDraft({ ...draft, quantity: Number(e.target.value) })}
            />
            <select
              className="input"
              value={draft.clinic_code}
              onChange={(e) => setDraft({ ...draft, clinic_code: e.target.value })}
            >
              <option value="BANER">BANER</option>
              <option value="KOTHRUD">KOTHRUD</option>
            </select>
          </div>
          <button className="btn" type="submit" disabled={saveMutation.isPending}>
            <Package size={16} aria-hidden="true" /> {t("pharmacy.save")}
          </button>
        </form>
      ) : null}

      <DataGrid
        columns={columns}
        items={listQuery.data?.items}
        meta={listQuery.data?.meta}
        loading={listQuery.isFetching}
        error={listQuery.error}
        grid={grid}
        rowKey={(row) => row.id}
        onRetry={() => void listQuery.refetch()}
        hideSearch
        emptyTitle={t("pharmacy.noMatches")}
        emptyHint={t("pharmacy.typeaheadHint")}
      />
    </>
  );
}
