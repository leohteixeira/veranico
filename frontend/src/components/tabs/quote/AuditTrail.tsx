import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { translateCoded, translateValue } from "../../../i18n/coded";
import { formatDate } from "../../../i18n/format";

type Coded = components["schemas"]["Coded"];

interface AuditTrailProps {
  audit: readonly components["schemas"]["AuditEntry"][];
  /** Carrier id to the directory's name, from the approvals queue; an unknown id is not shown. */
  carrierNames?: ReadonlyMap<string, string>;
}

/** The action with the carrier's name beside its id, so the sentence names the carrier. */
function withCarrierName(action: Coded, carrierNames: ReadonlyMap<string, string>): Coded {
  const carrierId = action.params?.carrier_id;
  const name = typeof carrierId === "string" ? carrierNames.get(carrierId) : undefined;
  return name === undefined
    ? action
    : { ...action, params: { ...action.params, carrier_name: name } };
}

/** Who did what to the quote, and when: each action is a code written in the visitor's language. */
export function AuditTrail({ audit, carrierNames = new Map() }: AuditTrailProps) {
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
            <span className="audit__action">
              {translateCoded(withCarrierName(entry.action, carrierNames), locale)}
            </span>
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
