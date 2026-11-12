import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { formatMoney, formatNumber, formatRate, formatSeason } from "../../../i18n/format";

type BacktestResult = components["schemas"]["BacktestResult"];

interface AggregatesProps {
  backtest: BacktestResult;
  /** The field a figure link asked for (`burn_cost`, `max_payout`, `trigger_frequency`). */
  highlight: string | null;
}

/** The aggregates of the backtest, each one the API's value in the locale's notation. */
export function Aggregates({ backtest, highlight }: AggregatesProps) {
  const { locale } = useI18n();
  const largest = formatMoney(backtest.max_payout.amount_cents, locale);
  const rows: { field: string; label: string; value: string }[] = [
    {
      field: "seasons_used",
      label: translate(locale, "history.seasons_used"),
      value: formatNumber(backtest.seasons_used, locale),
    },
    {
      field: "trigger_frequency",
      label: translate(locale, "history.trigger_frequency"),
      value: formatRate(backtest.trigger_frequency, locale),
    },
    {
      field: "burn_cost",
      label: translate(locale, "history.burn_cost"),
      value: formatMoney(backtest.burn_cost.amount_cents, locale),
    },
    {
      field: "max_payout",
      label: translate(locale, "history.max_payout"),
      value:
        backtest.max_payout_season === null
          ? largest
          : translate(locale, "history.max_payout_in", {
              value: largest,
              season: formatSeason(backtest.max_payout_season),
            }),
    },
  ];
  if (backtest.seasons_excluded.length > 0) {
    rows.push({
      field: "seasons_excluded",
      label: translate(locale, "history.seasons_excluded"),
      value: backtest.seasons_excluded.map(formatSeason).join(", "),
    });
  }

  return (
    <dl className="aggregates" aria-label={translate(locale, "history.aggregates")}>
      {rows.map((row) => (
        <div
          key={row.field}
          className="aggregates__row"
          data-field={row.field}
          data-highlight={highlight === row.field ? "true" : undefined}
        >
          <dt>{row.label}</dt>
          <dd className="num">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
