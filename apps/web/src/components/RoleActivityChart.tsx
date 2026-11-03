import { formatNumber, humanize } from "../lib/format";
import { useI18n } from "../lib/i18n";

export interface RoleActivityRow {
  role?: string;
  count?: number;
}

const ROLE_COLORS: Record<string, string> = {
  patient: "var(--info)",
  doctor: "var(--primary)",
  front_desk: "var(--warning)",
  caregiver: "var(--violet)",
  pharmacist: "var(--success)",
  nurse: "#0ea5e9",
  admin: "var(--danger)",
  compliance: "#64748b",
  service: "#94a3b8",
};

const FALLBACK_COLORS = [
  "var(--primary)",
  "var(--info)",
  "var(--warning)",
  "var(--violet)",
  "var(--success)",
  "var(--danger)",
  "#0ea5e9",
  "#64748b",
];

function colorFor(role: string | undefined, index: number): string {
  if (role && ROLE_COLORS[role]) return ROLE_COLORS[role];
  return FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

/** Polar → cartesian for SVG donut arcs. */
function arcPath(
  cx: number,
  cy: number,
  radius: number,
  startAngle: number,
  endAngle: number,
): string {
  const start = {
    x: cx + radius * Math.cos(startAngle),
    y: cy + radius * Math.sin(startAngle),
  };
  const end = {
    x: cx + radius * Math.cos(endAngle),
    y: cy + radius * Math.sin(endAngle),
  };
  const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
  return [
    `M ${start.x} ${start.y}`,
    `A ${radius} ${radius} 0 ${largeArc} 1 ${end.x} ${end.y}`,
  ].join(" ");
}

export function RoleActivityChart({
  rows,
  title,
}: {
  rows: RoleActivityRow[];
  title?: string;
}) {
  const { t, locale } = useI18n();
  const sorted = [...rows]
    .map((row) => ({
      role: row.role ?? "unknown",
      count: Math.max(0, row.count ?? 0),
    }))
    .filter((row) => row.count > 0)
    .sort((a, b) => b.count - a.count);

  const total = sorted.reduce((sum, row) => sum + row.count, 0);
  if (!sorted.length || total === 0) {
    return (
      <div className="role-activity-chart is-empty">
        {title ? <h3 className="section-title">{title}</h3> : null}
        <p className="muted small">{t("analytics.notConfigured")}</p>
      </div>
    );
  }

  const size = 168;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 62;
  const stroke = 22;
  const gap = sorted.length > 1 ? 0.04 : 0;
  let angle = -Math.PI / 2;

  const slices = sorted.map((row, index) => {
    const share = row.count / total;
    const sweep = Math.max(share * Math.PI * 2 - gap, 0.02);
    const start = angle;
    const end = angle + sweep;
    angle = end + gap;
    return {
      ...row,
      share,
      color: colorFor(row.role, index),
      path: arcPath(cx, cy, radius, start, end),
    };
  });

  return (
    <div className="role-activity-chart">
      {title ? <h3 className="section-title">{title}</h3> : null}
      <div className="role-activity-body">
        <div className="role-donut-wrap">
          <svg
            className="role-donut"
            viewBox={`0 0 ${size} ${size}`}
            role="img"
            aria-label={title ?? t("analytics.activeByRole")}
          >
            <circle
              cx={cx}
              cy={cy}
              r={radius}
              fill="none"
              stroke="var(--surface-3)"
              strokeWidth={stroke}
            />
            {slices.map((slice) => (
              <path
                key={slice.role}
                d={slice.path}
                fill="none"
                stroke={slice.color}
                strokeWidth={stroke}
                strokeLinecap="butt"
              >
                <title>
                  {humanize(slice.role)}: {formatNumber(slice.count, locale)} (
                  {formatNumber(Math.round(slice.share * 100), locale)}%)
                </title>
              </path>
            ))}
          </svg>
          <div className="role-donut-center" aria-hidden="true">
            <strong>{formatNumber(total, locale)}</strong>
            <span>{t("analytics.activeTotal")}</span>
          </div>
        </div>
        <ul className="role-legend">
          {slices.map((slice) => (
            <li key={slice.role}>
              <span className="role-swatch" style={{ background: slice.color }} />
              <span className="role-legend-label">{humanize(slice.role)}</span>
              <span className="role-legend-share">
                {formatNumber(Math.round(slice.share * 100), locale)}%
              </span>
              <span className="role-legend-count">{formatNumber(slice.count, locale)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
