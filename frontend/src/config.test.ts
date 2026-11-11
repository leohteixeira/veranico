import { describe, expect, it } from "vitest";

import {
  ENV_BASEMAP_RELIEF,
  ENV_BASEMAP_SATELLITE,
  ENV_EXAMPLE_COVERS,
  loadConfig,
  type BasemapConfig,
  type ExampleCover,
} from "./config";

const SHOWCASE_REGIONS = ["sul-de-minas", "sorriso", "ribeirao-preto"];

describe("build-time configuration", () => {
  it("has an example cover for each showcase region, with exit below the trigger", () => {
    const { exampleCovers } = loadConfig({});

    expect(Object.keys(exampleCovers).sort()).toEqual([...SHOWCASE_REGIONS].sort());
    for (const example of Object.values(exampleCovers)) {
      expect(example.cover.index.index_type).toBe("rainfall_below");
      expect(example.cover.index.exit).toBeLessThan(example.cover.index.trigger);
      expect(Number.isInteger(example.cover.limit.amount_cents)).toBe(true);
    }
  });

  it("replaces a basemap from its VITE_ variable and leaves the other alone", () => {
    const relief: BasemapConfig = {
      urlTemplate: "https://tiles.test/{z}/{y}/{x}.jpg",
      attribution: "Test tiles",
      licenceNote: "Test licence",
      maxZoom: 12,
    };
    const defaults = loadConfig({});

    const config = loadConfig({ [ENV_BASEMAP_RELIEF]: JSON.stringify(relief) });

    expect(config.basemaps.relief).toEqual(relief);
    expect(config.basemaps.satellite).toEqual(defaults.basemaps.satellite);
  });

  it("merges example covers from VITE_EXAMPLE_COVERS by region", () => {
    const sorriso: ExampleCover = {
      point: { lat: -12.5, lon: -55.7 },
      label: "Elsewhere, MT",
      cover: {
        index: {
          index_type: "dry_spell_above",
          window: { start: "12-01", end: "01-31" },
          trigger: 12,
          exit: 25,
        },
        limit: { amount_cents: 10_000_000, currency: "BRL" },
      },
    };
    const defaults = loadConfig({});

    const config = loadConfig({ [ENV_EXAMPLE_COVERS]: JSON.stringify({ sorriso }) });

    expect(config.exampleCovers["sorriso"]).toEqual(sorriso);
    expect(config.exampleCovers["sul-de-minas"]).toEqual(defaults.exampleCovers["sul-de-minas"]);
  });

  it("ignores an empty variable", () => {
    expect(loadConfig({ [ENV_BASEMAP_SATELLITE]: "" })).toEqual(loadConfig({}));
  });

  it("refuses a malformed override instead of ignoring it", () => {
    expect(() => loadConfig({ [ENV_BASEMAP_RELIEF]: "{not json" })).toThrow(ENV_BASEMAP_RELIEF);
    expect(() => loadConfig({ [ENV_BASEMAP_SATELLITE]: '{"urlTemplate": 3}' })).toThrow(
      ENV_BASEMAP_SATELLITE,
    );
    expect(() =>
      loadConfig({
        [ENV_EXAMPLE_COVERS]: '{"sorriso": {"label": "x", "point": {"lat": "a", "lon": 1}}}',
      }),
    ).toThrow(ENV_EXAMPLE_COVERS);
  });
});
