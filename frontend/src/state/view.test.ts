import { describe, expect, it } from "vitest";

import { INDEX, LIMIT_CENTS, POINT, POINT_LABEL, QUOTE_ID } from "../test/fixtures/bodies";
import { initialView, viewReducer, type ViewAction, type ViewState } from "./view";

function run(actions: readonly ViewAction[], from: ViewState = initialView): ViewState {
  return actions.reduce(viewReducer, from);
}

const IN_REGION: ViewAction = {
  type: "region_selected",
  regionId: "sul-de-minas",
  point: { ...POINT, label: POINT_LABEL },
  index: INDEX,
  limitCents: LIMIT_CENTS,
};

describe("view store [R-12.2-4] [R-16.7-1]", () => {
  it("opens on the trigger frequency of all seasons, as a surface, on the Risk tab", () => {
    expect(initialView).toMatchObject({
      metric: "trigger_frequency",
      season: null,
      render: "surface",
      basemap: null,
      tab: "risk",
    });
  });

  it("selecting a season enters the season view and clearing it returns to the frequency", () => {
    const selected = run([IN_REGION, { type: "season_selected", season: 1987 }]);
    expect(selected.season).toBe(1987);
    expect(selected.metric).toBe("season_anomaly");

    const moved = viewReducer(selected, { type: "season_selected", season: 1988 });
    expect(moved.season).toBe(1988);
    expect(moved.metric).toBe("season_anomaly");

    const all = viewReducer(moved, { type: "season_selected", season: null });
    expect(all.season).toBeNull();
    expect(all.metric).toBe("trigger_frequency");
  });

  it("another region or another index definition leaves the season view", () => {
    const inSeason = run([IN_REGION, { type: "season_selected", season: 1987 }]);

    const otherRegion = viewReducer(inSeason, { ...IN_REGION, regionId: "sorriso" });
    expect(otherRegion).toMatchObject({ regionId: "sorriso", season: null, quoteId: null });
    expect(otherRegion.metric).toBe("trigger_frequency");

    const otherIndex = viewReducer(inSeason, {
      type: "index_set",
      index: { ...INDEX, trigger: 120 },
      limitCents: LIMIT_CENTS,
    });
    expect(otherIndex.season).toBeNull();
    expect(otherIndex.metric).toBe("trigger_frequency");
    expect(otherIndex.index?.trigger).toBe(120);
  });

  it("a priced quote pins its index definition without leaving the season on screen", () => {
    const pinned = run([
      IN_REGION,
      { type: "season_selected", season: 1987 },
      { type: "quote_pinned", quoteId: QUOTE_ID, index: INDEX, limitCents: LIMIT_CENTS },
    ]);

    expect(pinned.quoteId).toBe(QUOTE_ID);
    expect(pinned.season).toBe(1987);
  });

  it("render, basemap and tab are independent switches", () => {
    const state = run([
      { type: "render_set", render: "cells" },
      { type: "basemap_set", basemap: "satellite" },
      { type: "tab_opened", tab: "quote", highlight: "premium" },
      { type: "season_selected", season: 2001 },
    ]);

    expect(state).toMatchObject({
      render: "cells",
      basemap: "satellite",
      tab: "quote",
      highlight: "premium",
      season: 2001,
    });
    expect(viewReducer(state, { type: "tab_opened", tab: "history" }).highlight).toBeNull();
  });

  it("a point outside the showcase regions has no region", () => {
    const state = run([
      IN_REGION,
      {
        type: "point_set",
        point: { lat: -9.41, lon: -40.5, label: "Petrolina, PE" },
        regionId: null,
      },
    ]);

    expect(state.regionId).toBeNull();
    expect(state.point?.label).toBe("Petrolina, PE");
  });
});
