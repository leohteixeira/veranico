import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { translateCoded } from "../../../i18n/coded";

interface AssumptionsProps {
  assumptions: readonly components["schemas"]["Coded"][];
}

/** The assumptions behind the price, each a code of the API written in the visitor's language. */
export function Assumptions({ assumptions }: AssumptionsProps) {
  const { locale } = useI18n();
  if (assumptions.length === 0) return null;
  return (
    <section className="quote__section">
      <h4>{translate(locale, "quote.assumptions")}</h4>
      <ul className="quote__assumptions">
        {assumptions.map((assumption, at) => (
          <li key={`${assumption.code}-${at}`} data-assumption={assumption.code}>
            {translateCoded(assumption, locale)}
          </li>
        ))}
      </ul>
    </section>
  );
}
