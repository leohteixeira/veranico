import type { Locale } from "../../i18n";
import { translate } from "../../i18n";
import { formatIndexValue, formatMoney, formatNumber, formatRate } from "../../i18n/format";
import type { ToolRow } from "../../state/session";
import type { TabId } from "../../state/view";

/**
 * Figure links. A figure in an answer is matched BY VALUE against the fields of the conversation's
 * tool results: the candidate texts are the API's own values in the notations an answer may use
 * (with or without the centavos, a rate at zero to two decimals). Nothing is computed from them.
 */

/** The field of a tab a figure points at; the tabs highlight the field with this key. */
export type FigureKey =
  | "quote_id"
  | "premium"
  | "rate_on_line"
  | "expected_loss"
  | "payout_1_in_10"
  | "payout_1_in_100"
  | "burn_cost"
  | "max_payout"
  | "trigger_frequency"
  | "limit"
  | "trigger"
  | "exit";

export type Segment =
  | { kind: "text"; text: string }
  /** A figure with a source: `key` is `null` when only the tab of the latest tool is known. */
  | { kind: "figure"; text: string; tab: TabId; key: FigureKey | null }
  /** A figure the grounding check found in no tool output. */
  | { kind: "flagged"; text: string };

/** The tab that shows what a tool produced. */
export const TAB_OF_TOOL: Readonly<Record<string, TabId>> = {
  resolve_location: "risk",
  get_weather_history: "history",
  backtest_index: "history",
  find_extreme_seasons: "history",
  price_cover: "quote",
  draft_term_sheet: "quote",
  request_submission: "approvals",
};

type Json = Record<string, unknown>;

interface Target {
  tab: TabId;
  key: FigureKey;
}

function record(value: unknown): Json | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Json)
    : null;
}

function cents(value: unknown): number | null {
  const amount = record(value)?.amount_cents;
  return typeof amount === "number" && Number.isSafeInteger(amount) ? amount : null;
}

const NBSP = " ";

/** One space for every space or no-break space, so a figure matches however it was spaced. */
function plain(text: string): string {
  return text.replaceAll(NBSP, " ");
}

function moneyTexts(value: unknown, locale: Locale): string[] {
  const amount = cents(value);
  if (amount === null) return [];
  const full = formatMoney(amount, locale);
  // A whole amount is often written without its centavos.
  return amount % 100 === 0 ? [full, full.slice(0, -3)] : [full];
}

function rateTexts(value: unknown, locale: Locale): string[] {
  if (typeof value !== "string") return [];
  return [
    formatRate(value, locale),
    ...[2, 1, 0].map((digits) => formatRate(value, locale, digits)),
  ];
}

function indexTexts(value: unknown, indexType: unknown, locale: Locale): string[] {
  if (typeof value !== "number") return [];
  if (indexType !== "rainfall_below" && indexType !== "dry_spell_above") return [];
  const texts = [formatIndexValue(value, indexType, locale)];
  if (indexType === "rainfall_below") {
    texts.push(translate(locale, "unit.mm", { value: formatNumber(value, locale) }));
  }
  return texts;
}

class Candidates {
  readonly byText = new Map<string, Target>();

  /** The first target given for a text is kept: rows are read from the most recent one. */
  add(texts: readonly string[], tab: TabId, key: FigureKey): void {
    for (const text of texts) {
      const normal = plain(text);
      if (normal !== "" && !this.byText.has(normal)) this.byText.set(normal, { tab, key });
    }
  }
}

function addCover(found: Candidates, cover: Json | null, tab: TabId, locale: Locale): void {
  const index = record(cover?.index);
  found.add(moneyTexts(cover?.limit, locale), tab, "limit");
  found.add(indexTexts(index?.trigger, index?.index_type, locale), tab, "trigger");
  found.add(indexTexts(index?.exit, index?.index_type, locale), tab, "exit");
}

function addBacktest(found: Candidates, backtest: Json | null, locale: Locale): void {
  if (backtest === null) return;
  found.add(moneyTexts(backtest.burn_cost, locale), "history", "burn_cost");
  found.add(moneyTexts(backtest.max_payout, locale), "history", "max_payout");
  found.add(rateTexts(backtest.trigger_frequency, locale), "history", "trigger_frequency");
}

