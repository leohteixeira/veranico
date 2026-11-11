import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { INSURED_COL, INSURED_ROW, SEASONS, backtestResult } from "./bodies";
import { RECORDED_CELLS, recordedResult, recording } from "./recording";
import { STREAM_FIXTURES } from "./streams";

/**
 * The `.sse` files are the serialised form of the typed events in `streams.ts`. This test fails
 * when a file is out of step; `UPDATE_FIXTURES=1 pnpm test src/test/fixtures` rewrites them.
 */
describe("stream fixtures", () => {
  it.each(Object.keys(STREAM_FIXTURES))("%s is the serialised typed events", (name) => {
    const path = join(import.meta.dirname, name);
    const expected = STREAM_FIXTURES[name]?.() ?? "";
    if (process.env.UPDATE_FIXTURES === "1") writeFileSync(path, expected);

    expect(existsSync(path), `${name} is missing: run with UPDATE_FIXTURES=1`).toBe(true);
    expect(readFileSync(path, "utf8")).toBe(expected);
    expect(expected.endsWith("\n\n")).toBe(true);
  });
});

describe("recorded happy path", () => {
  it("prices the same cover to the same figures in both languages", () => {
    // The mock serves one quote body for both recordings, with each one's identifiers.
    const priced = (locale: "en" | "pt-BR") => recordedResult(locale, "price_cover").priced;
    expect(priced("pt-BR")).toEqual(priced("en"));
  });

  it("the cell grids come from the recording's cube and agree with its backtest", () => {
    expect(RECORDED_CELLS.source.cube_checksum).toBe(recording("en").header.cube_checksum);
    expect(RECORDED_CELLS.index).toEqual(backtestResult().cover.index);
    expect(RECORDED_CELLS.trigger_frequency.seasons).toEqual(SEASONS);
    const insured = INSURED_ROW * RECORDED_CELLS.region.nx + INSURED_COL;
    expect(RECORDED_CELLS.trigger_frequency.values[insured]).toBe(
      Number(backtestResult().trigger_frequency),
    );
  });
});
