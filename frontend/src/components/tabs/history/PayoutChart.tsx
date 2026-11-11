import { Bar, BarChart, Cell, Tooltip, XAxis, YAxis } from "recharts";

import type { components } from "../../../api/schema";
import { useI18n } from "../../../i18n";
import { formatMoney, formatSeason } from "../../../i18n/format";
import {
  CHART_MARGIN,
  SYNC_ID,
  Y_AXIS_WIDTH,
  barOpacity,
  decadeTicks,
  seasonAtX,
  useChartWidth,
  type SeasonResult,
} from "./chart";
import { SeasonTip } from "./SeasonTip";

type Schemas = components["schemas"];

interface PayoutChartProps {
  seasons: readonly SeasonResult[];
  indexType: Schemas["IndexDefinition"]["index_type"];
  /** The limit of the cover: the top of the value axis, since no payout exceeds it. */
  limit: Schemas["Money"];
  selected: number | null;
  onSelect: (season: number) => void;
}

const HEIGHT = 96;

/** The payout per season, on the time axis of the index panel above and with its own value axis. */
export function PayoutChart({ seasons, indexType, limit, selected, onSelect }: PayoutChartProps) {
  const { locale } = useI18n();
  const [frame, width] = useChartWidth();
  // The axis is labelled at its two ends only: zero, and the limit as the API gave it.
  const money = (cents: number) => {
    if (cents === 0) return "0";
    const text = formatMoney(cents, locale);
    return cents % 100 === 0 ? text.slice(0, -3) : text;
  };

  return (
    <div
      ref={frame}
      className="chart"
      data-chart="payout"
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
          tickLine={false}
          height={20}
          stroke="var(--line-strong)"
          tick={{ fill: "var(--ink-3)", fontSize: 11 }}
          tickFormatter={(season: number) => formatSeason(season)}
        />
        <YAxis
          width={Y_AXIS_WIDTH}
          domain={[0, limit.amount_cents]}
          ticks={[0, limit.amount_cents]}
          tickLine={false}
          axisLine={false}
          tick={{ fill: "var(--ink-3)", fontSize: 10 }}
          tickFormatter={money}
        />
        <Tooltip
          isAnimationActive={false}
          cursor={{ fill: "var(--soft)" }}
          content={({ active, label }) => (
            <SeasonTip
              seasons={seasons}
              measure="payout"
              indexType={indexType}
              active={active}
              label={label}
            />
          )}
        />
        <Bar
          dataKey={(season: SeasonResult) => season.payout?.amount_cents ?? 0}
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
              fill="var(--pay)"
              fillOpacity={barOpacity(season, selected)}
            />
          ))}
        </Bar>
      </BarChart>
    </div>
  );
}
