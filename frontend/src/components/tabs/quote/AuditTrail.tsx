import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { translateCoded, translateValue } from "../../../i18n/coded";
import { formatDate } from "../../../i18n/format";

interface AuditTrailProps {
  audit: readonly components["schemas"]["AuditEntry"][];
}

/** Who did what to the quote, and when: each action is a code written in the visitor's language. */
export function AuditTrail({ audit }: AuditTrailProps) {
  const { locale } = useI18n();
  if (audit.length === 0) return null;
  return (
    <section className="quote__section">
      <h4>{translate(locale, "quote.audit")}</h4>
      <ol className="audit">
        {audit.map((entry, at) => (
          <li key={`${entry.at}-${at}`} className="audit__entry" data-action={entry.action.code}>
            <span className="audit__meta">
              <time dateTime={entry.at} className="num">
                {formatDate(entry.at, locale)}
              </time>
              {" · "}
              <span data-actor={entry.actor}>{translateValue("actor", entry.actor, locale)}</span>
            </span>
            <span className="audit__action">{translateCoded(entry.action, locale)}</span>
            {entry.note !== null && entry.note !== undefined && entry.note !== "" && (
              <span className="audit__note">
                {translate(locale, "quote.audit.note", { note: entry.note })}
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
