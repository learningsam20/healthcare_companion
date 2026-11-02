import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, setApiConsentId } from "./api";
import { useAuth } from "./auth";
import type { CareContext } from "./types";

const STORAGE_KEY = "sahyog.consent-id";
const CLEARED = "__none__";

interface CareContextValue {
  contexts: CareContext[];
  active: CareContext | null;
  loading: boolean;
  select: (context: CareContext | null) => Promise<void>;
  refresh: () => void;
}

const Context = createContext<CareContextValue | null>(null);

export function CareContextProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const isCaregiver = me.primary_role === "caregiver";
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    window.localStorage.getItem(STORAGE_KEY),
  );
  const activeId = selectedId === CLEARED ? null : selectedId;

  const query = useQuery({
    queryKey: ["me", "contexts"],
    queryFn: () => api<CareContext[]>("/api/v1/me/contexts"),
    enabled: isCaregiver,
    staleTime: 30_000,
  });

  useEffect(() => {
    setApiConsentId(isCaregiver ? activeId : null);
  }, [isCaregiver, activeId]);

  useEffect(() => {
    if (!isCaregiver) {
      if (selectedId !== null) {
        setSelectedId(null);
        window.localStorage.removeItem(STORAGE_KEY);
      }
      return;
    }
    const contexts = query.data;
    if (!contexts) return;
    if (
      selectedId &&
      selectedId !== CLEARED &&
      !contexts.some((item) => item.consent_id === selectedId)
    ) {
      setSelectedId(null);
      window.localStorage.removeItem(STORAGE_KEY);
      return;
    }
    if (selectedId === null && contexts.length === 1) {
      setSelectedId(contexts[0].consent_id);
      window.localStorage.setItem(STORAGE_KEY, contexts[0].consent_id);
    }
  }, [isCaregiver, query.data, selectedId]);

  const select = useCallback(
    async (context: CareContext | null) => {
      if (!context) {
        // Clear locally even if the audit call fails: leaving a stale context on screen
        // is worse than a missing clear event, and the consent stays valid server-side.
        await api<void>("/api/v1/me/context", { method: "DELETE" }).catch(() => undefined);
        setSelectedId(CLEARED);
        window.localStorage.setItem(STORAGE_KEY, CLEARED);
        setApiConsentId(null);
        return;
      }
      await api<CareContext>(`/api/v1/me/contexts/${context.consent_id}/activate`, {
        method: "POST",
      });
      setSelectedId(context.consent_id);
      window.localStorage.setItem(STORAGE_KEY, context.consent_id);
      setApiConsentId(context.consent_id);
      await queryClient.invalidateQueries();
    },
    [queryClient],
  );

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["me", "contexts"] });
  }, [queryClient]);

  const value = useMemo<CareContextValue>(() => {
    const contexts = isCaregiver ? (query.data ?? []) : [];
    return {
      contexts,
      active: contexts.find((item) => item.consent_id === activeId) ?? null,
      loading: query.isFetching,
      select,
      refresh,
    };
  }, [activeId, isCaregiver, query.data, query.isFetching, select, refresh]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useCareContext(): CareContextValue {
  const value = useContext(Context);
  if (!value) throw new Error("useCareContext must be used inside CareContextProvider");
  return value;
}
