import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

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
