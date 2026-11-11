import type { components } from "../../../api/schema";
import { readBacktest } from "../history/backtest";
import type { RecordedQuote } from "./QuoteTab";

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

const SIMULATION_MONEY = [
  "expected_loss",
  "std_dev",
  "payout_1_in_10",
  "payout_1_in_100",
  "gap_to_burn_cost",
] as const;

/**
 * The quote of a recorded `price_cover` result (`{quote_id, priced}`). A tool result reaches the
 * interface as a free object, so the fields the Quote tab draws are checked first; `null` when the
 * object is not a priced cover.
 */
export function readRecordedQuote(result: Json | null): RecordedQuote | null {
  const priced = record(result?.priced);
  const premium = record(priced?.premium);
  const simulation = record(priced?.simulation);
  if (typeof result?.quote_id !== "string" || priced === null) return null;
  const valid =
    readBacktest(record(priced.backtest)) !== null &&
    isMoney(premium?.premium) &&
    typeof premium?.rate_on_line === "string" &&
    simulation !== null &&
    SIMULATION_MONEY.every((name) => isMoney(simulation[name])) &&
    typeof simulation.probability_of_payout === "string" &&
    Array.isArray(priced.assumptions);
  return valid
    ? { quoteId: result.quote_id, priced: priced as unknown as Schemas["PricedCover"] }
    : null;
}
