import { Bar, BarChart, Cell, ReferenceLine, Tooltip, XAxis, YAxis } from "recharts";

import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { formatIndexValue, formatNumber } from "../../../i18n/format";
import {
  CHART_MARGIN,
  SYNC_ID,
  Y_AXIS_WIDTH,
  barFill,
  barOpacity,
  decadeTicks,
  seasonAtX,
  useChartWidth,
  type SeasonResult,
} from "./chart";
import { SeasonTip } from "./SeasonTip";

type IndexDefinition = components["schemas"]["IndexDefinition"];

interface IndexChartProps {
  seasons: readonly SeasonResult[];
  /** The index the seasons were computed for: its unit, its trigger and its exit. */
  index: IndexDefinition;
  selected: number | null;
  onSelect: (season: number) => void;
}

const HEIGHT = 150;

/**
 * The index per season, with the trigger and the exit as reference lines named in the key above
 * the plot (a label inside a plot this dense would sit on the bars). One value axis: the payouts
 * are another measure and have their own panel below, on the same time axis.
 */
export function IndexChart({ seasons, index, selected, onSelect }: IndexChartProps) {
  const { locale } = useI18n();
  const [frame, width] = useChartWidth();
  const value = (amount: number) => formatIndexValue(amount, index.index_type, locale);

  return (
    <>
      <p className="chart-key">
        <span className="chart-key__item chart-key__item--trigger" data-line="trigger">
          {translate(locale, "history.trigger_line", { value: value(index.trigger) })}
        </span>
        <span className="chart-key__item chart-key__item--exit" data-line="exit">
          {translate(locale, "history.exit_line", { value: value(index.exit) })}
        </span>
      </p>
      <div
        ref={frame}
        className="chart"
        data-chart="index"
        onClick={(event) => {
          const season = seasonAtX(seasons, event.currentTarget, event.clientX);
          if (season !== null) onSelect(season);
        }}
      >
        <BarChart
          width={width}
          height={HEIGHT}
          data={[...seasons]}
          margin={CHART_MARGIN}
          syncId={SYNC_ID}
          barCategoryGap={1}
          accessibilityLayer={false}
        >
          <XAxis
            dataKey="season"
            ticks={decadeTicks(seasons)}
            tick={false}
            tickLine={false}
            height={4}
            stroke="var(--line-strong)"
          />
          <YAxis
            width={Y_AXIS_WIDTH}
            tickCount={4}
            tickLine={false}
            axisLine={false}
            tick={{ fill: "var(--ink-3)", fontSize: 11 }}
            tickFormatter={(tick: number) => formatNumber(tick, locale)}
          />
          <Tooltip
            isAnimationActive={false}
            cursor={{ fill: "var(--soft)" }}
            content={({ active, label }) => (
              <SeasonTip
                seasons={seasons}
                measure="index"
                indexType={index.index_type}
                active={active}
                label={label}
              />
            )}
          />
          <Bar
            dataKey="index_value"
            isAnimationActive={false}
            radius={[2, 2, 0, 0]}
            onClick={(_, at) => {
              const season = seasons[at];
              if (season !== undefined) onSelect(season.season);
            }}
          >
            {seasons.map((season) => (
              <Cell
                key={season.season}
                fill={barFill(season)}
                fillOpacity={barOpacity(season, selected)}
              />
            ))}
          </Bar>
          <ReferenceLine
            y={index.trigger}
            className="chart__line chart__line--trigger"
            stroke="var(--ink)"
            strokeDasharray="5 3"
            strokeWidth={1.2}
          />
          <ReferenceLine
            y={index.exit}
            className="chart__line chart__line--exit"
            stroke="var(--ink)"
            strokeDasharray="1.5 3"
            strokeWidth={1.2}
          />
        </BarChart>
      </div>
    </>
  );
}