function addPriced(found: Candidates, result: Json, locale: Locale): void {
  const priced = record(result.priced);
  const premium = record(priced?.premium);
  const simulation = record(priced?.simulation);
  const backtest = record(priced?.backtest);
  if (typeof result.quote_id === "string") found.add([result.quote_id], "quote", "quote_id");
  found.add(moneyTexts(premium?.premium, locale), "quote", "premium");
  found.add(rateTexts(premium?.rate_on_line, locale), "quote", "rate_on_line");
  found.add(moneyTexts(simulation?.expected_loss, locale), "quote", "expected_loss");
  found.add(moneyTexts(simulation?.payout_1_in_10, locale), "quote", "payout_1_in_10");
  found.add(moneyTexts(simulation?.payout_1_in_100, locale), "quote", "payout_1_in_100");
  addCover(found, record(backtest?.cover), "quote", locale);
  addBacktest(found, backtest, locale);
}

function candidates(rows: readonly ToolRow[], locale: Locale): Map<string, Target> {
  const found = new Candidates();
  for (let at = rows.length - 1; at >= 0; at -= 1) {
    const row = rows[at];
    if (row === undefined || row.status !== "ok" || row.result === null) continue;
    if (row.tool === "price_cover") addPriced(found, row.result, locale);
    if (row.tool === "backtest_index") {
      addBacktest(found, row.result, locale);
      addCover(found, record(row.result.cover), "history", locale);
    }
    if (row.tool === "request_submission" && typeof row.result.quote_id === "string") {
      found.add([row.result.quote_id], "quote", "quote_id");
    }
  }
  return found.byText;
}

function latestTab(rows: readonly ToolRow[]): TabId | null {
  for (let at = rows.length - 1; at >= 0; at -= 1) {
    const row = rows[at];
    const tab = row === undefined || row.status === "running" ? undefined : TAB_OF_TOOL[row.tool];
    if (tab !== undefined) return tab;
  }
  return null;
}

const SPACE = "[ \\u00a0]";
const NUMBER = "\\d(?:[\\d.,]*\\d)?";
/** Anything written as money, a percentage or millimetres is a figure, matched or not. */
const ANY_FIGURE = [
  `R\\$${SPACE}?${NUMBER}`,
  `${NUMBER}${SPACE}?%`,
  `${NUMBER}${SPACE}?mm(?![A-Za-z])`,
];

function pattern(text: string): string {
  return plain(text)
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replaceAll(" ", SPACE);
}

/**
 * Splits an answer into text, linked figures and flagged figures.
 *
 * `toolResults` are the finished tool rows of the conversation up to this answer, oldest first;
 * `flagged` are the values `grounding_flagged` listed for it. A flagged value is never linked. A
 * figure that matches no field opens the tab of the most recent tool, without a field.
 */
export function linkFigures(
  text: string,
  toolResults: readonly ToolRow[],
  flagged: readonly string[],
  locale: Locale,
): Segment[] {
  const targets = candidates(toolResults, locale);
  const flaggedTexts = new Set(flagged.map(plain).filter((value) => value !== ""));
  const fallback = latestTab(toolResults);

  // Longest first, so `R$ 300,000.00` is not read as `R$ 300,000` followed by text.
  const known = [...flaggedTexts, ...targets.keys()].sort((a, b) => b.length - a.length);
  const figure = new RegExp(
    `(?<![\\w.,])(?:${[...known.map(pattern), ...ANY_FIGURE].join("|")})(?![\\w]|[.,]\\d)`,
    "g",
  );

  const segments: Segment[] = [];
  const pushText = (value: string) => {
    if (value === "") return;
    const last = segments[segments.length - 1];
    if (last?.kind === "text") last.text += value;
    else segments.push({ kind: "text", text: value });
  };

  let cursor = 0;
  for (const match of text.matchAll(figure)) {
    const value = match[0];
    pushText(text.slice(cursor, match.index));
    cursor = match.index + value.length;
    const normal = plain(value);
    const target = targets.get(normal);
    if (flaggedTexts.has(normal)) segments.push({ kind: "flagged", text: value });
    else if (target !== undefined) segments.push({ kind: "figure", text: value, ...target });
    else if (fallback !== null)
      segments.push({ kind: "figure", text: value, tab: fallback, key: null });
    else pushText(value);
  }
  pushText(text.slice(cursor));
  return segments;
}
