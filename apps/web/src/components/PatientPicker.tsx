import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Search, UserRound, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, qs } from "../lib/api";
import { useI18n } from "../lib/i18n";
import type { GridResponse, Patient } from "../lib/types";
import { useOutsideClose } from "./IconButton";

export function PatientPicker({
  value,
  onChange,
  disabled = false,
}: {
  value: Patient | null;
  onChange: (patient: Patient | null) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const container = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useOutsideClose(container, () => setOpen(false), open);

  const results = useQuery({
    queryKey: ["patient-picker", debounced],
    queryFn: () =>
      api<GridResponse<Patient>>(
        `/api/v1/patients${qs({ page_size: 8, sort: "display_name", order: "asc", q: debounced || undefined })}`,
      ),
    enabled: open,
    staleTime: 15_000,
  });

  return (
    <div className="patient-picker" ref={container}>
      <button
        type="button"
        className="picker-trigger"
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        data-testid="patient-picker-trigger"
      >
        <UserRound size={16} aria-hidden="true" />
        <span className={value ? "" : "muted"}>
          {value
            ? value.display_name ?? `Patient ${value.id.slice(0, 8)}`
            : t("appointments.choosePatient")}
        </span>
        <ChevronDown size={15} aria-hidden="true" />
      </button>
      {value ? (
        <button
          type="button"
          className="picker-clear"
          aria-label={t("common.clear")}
          onClick={() => onChange(null)}
        >
          <X size={14} aria-hidden="true" />
        </button>
      ) : null}

      {open ? (
        <div className="picker-popover">
          <div className="search-box search-box-sm">
            <Search size={15} aria-hidden="true" />
            <input
              autoFocus
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("patients.searchPlaceholder")}
              aria-label={t("patients.searchPlaceholder")}
            />
          </div>
          <div className="picker-results" role="listbox" aria-label={t("common.patient")}>
            {results.isPending ? (
              <p className="picker-note muted">{t("common.loading")}</p>
            ) : results.isError ? (
              <p className="picker-note form-error">{t("common.errorTitle")}</p>
            ) : !results.data?.items.length ? (
              <p className="picker-note muted">{t("common.emptyTitle")}</p>
            ) : (
              results.data.items.map((patient) => (
                <button
                  key={patient.id}
                  type="button"
                  role="option"
                  aria-selected={value?.id === patient.id}
                  data-testid="patient-picker-option"
                  className={`picker-option ${value?.id === patient.id ? "is-selected" : ""}`}
                  onClick={() => {
                    onChange(patient);
                    setOpen(false);
                    setQuery("");
                  }}
                >
                  <span>{patient.display_name ?? `Patient ${patient.id.slice(0, 8)}`}</span>
                  <span className="muted mono">{patient.id.slice(0, 8)}</span>
                </button>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
