import type { ReactNode } from "react";

import { humanize } from "../lib/format";

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger" | "violet";

const STATUS_TONES: Record<string, BadgeTone> = {
  active: "success",
  confirmed: "success",
  held: "info",
  scheduled: "info",
  ok: "success",
  resolved: "success",
  passed: "success",
  signed: "success",
  read: "neutral",
  sent: "success",
  delivered: "success",
  completed: "success",
  ready: "success",
  indexed: "success",
  quarantined: "danger",
  verified: "success",
  configured: "success",
  enabled: "success",
  matched: "success",
  partial: "warning",
  insufficient_data: "warning",
  variance: "danger",
  draft: "warning",
  queued: "warning",
  processing: "warning",
  in_progress: "warning",
  new: "info",
  stale: "warning",
  unsourced: "warning",
  no_runs: "warning",
  unknown: "warning",
  unconfigured: "warning",
  unavailable: "warning",
  blocked: "danger",
  failed: "danger",
  missing: "danger",
  cancelled: "danger",
  no_show: "danger",
  rejected: "danger",
  dead_letter: "danger",
  forbidden: "danger",
  not_configured: "neutral",
  disabled: "neutral",
  suppressed: "neutral",
  closed: "neutral",
  open: "warning",
  claimed: "info",
  broken: "danger",
  never_run: "warning",
  empty: "info",
  unhashed: "warning",
  succeeded: "success",
  running: "info",
  real: "violet",
  synthetic: "warning",
  local: "success",
  external: "warning",
  emergency: "danger",
  urgent: "warning",
  soon: "warning",
  routine: "info",
};

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  title?: string;
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function StatusBadge({ status, label }: { status: string | null | undefined; label?: string }) {
  if (!status) return <span className="muted">—</span>;
  const tone = STATUS_TONES[status] ?? "neutral";
  return <Badge tone={tone}>{label ?? humanize(status)}</Badge>;
}

export function TypeBadge({ type }: { type: string }) {
  const tone: BadgeTone =
    type === "document" ? "info" : type === "tool" ? "violet" : type === "rule" ? "danger" : "neutral";
  return <Badge tone={tone}>{humanize(type)}</Badge>;
}
