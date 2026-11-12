import type { components } from "../api/schema";
import type { ExampleCover } from "../config";
import type { SessionState, ToolRow } from "./session";
import type { ViewAction } from "./view";

/**
 * The live link between the conversation and the rest of the screen, as pure functions from tool
 * rows to view actions. The same link runs over a live turn, a recording and a restored
 * conversation, so a reload brings the map and the tabs back to where the conversation left them.
 */

type Schemas = components["schemas"];
type Region = Schemas["Region"];
type IndexDefinition = Schemas["IndexDefinition"];
type Json = Record<string, unknown>;

function record(value: unknown): Json | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Json)
    : null;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function indexType(value: unknown): IndexDefinition["index_type"] | null {
  return value === "rainfall_below" || value === "dry_spell_above" ? value : null;
}

/** The showcase region whose weather cube contains a point, or `null` outside all of them. */
export function regionAt(regions: readonly Region[], lat: number, lon: number): Region | null {
  return (
    regions.find(
      (region) =>
        lat <= region.north && lat >= region.south && lon >= region.west && lon <= region.east,
    ) ?? null
  );
}

interface Cover {
  index: IndexDefinition;
  limitCents: number | null;
}

/** The cover in the flat arguments of `backtest_index` and `price_cover`. */
function coverFromArguments(args: Json | null): Cover | null {
  const type = indexType(args?.index_type);
  if (args === null || type === null) return null;
  const { window_start: start, window_end: end, trigger, exit, limit_cents: limit } = args;
  if (typeof start !== "string" || typeof end !== "string") return null;
  if (!finite(trigger) || !finite(exit)) return null;
  return {
    index: { index_type: type, window: { start, end }, trigger, exit },
    limitCents: finite(limit) ? limit : null,
  };
}

/** The cover inside a result (`BacktestResult.cover`), for rows that kept no arguments. */
function coverFromResult(value: unknown): Cover | null {
  const cover = record(value);
  const index = record(cover?.index);
  const window = record(index?.window);
  const type = indexType(index?.index_type);
  if (index === null || type === null) return null;
  if (typeof window?.start !== "string" || typeof window.end !== "string") return null;
  if (!finite(index.trigger) || !finite(index.exit)) return null;
  const limit = record(cover?.limit)?.amount_cents;
  return {
    index: {
      index_type: type,
      window: { start: window.start, end: window.end },
      trigger: index.trigger,
      exit: index.exit,
    },
    limitCents: finite(limit) ? limit : null,
  };
}

/**
 * What one tool row asks of the view, or nothing yet.
 *
 * - A finished `resolve_location` moves the map to the point and selects its region; a point in
 *   no showcase region selects none (the single-cell state).
 * - A `backtest_index` call sets the index definition, which recolours the risk layer: from its
 *   arguments as soon as the call starts, or from its result when the arguments were not kept.
 * - A finished `price_cover` pins the quote's index definition and opens the Quote tab.
 */
export function linkActions(row: ToolRow, regions: readonly Region[]): ViewAction[] {
  if (row.status === "error") return [];

  if (row.tool === "resolve_location") {
    const result = row.result;
    if (row.status !== "ok" || result === null) return [];
    const { lat, lon, label } = result;
    if (!finite(lat) || !finite(lon)) return [];
    return [
      {
        type: "point_set",
        point: { lat, lon, label: typeof label === "string" ? label : null },
        regionId: regionAt(regions, lat, lon)?.region_id ?? null,
      },
    ];
  }

  if (row.tool === "backtest_index") {
    const cover =
      coverFromArguments(row.arguments) ??
      (row.status === "ok" ? coverFromResult(row.result?.cover) : null);
    return cover === null ? [] : [{ type: "index_set", ...cover }];
  }

  if (row.tool === "price_cover") {
    const result = row.result;
    if (row.status !== "ok" || result === null || typeof result.quote_id !== "string") return [];
    const cover = coverFromResult(record(record(result.priced)?.backtest)?.cover);
    if (cover === null || cover.limitCents === null) return [];
    return [
      {
        type: "quote_pinned",
        quoteId: result.quote_id,
        index: cover.index,
        limitCents: cover.limitCents,
      },
      { type: "tab_opened", tab: "quote" },
    ];
  }

  return [];
}

export interface LinkStep {
  actions: ViewAction[];
  /** The calls whose actions were produced, so each call acts once. */
  applied: Set<string>;
}

/**
 * The actions of every tool row of the session that has not acted yet, oldest first. `applied`
 * holds the call identifiers handled so far; the returned set also holds the new ones.
 */
export function sessionLink(
  session: SessionState,
  regions: readonly Region[],
  applied: ReadonlySet<string>,
): LinkStep {
  const next = new Set(applied);
  const actions: ViewAction[] = [];
  for (const message of session.messages) {
    for (const row of message.tools) {
      if (next.has(row.callId)) continue;
      const produced = linkActions(row, regions);
      if (produced.length === 0) continue;
      next.add(row.callId);
      actions.push(...produced);
    }
  }
  return { actions, applied: next };
}

/** The view a showcase region opens with: its example point and cover, when it has one. */
export function regionSelected(
  region: Region,
  examples: Readonly<Record<string, ExampleCover>>,
): ViewAction {
  const example = examples[region.region_id];
  return {
    type: "region_selected",
    regionId: region.region_id,
    point:
      example === undefined
        ? null
        : { lat: example.point.lat, lon: example.point.lon, label: example.label },
    index: example?.cover.index ?? null,
    limitCents: example?.cover.limit.amount_cents ?? null,
  };
}

/** Whether a cover read from a tool result is the one the view is drawn for. */
export function sameIndex(a: IndexDefinition | null, b: IndexDefinition | null): boolean {
  if (a === null || b === null) return false;
  return (
    a.index_type === b.index_type &&
    a.window.start === b.window.start &&
    a.window.end === b.window.end &&
    a.trigger === b.trigger &&
    a.exit === b.exit
  );
}
