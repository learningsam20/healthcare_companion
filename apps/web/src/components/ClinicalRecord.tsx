import { Badge, StatusBadge } from "./Badge";
import { humanize } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { DraftLine, MedicineDraft, ScribeDraft } from "../lib/types";

const SOAP: { key: "subjective" | "objective" | "assessment" | "plan"; letter: string }[] = [
  { key: "subjective", letter: "S" },
  { key: "objective", letter: "O" },
  { key: "assessment", letter: "A" },
  { key: "plan", letter: "P" },
];

export function ClinicalRecord({ content }: { content: ScribeDraft["content"] }) {
  const { t } = useI18n();
  const medicines = content.medicines ?? [];

  return (
    <div className="clinical-record" data-testid="clinical-record">
      <p className="clinical-record-label">{t("notes.clinicalRecord")}</p>
      {SOAP.map(({ key, letter }) => {
        const lines = content[key] ?? [];
        return (
          <section key={key}>
            <div className="clinical-section-head">
              <span className="soap-letter" aria-hidden="true">
                {letter}
              </span>
              <h4 className="section-title">{humanize(key)}</h4>
            </div>
            {lines.length ? (
              <ul className="draft-lines">
                {lines.map((line, index) => (
                  <Line key={`${key}-${index}`} line={line} />
                ))}
              </ul>
            ) : (
              <p className="muted clinical-empty">{t("notes.notRecorded")}</p>
            )}
          </section>
        );
      })}
      <section>
        <h4 className="section-title">{t("scribe.followUp")}</h4>
        {content.follow_up?.text ? (
          <p className="clinical-prose">{clinicalSentence(content.follow_up.text)}</p>
        ) : (
          <p className="muted clinical-empty">{t("notes.notRecorded")}</p>
        )}
      </section>
      <section>
        <h4 className="section-title">{t("notes.prescription")}</h4>
        {medicines.length ? (
          <div className="table-wrap">
            <table className="data-table compact">
              <thead>
                <tr>
                  <th>{t("scribe.medicine")}</th>
                  <th>{t("scribe.dose")}</th>
                  <th>{t("scribe.frequency")}</th>
                  <th>{t("scribe.duration")}</th>
                  <th>{t("notes.instructions")}</th>
                  <th>{t("scribe.stock")}</th>
                </tr>
              </thead>
              <tbody>
                {medicines.map((medicine, index) => (
                  <MedicineRow key={`${medicine.name}-${index}`} medicine={medicine} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted clinical-empty">{t("notes.notRecorded")}</p>
        )}
      </section>
    </div>
  );
}

function clinicalSentence(text: string): string {
  const label = "[doctor to specify]";
  const hasLabel = text.includes(label);
  let body = text.replaceAll(label, " ").replace(/\s+/g, " ").trim();
  body = body.replace(/\s+([,.;:!?])/g, "$1");
  if (!body) return text.trim();
  body = body.charAt(0).toUpperCase() + body.slice(1);
  if (!/[.!?]$/.test(body)) body += ".";
  return hasLabel ? `${body} ${label}` : body;
}

function Line({ line }: { line: DraftLine }) {
  const { t } = useI18n();
  return (
    <li className={line.unsourced ? "is-unsourced" : undefined}>
      <span>{clinicalSentence(line.text)}</span>
      {line.unsourced ? (
        <Badge tone="warning">{t("common.unsourced")}</Badge>
      ) : (
        <span className="citation-chips">
          {line.source_turn_ids.map((turn) => (
            <Badge key={turn} tone="neutral">
              {t("scribe.citation", { turn })}
            </Badge>
          ))}
        </span>
      )}
    </li>
  );
}

function MedicineRow({ medicine }: { medicine: MedicineDraft }) {
  const { t } = useI18n();
  return (
    <tr>
      <td>{medicine.name}</td>
      <td>{medicine.dose ?? "—"}</td>
      <td>{medicine.frequency ?? "—"}</td>
      <td>{medicine.duration ?? "—"}</td>
      <td>{medicine.instructions ?? "—"}</td>
      <td>
        {medicine.stock?.status ? (
          <StatusBadge
            status={medicine.stock.stale ? "stale" : medicine.stock.status}
            label={
              medicine.stock.status === "unknown"
                ? t("scribe.stockUnknown")
                : medicine.stock.stale
                  ? t("scribe.stockStale")
                  : humanize(medicine.stock.status)
            }
          />
        ) : (
          <span className="muted">—</span>
        )}
      </td>
    </tr>
  );
}
