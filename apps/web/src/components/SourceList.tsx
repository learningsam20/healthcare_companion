import {
  Brain,
  FileText,
  MessageSquare,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";

import { formatDateTime } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { SourceRef } from "../lib/types";
import { StatusBadge, TypeBadge } from "./Badge";

const ICONS = {
  document: FileText,
  tool: Wrench,
  memory: Brain,
  conversation: MessageSquare,
  rule: ShieldCheck,
  general: Sparkles,
} as const;

export function SourceList({
  sources,
  compact = false,
}: {
  sources: SourceRef[];
  compact?: boolean;
}) {
  const { t, locale } = useI18n();
  if (!sources.length) {
    return <p className="muted">{t("common.noSources")}</p>;
  }
  return (
    <ul className={`source-list ${compact ? "is-compact" : ""}`}>
      {sources.map((source) => {
        const Icon = ICONS[source.type] ?? FileText;
        const nonEvidence = source.type === "memory" || source.type === "general";
        return (
          <li key={source.id} className="source-card">
            <div className="source-head">
              <span className="source-icon">
                <Icon size={15} aria-hidden="true" />
              </span>
              <div className="source-title">
                <span>{source.title}</span>
                {source.locator ? <code className="source-locator">{source.locator}</code> : null}
              </div>
              <TypeBadge type={source.type} />
              <StatusBadge status={source.status} />
            </div>
            {source.snippet && (!compact || source.type === "memory" || source.type === "conversation") ? (
              <p className="source-snippet">{source.snippet}</p>
            ) : null}
            <div className="source-meta muted">
              {nonEvidence ? <span>{t("chat.notClinical")}</span> : null}
              {source.observed_at ? (
                <span>{formatDateTime(source.observed_at, locale)}</span>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
