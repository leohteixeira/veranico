import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { formatMoney, formatRate } from "../../../i18n/format";
import { FieldList } from "../FieldList";

interface SimulationProps {
  simulation: components["schemas"]["SimulationResult"];
  highlight: string | null;
}

/** What the simulation returned: the expected loss, its spread and the tail payouts. */
export function Simulation({ simulation, highlight }: SimulationProps) {
  const { locale } = useI18n();
  const money = (value: components["schemas"]["Money"]) => formatMoney(value.amount_cents, locale);
  return (
    <section className="quote__section">
      <h4>{translate(locale, "quote.simulation")}</h4>
      <FieldList
        highlight={highlight}
        fields={[
          {
            field: "expected_loss",
            label: translate(locale, "quote.expected_loss"),
            value: money(simulation.expected_loss),
          },
          {
            field: "std_dev",
            label: translate(locale, "quote.std_dev"),
            value: money(simulation.std_dev),
          },
          {
            field: "probability_of_payout",
            label: translate(locale, "quote.probability_of_payout"),
            value: formatRate(simulation.probability_of_payout, locale),
          },
          {
            field: "payout_1_in_10",
            label: translate(locale, "quote.payout_1_in_10"),
            value: money(simulation.payout_1_in_10),
          },
          {
            field: "payout_1_in_100",
            label: translate(locale, "quote.payout_1_in_100"),
            value: money(simulation.payout_1_in_100),
          },
          {
            field: "gap_to_burn_cost",
            label: translate(locale, "quote.gap_to_burn_cost"),
            value: money(simulation.gap_to_burn_cost),
          },
        ]}
      />
    </section>
  );
}
