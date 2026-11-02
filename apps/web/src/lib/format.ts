const LOCALE_MAP: Record<string, string> = {
  "en-IN": "en-IN",
  "hi-IN": "hi-IN",
  "mr-IN": "mr-IN",
};

export function intlLocale(locale: string | undefined): string {
  return LOCALE_MAP[locale ?? ""] ?? "en-IN";
}

export function formatDateTime(
  value: string | null | undefined,
  locale: string,
  timeZone = "Asia/Kolkata",
): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(intlLocale(locale), {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(date);
}

export function formatDate(
  value: string | null | undefined,
  locale: string,
  timeZone = "Asia/Kolkata",
): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(intlLocale(locale), {
    dateStyle: "medium",
    timeZone,
  }).format(date);
}

export function toLocalInputValue(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60_000).toISOString().slice(0, 16);
}

export function formatNumber(value: number | string | null | undefined, locale: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  return new Intl.NumberFormat(intlLocale(locale), { maximumFractionDigits: 2 }).format(value);
}

export function formatCurrency(
  value: number | null | undefined,
  currency: string,
  locale: string,
): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(intlLocale(locale), {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}

export function truncate(value: string, length = 80): string {
  if (value.length <= length) return value;
  return `${value.slice(0, length - 1)}…`;
}

export function purposeLabel(purpose: string): string {
  return humanize(purpose);
}
