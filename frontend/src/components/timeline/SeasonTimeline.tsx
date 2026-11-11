import type { components } from "../../api/schema";
import type { BasemapConfig } from "../../config";
import { useI18n } from "../../i18n";
import { formatIndexValue, formatMoney, formatSeason } from "../../i18n/format";
import { Attribution } from "../../map/Attribution";
import { Button } from "../common/Button";
import { Card } from "../common/Card";
import { Spinner } from "../common/Spinner";
import { TimelineBars, pays } from "./TimelineBars";
import "./timeline.css";

type Schemas = components["schemas"];
type SeasonResult = Schemas["SeasonResult"];

interface SeasonTimelineProps {
  /** The seasons of the insured point, oldest first; `null` while there is no series. */
  seasons: readonly SeasonResult[] | null;
  /** The index the series was computed for: its trigger line and its unit. */
  index: Schemas["IndexDefinition"] | null;
  /** The season on the map; `null` is the view of all seasons. */
  selected: number | null;
  /** The season the API suggests for a first look (`CellGrid.suggested_season`). */
  suggested: number | null;
  onSelect: (season: number | null) => void;
  status?: "ready" | "loading" | "failed";
  onRetry?: () => void;
  /** The basemap on screen: the card carries its attribution. */
  basemap: BasemapConfig;
  className?: string;
}

/**
 * The season timeline card: one bar per season, drag or arrow keys to put one season on the map,
 * "All seasons" to go back. The attribution of the map and the pricing disclaimer sit at its foot.
 */
export function SeasonTimeline({
  seasons,
  index,
  selected,
  suggested,
  onSelect,
  status = "ready",
  onRetry,
  basemap,
  className,
}: SeasonTimelineProps) {
  const { t, locale } = useI18n();
  const series = seasons !== null && seasons.length > 0 && index !== null ? seasons : null;
  const first = series?.[0];
  const last = series?.[series.length - 1];
  const selectedAt =
    series === null || selected === null
      ? -1
      : series.findIndex((season) => season.season === selected);
  const current = selectedAt >= 0 ? series?.[selectedAt] : undefined;
  const hasPayouts = series?.some((season) => season.payout !== null) ?? false;

  const describe = (season: SeasonResult): string => {
    if (index === null) return formatSeason(season.season);
    const value = formatIndexValue(season.index_value, index.index_type, locale);
    return pays(season) && season.payout !== null
      ? t("timeline.season_payout", {
          season: formatSeason(season.season),
          value,
          payout: formatMoney(season.payout.amount_cents, locale),
        })
      : t("timeline.season", { season: formatSeason(season.season), value });
  };

  /** Entering the season view without a selection opens on the season the API suggests. */
  const enterSeasonView = () => {
    if (series === null || last === undefined) return;
    const known = suggested !== null && series.some((season) => season.season === suggested);
    onSelect(known && suggested !== null ? suggested : last.season);
  };

  const classes = className === undefined ? "timeline" : `timeline ${className}`;
  return (
    <Card as="section" className={classes} aria-label={t("timeline.label")}>
      {series !== null && index !== null && first !== undefined && last !== undefined ? (
        <>
          <div className="timeline__head">
            <div className="timeline__what">
              <p className="timeline__readout num" aria-live="polite">
                {current === undefined
                  ? `${formatSeason(first.season)}–${formatSeason(last.season)}`
                  : describe(current)}
              </p>
              <p className="timeline__legend">
                {hasPayouts && (
                  <span className="timeline__key timeline__key--pay">
                    {t("timeline.legend_payout")}
                  </span>
                )}
                <span className="timeline__key timeline__key--trigger">
                  {t("timeline.legend_trigger", {
                    value: formatIndexValue(index.trigger, index.index_type, locale),
                  })}
                </span>
              </p>
            </div>
            {current === undefined ? (
              <Button variant="link" onClick={enterSeasonView}>
                {t("timeline.season_view")}
              </Button>
            ) : (
              <Button
                variant="link"
                onClick={() => {
                  onSelect(null);
                }}
              >
                {t("timeline.all_seasons")}
              </Button>
            )}
          </div>
          <div className="timeline__track" title={t("timeline.hint")}>
            <TimelineBars
              seasons={series}
              trigger={index.trigger}
              selected={current?.season ?? null}
              onSelect={onSelect}
              describe={describe}
            />
            {/* The keyboard's handle on the same selection: arrows move one season at a time. */}
            <input
              className="timeline__range"
              type="range"
              min={0}
              max={series.length - 1}
              step={1}
              value={selectedAt >= 0 ? selectedAt : series.length - 1}
              aria-label={t("timeline.range_label")}
              aria-valuetext={current === undefined ? t("timeline.all_seasons") : describe(current)}
              onChange={(event) => {
                const season = series[Number(event.target.value)];
                if (season !== undefined) onSelect(season.season);
              }}
            />
          </div>
        </>
      ) : status === "failed" ? (
        <div className="timeline__state" role="alert">
          <span>{t("timeline.failed")}</span>
          {onRetry !== undefined && (
            <Button variant="link" onClick={onRetry}>
              {t("action.retry")}
            </Button>
          )}
        </div>
      ) : (
        <div className="timeline__state" role="status">
          {status === "loading" && (
            <>
              <Spinner />
              <span>{t("timeline.loading")}</span>
            </>
          )}
        </div>
      )}
      <Attribution basemap={basemap} className="timeline__attribution" />
    </Card>
  );
}
