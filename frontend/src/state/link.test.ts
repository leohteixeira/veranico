import { describe, expect, it } from "vitest";

import { config } from "../config";
import { INDEX, LIMIT_CENTS, POINT, POINT_LABEL, QUOTE_ID, REGIONS } from "../test/fixtures/bodies";
import { conversationView, happyPath } from "../test/fixtures/streams";
import { linkActions, regionAt, regionSelected, sameIndex, sessionLink } from "./link";
import {
  initialSession,
  sessionReducer,
  type SessionAction,
  type SessionState,
  type ToolRow,
} from "./session";
import { initialView, viewReducer, type ViewAction, type ViewState } from "./view";

const [SUL_DE_MINAS, SORRISO] = REGIONS;
if (SUL_DE_MINAS === undefined || SORRISO === undefined) throw new Error("fixture regions missing");

function reduce(actions: readonly SessionAction[]): SessionState {
  return actions.reduce(sessionReducer, initialSession("live"));
}

/** The live session after the first `turnCount` turns of the happy path. */
function liveSession(turnCount: number): SessionState {
  const { turns, requests } = happyPath("en");
  const actions: SessionAction[] = [];
  turns.slice(0, turnCount).forEach((events, at) => {
    actions.push({ type: "user_sent", text: requests[at] ?? "" }, ...events);
  });
  return reduce(actions);
}

function row(overrides: Partial<ToolRow> & Pick<ToolRow, "tool">): ToolRow {
  return {
    callId: "call-x",
    arguments: null,
    status: "ok",
    durationMs: 10,
    summary: null,
    result: null,
    error: null,
    ...overrides,
  };
}

function apply(actions: readonly ViewAction[], from: ViewState = initialView): ViewState {
  return actions.reduce(viewReducer, from);
}

/** The view a visitor has before the conversation: another region, with its example. */
const IN_SORRISO = apply([regionSelected(SORRISO, config.exampleCovers)]);

