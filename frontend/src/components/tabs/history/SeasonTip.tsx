import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { formatIndexValue, formatMoney, formatSeason } from "../../../i18n/format";
import { pays, type SeasonResult } from "./chart";

type IndexType = components["schemas"]["IndexDefinition"]["index_type"];

interface SeasonTipProps {
  seasons: readonly SeasonResult[];
  /** The measure of the panel the tip belongs to: each panel speaks for its own. */
  measure: "index" | "payout";
  indexType: IndexType;
  active: boolean | undefined;
  /** The season under the pointer, as the time axis labels it. */
  label: string | number | undefined;
}

/** What a column says on hover: the season and the value of the panel's measure. */
export function SeasonTip({ seasons, measure, indexType, active, label }: SeasonTipProps) {
  const { locale } = useI18n();
  const season = seasons.find((item) => item.season === Number(label));
  if (active !== true || season === undefined) return null;
  return (
    <div className="chart-tip">
      <strong className="chart-tip__title num">{formatSeason(season.season)}</strong>
      {measure === "index" ? (
        <span className="chart-tip__line">
          {translate(locale, "history.tip.index")}{" "}
          <b className="num">{formatIndexValue(season.index_value, indexType, locale)}</b>
        </span>
      ) : (
        <span className="chart-tip__line">
          {pays(season) && season.payout !== null ? (
            <>
              {translate(locale, "history.tip.payout")}{" "}
              <b className="num">{formatMoney(season.payout.amount_cents, locale)}</b>
            </>
          ) : (
            translate(locale, "history.no_payout")
          )}
        </span>
      )}
    </div>
  );
}
