import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { formatMoney, formatRate } from "../../../i18n/format";

interface PremiumProps {
  premium: components["schemas"]["Premium"];
  highlight: string | null;
}

/** The two figures the tab opens with: the indicative premium and the rate on line. */
export function Premium({ premium, highlight }: PremiumProps) {
  const { locale } = useI18n();
  return (
    <dl className="premium">
      <div data-field="premium" data-highlight={highlight === "premium" ? "true" : undefined}>
        <dt>{translate(locale, "quote.premium")}</dt>
        <dd className="premium__figure num">{formatMoney(premium.premium.amount_cents, locale)}</dd>
      </div>
      <div
        data-field="rate_on_line"
        data-highlight={highlight === "rate_on_line" ? "true" : undefined}
      >
        <dt>{translate(locale, "quote.rate_on_line")}</dt>
        <dd className="premium__rate num">{formatRate(premium.rate_on_line, locale)}</dd>
      </div>
    </dl>
  );
}