describe("live link [R-12.2-5] [R-16.7-1]", () => {
  it("resolve_location_moves_the_map_and_selects_the_region [R-12.2-5]", () => {
    const actions = linkActions(
      row({ tool: "resolve_location", result: { label: POINT_LABEL, ...POINT } }),
      REGIONS,
    );
    expect(actions).toEqual([
      { type: "point_set", point: { ...POINT, label: POINT_LABEL }, regionId: "sul-de-minas" },
    ]);

    const view = apply(actions, IN_SORRISO);
    expect(view.regionId).toBe("sul-de-minas");
    expect(view.point).toEqual({ ...POINT, label: POINT_LABEL });

    // A call that is still running, or that failed, moves nothing.
    expect(linkActions(row({ tool: "resolve_location", status: "running" }), REGIONS)).toEqual([]);
    expect(
      linkActions(row({ tool: "resolve_location", status: "error", result: POINT }), REGIONS),
    ).toEqual([]);
    // Several candidates are a question to the visitor, not a place.
    expect(
      linkActions(row({ tool: "resolve_location", result: { candidates: [POINT] } }), REGIONS),
    ).toEqual([]);
  });

  it("point_outside_regions_enters_the_single_cell_state [R-12.4-6]", () => {
    const london = { label: "London, UK", lat: 51.5, lon: -0.12 };
    expect(regionAt(REGIONS, london.lat, london.lon)).toBeNull();
    expect(regionAt(REGIONS, POINT.lat, POINT.lon)).toBe(SUL_DE_MINAS);
    // The edges of a cube belong to it.
    expect(regionAt(REGIONS, SUL_DE_MINAS.north, SUL_DE_MINAS.west)).toBe(SUL_DE_MINAS);

    const actions = linkActions(row({ tool: "resolve_location", result: london }), REGIONS);
    const view = apply(actions, IN_SORRISO);
    expect(view.regionId).toBeNull();
    expect(view.point).toEqual(london);
  });

  it("backtest_recolours_with_its_index_definition [R-12.2-5]", () => {
    const args = {
      dataset_id: "cube:sul-de-minas:9:10",
      index_type: INDEX.index_type,
      window_start: INDEX.window.start,
      window_end: INDEX.window.end,
      trigger: INDEX.trigger,
      exit: INDEX.exit,
      limit_cents: LIMIT_CENTS,
    };
    const expected: ViewAction = { type: "index_set", index: INDEX, limitCents: LIMIT_CENTS };

    // The call recolours the layer as soon as it starts: its arguments are the definition.
    expect(
      linkActions(row({ tool: "backtest_index", status: "running", arguments: args }), REGIONS),
    ).toEqual([expected]);

    // A restored conversation keeps results, not arguments: the result's cover says the same.
    const stored = liveSession(1)
      .messages.flatMap((message) => message.tools)
      .find((tool) => tool.tool === "backtest_index");
    if (stored === undefined) throw new Error("the happy path has a backtest");
    expect(linkActions({ ...stored, arguments: null }, REGIONS)).toEqual([expected]);

    const before = apply([{ type: "season_selected", season: 1987 }], IN_SORRISO);
    const view = apply([expected], before);
    expect(view.index).toEqual(INDEX);
    expect(view.limitCents).toBe(LIMIT_CENTS);
    // Another definition has other seasons: the view returns to the frequency of all seasons.
    expect(view.metric).toBe("trigger_frequency");
    expect(view.season).toBeNull();

    expect(
      linkActions(row({ tool: "backtest_index", status: "error", arguments: args }), REGIONS),
    ).toEqual([]);
    expect(
      linkActions(row({ tool: "backtest_index", arguments: { index_type: "other" } }), REGIONS),
    ).toEqual([]);
  });

  it("priced_quote_pins_the_index_definition [R-12.2-5]", () => {
    const session = liveSession(2);
    const step = sessionLink(session, REGIONS, new Set());
    expect(step.actions.map((action) => action.type)).toEqual([
      "point_set",
      "index_set",
      "quote_pinned",
      "tab_opened",
    ]);
    expect(step.actions[2]).toEqual({
      type: "quote_pinned",
      quoteId: QUOTE_ID,
      index: INDEX,
      limitCents: LIMIT_CENTS,
    });

    const view = apply(step.actions, IN_SORRISO);
    expect(view).toMatchObject({
      regionId: "sul-de-minas",
      quoteId: QUOTE_ID,
      index: INDEX,
      limitCents: LIMIT_CENTS,
      tab: "quote",
    });

    // A quote that could not be priced pins nothing.
    expect(
      linkActions(row({ tool: "price_cover", status: "error", result: null }), REGIONS),
    ).toEqual([]);
    expect(
      linkActions(row({ tool: "price_cover", result: { quote_id: QUOTE_ID } }), REGIONS),
    ).toEqual([]);
  });

  it("each call acts once, however often the session changes", () => {
    const first = sessionLink(liveSession(1), REGIONS, new Set());
    expect(first.actions.map((action) => action.type)).toEqual(["point_set", "index_set"]);
    expect([...first.applied]).toEqual(["call-1", "call-3"]);

    // The same session again asks for nothing: a season the visitor chose is not undone.
    expect(sessionLink(liveSession(1), REGIONS, first.applied).actions).toEqual([]);

    const second = sessionLink(liveSession(2), REGIONS, first.applied);
    expect(second.actions.map((action) => action.type)).toEqual(["quote_pinned", "tab_opened"]);
  });

  it("a restored conversation runs through the same link", () => {
    const restored = reduce([{ type: "restored", conversation: conversationView("en", 4) }]);
    const { actions } = sessionLink(restored, REGIONS, new Set());
    expect(apply(actions)).toMatchObject({
      regionId: "sul-de-minas",
      point: { ...POINT, label: POINT_LABEL },
      index: INDEX,
      quoteId: QUOTE_ID,
      tab: "quote",
    });
  });

  it("a region opens with its example cover, or empty when it has none", () => {
    const example = config.exampleCovers["sul-de-minas"];
    if (example === undefined) throw new Error("the first region has an example");
    expect(regionSelected(SUL_DE_MINAS, config.exampleCovers)).toEqual({
      type: "region_selected",
      regionId: "sul-de-minas",
      point: { ...example.point, label: example.label },
      index: example.cover.index,
      limitCents: example.cover.limit.amount_cents,
    });
    expect(regionSelected(SUL_DE_MINAS, {})).toEqual({
      type: "region_selected",
      regionId: "sul-de-minas",
      point: null,
      index: null,
      limitCents: null,
    });
  });

  it("two index definitions are the same only when every term is", () => {
    expect(sameIndex(INDEX, { ...INDEX, window: { ...INDEX.window } })).toBe(true);
    expect(sameIndex(INDEX, { ...INDEX, trigger: INDEX.trigger + 1 })).toBe(false);
    expect(sameIndex(INDEX, null)).toBe(false);
    expect(sameIndex(null, null)).toBe(false);
  });
});
