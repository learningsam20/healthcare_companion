import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Search,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import type { GridMeta } from "../lib/types";
import { errorMessage } from "../lib/api";
import { useI18n } from "../lib/i18n";
import type { GridState } from "../lib/grid";
import { EmptyState, ErrorState } from "./primitives";
import { IconButton } from "./IconButton";

export interface DataGridColumn<T> {
  key: string;
  header: string;
  sortKey?: string;
  render: (row: T) => ReactNode;
  align?: "left" | "right" | "center";
  width?: string;
  hideOnMobile?: boolean;
}

interface DataGridProps<T> {
  columns: DataGridColumn<T>[];
  items: T[] | undefined;
  meta: GridMeta | null | undefined;
  loading: boolean;
  error: unknown;
  grid: GridState;
  rowKey: (row: T) => string;
  onRetry?: () => void;
  onRowClick?: (row: T) => void;
  searchPlaceholder?: string;
  filters?: ReactNode;
  actions?: ReactNode;
  emptyTitle?: string;
  emptyHint?: string;
  emptyAction?: ReactNode;
  hideSearch?: boolean;
}

const PAGE_SIZES = [10, 20, 50, 100];

export function DataGrid<T>({
  columns,
  items,
  meta,
  loading,
  error,
  grid,
  rowKey,
  onRetry,
  onRowClick,
  searchPlaceholder,
  filters,
  actions,
  emptyTitle,
  emptyHint,
  emptyAction,
  hideSearch = false,
}: DataGridProps<T>) {
  const { t } = useI18n();
  const [search, setSearch] = useState(grid.query);
  const [debounced, setDebounced] = useState(grid.query);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search), 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (debounced !== grid.query) grid.setQuery(debounced);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  useEffect(() => {
    if (grid.query !== search) {
      setSearch(grid.query);
      setDebounced(grid.query);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid.query]);

  const total = meta?.total ?? 0;
  const pages = meta?.pages ?? 0;
  const page = meta?.page ?? grid.page;
  const pageSize = meta?.page_size ?? grid.pageSize;
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  const busy = loading && !items;

  return (
    <section className="grid-panel" aria-busy={loading}>
      {!hideSearch || actions ? (
        <div className="grid-toolbar">
          {!hideSearch ? (
            <div className="search-box">
              <Search size={16} aria-hidden="true" />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
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
                    setSearch("");
                    setDebounced("");
                    grid.setQuery("");
                  }}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              ) : null}
            </div>
          ) : null}
          {actions ? <div className="grid-toolbar-actions">{actions}</div> : null}
        </div>
      ) : null}

      {filters ? <div className="grid-filters">{filters}</div> : null}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((column) => {
                const sortable = Boolean(column.sortKey);
                const active = sortable && grid.sort === column.sortKey;
                const ariaSort = active ? (grid.order === "asc" ? "ascending" : "descending") : "none";
                return (
                  <th
                    key={column.key}
                    scope="col"
                    style={column.width ? { width: column.width } : undefined}
                    className={`${column.align ? `align-${column.align}` : ""} ${
                      column.hideOnMobile ? "hide-mobile" : ""
                    }`}
                    aria-sort={ariaSort}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        className={`sort-button ${active ? "is-active" : ""}`}
                        onClick={() => grid.toggleSort(column.sortKey as string)}
                      >
                        {column.header}
                        {active ? (
                          grid.order === "asc" ? (
                            <ArrowUp size={13} aria-hidden="true" />
                          ) : (
                            <ArrowDown size={13} aria-hidden="true" />
                          )
                        ) : (
                          <ArrowUpDown size={13} aria-hidden="true" />
                        )}
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {error ? (
              <tr>
                <td colSpan={columns.length}>
                  <ErrorState
                    message={errorMessage(error) || t("common.errorTitle")}
                    onRetry={onRetry}
                    retryLabel={t("common.retry")}
                  />
                </td>
              </tr>
            ) : busy ? (
              Array.from({ length: 4 }).map((_, index) => (
                <tr key={`skeleton-${index}`} className="skeleton-row">
                  {columns.map((column) => (
                    <td key={column.key}>
                      <span className="skeleton" style={{ width: `${55 + (index * 13) % 40}%` }} />
                    </td>
                  ))}
                </tr>
              ))
            ) : !items || items.length === 0 ? (
              <tr>
                <td colSpan={columns.length}>
                  <EmptyState
                    title={emptyTitle ?? t("common.emptyTitle")}
                    hint={emptyHint ?? t("common.emptyHint")}
                    action={emptyAction}
                  />
                </td>
              </tr>
            ) : (
              items.map((row) => (
                <tr
                  key={rowKey(row)}
                  className={onRowClick ? "is-clickable" : undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                  onKeyDown={
                    onRowClick
                      ? (event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={`${column.align ? `align-${column.align}` : ""} ${
                        column.hideOnMobile ? "hide-mobile" : ""
                      }`}
                    >
                      {column.render(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

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
