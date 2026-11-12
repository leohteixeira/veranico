import type { components } from "../api/schema";
import { useSeasons } from "./useSeasons";

type Schemas = components["schemas"];
type SeasonResult = Schemas["SeasonResult"];

function isMoney(value: unknown): value is Schemas["Money"] {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { amount_cents?: unknown }).amount_cents === "number" &&
    typeof (value as { currency?: unknown }).currency === "string"
  );
}

function isSeasonResult(value: unknown): value is SeasonResult {
  if (typeof value !== "object" || value === null) return false;
  const item = value as { season?: unknown; index_value?: unknown; payout?: unknown };
  return (
    typeof item.season === "number" &&
    typeof item.index_value === "number" &&
    (item.payout === null || isMoney(item.payout))
  );
}

/**
 * The seasons of a `backtest_index` tool result. A tool result reaches the interface as a free
 * object, so its shape is checked here before anything draws it.
 */
export function backtestSeasons(result: Record<string, unknown> | null): SeasonResult[] | null {
  const seasons = result?.seasons;
  if (!Array.isArray(seasons) || seasons.length === 0) return null;
  return seasons.every(isSeasonResult) ? seasons : null;
}

interface TimelineSource {
  /** The latest successful `backtest_index` result of the conversation, when there is one. */
  backtest: Record<string, unknown> | null;
  point: { lat: number; lon: number } | null;
  index: Schemas["IndexDefinition"] | null;
  limitCents: number | null;
}

export interface TimelineSeries {
  seasons: SeasonResult[] | null;
  status: "ready" | "loading" | "failed";
  retry: () => void;
}

/**
 * The series of the season timeline: the seasons of the latest backtest when the conversation has
 * one, otherwise `GET /weather/seasons` for the cover in view with its limit, so that payouts
 * always come from the API.
 */
export function useTimelineSeries({
  backtest,
  point,
  index,
  limitCents,
}: TimelineSource): TimelineSeries {
  const fromBacktest = backtestSeasons(backtest);
  const query = useSeasons(
    fromBacktest === null && point !== null && index !== null
      ? { lat: point.lat, lon: point.lon, index, limitCents }
      : null,
  );
  const retry = () => {
    void query.refetch();
  };
  if (fromBacktest !== null) return { seasons: fromBacktest, status: "ready", retry };
  if (query.data !== undefined) return { seasons: query.data.seasons, status: "ready", retry };
  return { seasons: null, status: query.isError ? "failed" : "loading", retry };
}
