import { AlertTriangle, Inbox, LoaderCircle, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p className="page-subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function Field({
  label,
  required,
  hint,
  children,
  className,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`field ${className ?? ""}`}>
      <span className="field-label">
        {label}
        {required ? <span className="required"> *</span> : null}
      </span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

export function Callout({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warning" | "danger" | "success";
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className={`callout callout-${tone}`} role={tone === "danger" ? "alert" : undefined}>
      {title ? <strong className="callout-title">{title}</strong> : null}
      <div>{children}</div>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  icon,
  action,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon ?? <Inbox size={22} aria-hidden="true" />}</div>
      <strong>{title}</strong>
      {hint ? <p className="muted">{hint}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  retryLabel = "Retry",
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div className="error-state" role="alert">
      <AlertTriangle size={20} aria-hidden="true" />
      <div>
        <strong>Request failed</strong>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          <RefreshCw size={14} aria-hidden="true" /> {retryLabel}
        </button>
      ) : null}
    </div>
  );
}

export function LoadingBlock({ label }: { label?: string }) {
  return (
    <div className="loading-block">
      <LoaderCircle className="spin" size={20} aria-hidden="true" />
      <span>{label ?? "Loading…"}</span>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="spinner-inline" role="status" aria-label={label ?? "Loading"}>
      <LoaderCircle className="spin" size={16} aria-hidden="true" />
    </span>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="form-error" role="alert">
      {message}
    </p>
  );
}

export interface TabItem {
  id: string;
  label: string;
  count?: number;
}

export function Tabs({
  items,
  active,
  onChange,
}: {
  items: TabItem[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={active === item.id}
          className={`tab ${active === item.id ? "is-active" : ""}`}
          onClick={() => onChange(item.id)}
        >
          {item.label}
          {item.count !== undefined ? <span className="tab-count">{item.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {hint ? <span className="stat-hint">{hint}</span> : null}
    </div>
  );
}

export function DefinitionList({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="definition-list">
      {items.map(([term, value]) => (
        <div key={term} className="definition-row">
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
