import { useCallback, useMemo, useState } from "react";

import type { QueryValue } from "./api";

export type SortOrder = "asc" | "desc";

export interface GridState {
  page: number;
  pageSize: number;
  query: string;
  sort: string;
  order: SortOrder;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  setQuery: (query: string) => void;
  setSort: (sort: string) => void;
  setOrder: (order: SortOrder) => void;
  toggleSort: (column: string) => void;
  resetPage: () => void;
  params: Record<string, QueryValue>;
}

export function useGridState(
  defaultSort: string,
  defaultOrder: SortOrder = "desc",
): GridState {
  const [page, setPageState] = useState(1);
  const [pageSize, setPageSizeState] = useState(20);
  const [query, setQueryState] = useState("");
  const [sort, setSortState] = useState(defaultSort);
  const [order, setOrderState] = useState<SortOrder>(defaultOrder);

  const setPage = useCallback((next: number) => setPageState(Math.max(1, next)), []);
  const setPageSize = useCallback((next: number) => {
    setPageSizeState(next);
    setPageState(1);
  }, []);
  const setQuery = useCallback((next: string) => {
    setQueryState(next);
    setPageState(1);
  }, []);
  const setSort = useCallback((next: string) => {
    setSortState(next);
    setPageState(1);
  }, []);
  const setOrder = useCallback((next: SortOrder) => {
    setOrderState(next);
    setPageState(1);
  }, []);
  const toggleSort = useCallback(
    (column: string) => {
      setPageState(1);
      if (sort === column) {
        setOrderState((current) => (current === "asc" ? "desc" : "asc"));
      } else {
        setSortState(column);
        setOrderState("asc");
      }
    },
    [sort],
  );
  const resetPage = useCallback(() => setPageState(1), []);

  const params = useMemo(
    () => ({ page, page_size: pageSize, q: query || undefined, sort, order }),
    [page, pageSize, query, sort, order],
  );

  return {
    page,
    pageSize,
    query,
    sort,
    order,
    setPage,
    setPageSize,
    setQuery,
    setSort,
    setOrder,
    toggleSort,
    resetPage,
    params,
  };
}
