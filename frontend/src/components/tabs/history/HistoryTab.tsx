import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { translateCoded } from "../../../i18n/coded";
import { formatIndexValue, formatMoney, formatSeason } from "../../../i18n/format";
import { Button } from "../../common/Button";
import { Icon } from "../../common/Icon";
import { Note } from "../../common/Note";
import { TabEmpty, TabState, type DataStatus } from "../TabState";
import { Aggregates } from "./Aggregates";
import { pays, type SeasonResult } from "./chart";
import { IndexChart } from "./IndexChart";
import { PayoutChart } from "./PayoutChart";
import { SeasonTable } from "./SeasonTable";

import "../tabs.css";

type Schemas = components["schemas"];

interface HistoryTabProps {
  /** The latest backtest, from the agent's tool result or from the quote; `null` before any. */
  backtest: Schemas["BacktestResult"] | null;
  /** The selected season, shared with the timeline and the map; `null` is all seasons. */
  season: number | null;
  onSelectSeason: (season: number | null) => void;
  status?: DataStatus;
  onRetry?: () => void;
  /** The field a figure link asked the tab to highlight. */
  highlight?: string | null;
}

const TREND_WARNING = "warning.trend_significant";

/**
 * The History tab: the index per season with its trigger and exit, the payout per season below on
 * the same time axis, the trend warning when the trend is significant, the aggregates and a table
 * of every season. A bar, a table row or the arrow keys select the season the map shows.
 */
export function HistoryTab({
  backtest,
  season,
  onSelectSeason,
  status = "ready",
  onRetry,
  highlight = null,
}: HistoryTabProps) {
  const { locale } = useI18n();
  if (backtest === null) {
    return status === "ready" ? (
      <TabEmpty>{translate(locale, "history.empty")}</TabEmpty>
    ) : (
      <TabState status={status} onRetry={onRetry} />
    );
  }

  const { seasons, cover, trend } = backtest;
  const { index } = cover;
  const selectedAt = season === null ? -1 : seasons.findIndex((item) => item.season === season);
  const current = selectedAt >= 0 ? seasons[selectedAt] : undefined;
  const first = seasons[0];
  const last = seasons[seasons.length - 1];

  const describe = (item: SeasonResult): string => {
    const value = formatIndexValue(item.index_value, index.index_type, locale);
    return pays(item) && item.payout !== null
      ? translate(locale, "timeline.season_payout", {
          season: formatSeason(item.season),
          value,
          payout: formatMoney(item.payout.amount_cents, locale),
        })
      : translate(locale, "timeline.season", { season: formatSeason(item.season), value });
  };

  // The trend warning is shown only for a significant trend; other warnings always are.
  const warnings = backtest.warnings.filter(
    (warning) => warning.code !== TREND_WARNING || trend.significant,
  );
  if (trend.significant && !warnings.some((warning) => warning.code === TREND_WARNING)) {
    warnings.unshift({ code: TREND_WARNING, params: {} });
  }

  return (
    <div className="history">
      <div className="history__head">
        <p className="history__readout num" aria-live="polite">
          {current !== undefined
            ? describe(current)
            : first !== undefined && last !== undefined
              ? `${formatSeason(first.season)}–${formatSeason(last.season)}`
              : ""}
        </p>
        {current !== undefined && (
          <Button
            variant="link"
            onClick={() => {
              onSelectSeason(null);
            }}
          >
            {translate(locale, "timeline.all_seasons")}
          </Button>
        )}
      </div>

      <div className="history__charts" title={translate(locale, "history.hint")}>
        <figure
          className="history__panel"
          data-highlight={highlight === "trigger" || highlight === "exit" ? "true" : undefined}
        >
          <figcaption>{translate(locale, `history.index_title.${index.index_type}`)}</figcaption>
          <IndexChart
            seasons={seasons}
            index={index}
            selected={current?.season ?? null}
            onSelect={onSelectSeason}
          />
        </figure>
        <figure className="history__panel">
          <figcaption>{translate(locale, "history.payout_title")}</figcaption>
          <PayoutChart
            seasons={seasons}
            indexType={index.index_type}
            limit={cover.limit}
            selected={current?.season ?? null}
            onSelect={onSelectSeason}
          />
        </figure>
        {/* The keyboard's handle on the selection: arrows move one season at a time. */}
        {seasons.length > 0 && (
          <input
            className="history__range"
            type="range"
            min={0}
            max={seasons.length - 1}
            step={1}
            value={selectedAt >= 0 ? selectedAt : seasons.length - 1}
            aria-label={translate(locale, "history.range_label")}
            aria-valuetext={
              current === undefined ? translate(locale, "timeline.all_seasons") : describe(current)
            }
            onChange={(event) => {
              const next = seasons[Number(event.target.value)];
              if (next !== undefined) onSelectSeason(next.season);
            }}
          />
        )}
      </div>

      {warnings.map((warning) => (
        <Note
          key={warning.code}
          tone="warn"
          icon={<Icon name="warn" />}
          data-warning={warning.code}
        >
          {translateCoded(warning, locale)}
        </Note>
      ))}

      <Aggregates backtest={backtest} highlight={highlight} />
      <SeasonTable
        seasons={seasons}
        indexType={index.index_type}
        selected={current?.season ?? null}
        onSelect={onSelectSeason}
      />
    </div>
  );
}
