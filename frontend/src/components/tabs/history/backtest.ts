import type { components } from "../../../api/schema";
import { backtestSeasons } from "../../../hooks/useTimelineSeries";

type Schemas = components["schemas"];
type Json = Record<string, unknown>;

function record(value: unknown): Json | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Json)
    : null;
}

function isMoney(value: unknown): boolean {
  const money = record(value);
  return typeof money?.amount_cents === "number" && typeof money.currency === "string";
}

function isCover(value: unknown): boolean {
  const cover = record(value);
  const index = record(cover?.index);
  const window = record(index?.window);
  return (
    (index?.index_type === "rainfall_below" || index?.index_type === "dry_spell_above") &&
    typeof index.trigger === "number" &&
    typeof index.exit === "number" &&
    typeof window?.start === "string" &&
    typeof window.end === "string" &&
    isMoney(cover?.limit)
  );
}

/**
 * A `BacktestResult` read from a tool result, which reaches the interface as a free object: the
 * fields the History tab draws are checked first. `null` when the object is not a backtest.
 */
export function readBacktest(result: Json | null): Schemas["BacktestResult"] | null {
  if (result === null || backtestSeasons(result) === null) return null;
  const trend = record(result.trend);
  const valid =
    isCover(result.cover) &&
    isMoney(result.burn_cost) &&
    isMoney(result.max_payout) &&
    typeof result.trigger_frequency === "string" &&
    typeof result.seasons_used === "number" &&
    (result.max_payout_season === null || typeof result.max_payout_season === "number") &&
    Array.isArray(result.seasons_excluded) &&
    Array.isArray(result.warnings) &&
    typeof trend?.significant === "boolean" &&
    typeof trend.slope_per_decade === "number";
  return valid ? (result as unknown as Schemas["BacktestResult"]) : null;
}

/** The backtest inside a `price_cover` tool result (`{quote_id, priced}`), or `null`. */
export function readPricedBacktest(result: Json | null): Schemas["BacktestResult"] | null {
  return readBacktest(record(record(result?.priced)?.backtest));
}
