import { Info, ShieldAlert } from "lucide-react";

import { formatDateTime, formatNumber } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { MetricTile } from "../lib/types";
import { StatusBadge } from "./Badge";

export function MetricTiles({ tiles }: { tiles: MetricTile[] }) {
  const { t, locale } = useI18n();
  return (
    <div className="metric-grid">
      {tiles.map((tile) => (
        <article className="metric-tile" key={tile.id}>
          <div className="metric-head">
            <span className="metric-label">{tile.label}</span>
            <StatusBadge status={tile.status} />
          </div>
          <div className="metric-value">
            {tile.suppressed ? (
              <span className="metric-suppressed" title={t("analytics.suppressed")}>
                <ShieldAlert size={18} aria-hidden="true" />
                {t("analytics.suppressed")}
              </span>
            ) : (
              <>
                <strong>{formatNumber(tile.value, locale)}</strong>
                <span className="metric-unit">{tile.unit}</span>
              </>
            )}
          </div>
          {tile.note ? (
            <p className="metric-note">
              <Info size={13} aria-hidden="true" />
              {tile.note}
            </p>
          ) : null}
          <details className="metric-details">
            <summary>{t("common.details")}</summary>
            <dl>
              <div>
                <dt>{t("analytics.source")}</dt>
                <dd>{tile.source ?? "—"}</dd>
              </div>
              <div>
                <dt>{t("analytics.formula")}</dt>
                <dd>{tile.formula ?? "—"}</dd>
              </div>
              <div>
                <dt>{t("analytics.asOf")}</dt>
                <dd>{formatDateTime(tile.as_of, locale)}</dd>
              </div>
              {tile.description ? (
                <div>
                  <dt>{t("common.details")}</dt>
                  <dd>{tile.description}</dd>
                </div>
              ) : null}
            </dl>
          </details>
        </article>
      ))}
    </div>
  );
}
