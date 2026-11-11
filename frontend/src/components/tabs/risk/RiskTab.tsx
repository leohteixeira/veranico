import type { components } from "../../../api/schema";
import type { BasemapId } from "../../../config";
import type { Theme } from "../../../design/theme";
import { translate, useI18n } from "../../../i18n";
import { formatNumber, formatSeason } from "../../../i18n/format";
import { cellAt, neighbourRange, valueAt, type LatLon } from "../../../map/geometry";
import { Icon } from "../../common/Icon";
import { Note } from "../../common/Note";
import { TabEmpty, TabState, type DataStatus } from "../TabState";
import { cellValueText } from "./cellText";
import { Legend } from "./Legend";
import { Neighbourhood } from "./Neighbourhood";

import "../tabs.css";

type CellGrid = components["schemas"]["CellGrid"];

interface RiskTabProps {
  /** `GET /regions/{id}/cells` for the metric in view, or `null` while there is none. */
  grid: CellGrid | null;
  /** The insured point; its cell is the one the tab reads. */
  point: LatLon | null;
  /** The season on the map, when the grid is a season's anomaly. */
  season: number | null;
  status?: DataStatus;
  onRetry?: () => void;
  theme: Theme;
  basemap: BasemapId;
  /** `Region.synthetic`: the figures are generated for the demo, not weather history. */
  synthetic?: boolean;
}

/**
 * The Risk tab: the insured cell's figure, the range of its neighbours, one sentence that reads
 * them, the three-by-three neighbourhood and the legend. Every figure is a cell value of the API;
 * the only thing derived here is the lowest and highest value among the returned neighbours.
 */
export function RiskTab({
  grid,
  point,
  season,
  status = "ready",
  onRetry,
  theme,
  basemap,
  synthetic = false,
}: RiskTabProps) {
  const { locale } = useI18n();
  if (grid === null) {
    return status === "ready" ? (
      <TabEmpty>{translate(locale, "risk.empty")}</TabEmpty>
    ) : (
      <TabState status={status} onRetry={onRetry} />
    );
  }

  const cell = point === null ? null : cellAt(grid, point.lat, point.lon);
  const value = cell === null ? null : valueAt(grid, cell.row, cell.col);
  const range = cell === null ? null : neighbourRange(grid, cell.row, cell.col);
  const text = (number: number) => cellValueText(number, grid.metric, locale);
  const rangeText =
    range === null
      ? null
      : translate(locale, "risk.range", { min: text(range.min), max: text(range.max) });
  const seasonal = grid.metric === "season_anomaly" && season !== null;

  let reading: string | null = null;
  if (value !== null && seasonal) {
    const params = { season: formatSeason(season), anomaly: text(value) };
    reading =
      grid.cells_paying === null
        ? translate(locale, "risk.reading.season_plain", params)
        : translate(locale, "risk.reading.season", {
            ...params,
            paying: formatNumber(grid.cells_paying, locale),
            cells: formatNumber(grid.values.filter((item) => item !== null).length, locale),
          });
  } else if (value !== null && range !== null && grid.metric === "trigger_frequency") {
    reading = translate(locale, "risk.reading.frequency", {
      rate: text(value),
      seasons: formatNumber(grid.seasons.length, locale),
      min: text(range.min),
      max: text(range.max),
    });
  }

  return (
    <div className="risk" data-metric={grid.metric}>
      {synthetic && (
        <Note tone="warn" icon={<Icon name="warn" />} data-note="synthetic">
          {translate(locale, "app.synthetic")}
        </Note>
      )}
      {cell === null ? (
        <TabEmpty>{translate(locale, "risk.no_cell")}</TabEmpty>
      ) : (
        <>
          <dl className="risk__stats">
            <div className="risk__stat" data-field="cell">
              <dt>{translate(locale, "risk.cell")}</dt>
              <dd className="risk__figure num">
                {value === null ? translate(locale, "risk.cell.no_value") : text(value)}
              </dd>
            </div>
            {rangeText !== null && (
              <div className="risk__stat" data-field="neighbours">
                <dt>{translate(locale, "risk.neighbours")}</dt>
                <dd className="risk__range num">{rangeText}</dd>
              </div>
            )}
          </dl>
          {reading !== null && <p className="risk__reading">{reading}</p>}
          <Neighbourhood grid={grid} cell={cell} theme={theme} basemap={basemap} />
        </>
      )}
      <Legend metric={grid.metric} breaks={grid.breaks} theme={theme} basemap={basemap} />
    </div>
  );
}
