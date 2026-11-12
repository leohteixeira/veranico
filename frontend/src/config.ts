import type { components } from "./api/schema";
import type { Locale } from "./i18n";

type CoverDefinition = components["schemas"]["CoverDefinition"];
type GridPoint = components["schemas"]["GridPoint"];

/**
 * Build-time configuration. Agents and CI never read `.env` files, so every default lives here;
 * each entry can be replaced by one `VITE_` variable holding JSON (names in `env.example`).
 * There is no synthetic-data flag: that label comes from the API (`Region.synthetic`).
 */

export type BasemapId = "relief" | "satellite";

export interface BasemapConfig {
  /** Leaflet tile URL template (`{z}`, `{x}`, `{y}`). */
  urlTemplate: string;
  /** The attribution text the provider requires, shown next to the map. */
  attribution: string;
  /** Where the attribution links to (the provider asks for a link back). */
  attributionUrl?: string;
  /** The licence of the layer, shown with the attribution. */
  licenceNote: string;
  /** The text of the licence. */
  licenceUrl?: string;
  maxZoom: number;
}

/** The cover a showcase region opens with, before any conversation. */
export interface ExampleCover {
  /** The insured point of the example. */
  point: GridPoint;
  /** A place name, shown as data. */
  label: string;
  cover: CoverDefinition;
}

export interface AppConfig {
  basemaps: Record<BasemapId, BasemapConfig>;
  /** Keyed by `Region.region_id`. */
  exampleCovers: Record<string, ExampleCover>;
  /** The project's page on the owner's portfolio, per interface language; the wordmark links there. */
  landingUrls: Record<Locale, string>;
}

export const ENV_BASEMAP_RELIEF = "VITE_BASEMAP_RELIEF";
export const ENV_BASEMAP_SATELLITE = "VITE_BASEMAP_SATELLITE";
export const ENV_EXAMPLE_COVERS = "VITE_EXAMPLE_COVERS";
export const ENV_LANDING_URLS = "VITE_LANDING_URLS";

// The landing page lives in the portfolio repository (PRODUCT.md), one page per language.
const DEFAULT_LANDING_URLS: Record<Locale, string> = {
  en: "https://leohteixeira.com/en/projects/veranico",
  "pt-BR": "https://leohteixeira.com/pt/projects/veranico",
};

// Verified on 2026-11-11 in EOX's own documents, not stated from memory:
// - https://tiles.maps.eox.at/wmts/1.0.0/WMTSCapabilities.xml: the layer identifiers
//   (`terrain-light_3857`; `s2cloudless-2025_3857`, the most recent year), the resource template
//   `.../{layer}/default/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.jpg`, the tile matrix set
//   `g` (Web Mercator, 256 px tiles), the attribution of each layer and "Proper attribution is
//   required for any usage".
// - https://maps.eox.at/: free use, with attribution and a link back to EOX::Maps.
// - https://cloudless.eox.at/documentation/license: the attribution of Sentinel-2 cloudless and
//   its CC BY-NC-SA 4.0 licence, which is why the demo is non-commercial.
// The attribution texts are the providers' wording and are not translated. In Leaflet's template
// `{z}` is the tile matrix, `{y}` the row and `{x}` the column. Both layers answer over HTTPS.
const DEFAULT_BASEMAPS: Record<BasemapId, BasemapConfig> = {
  relief: {
    urlTemplate:
      "https://tiles.maps.eox.at/wmts/1.0.0/terrain-light_3857/default/g/{z}/{y}/{x}.jpg",
    attribution: "Terrain Light { Data © OpenStreetMap contributors and others, Rendering © EOX }",
    attributionUrl: "https://maps.eox.at/#data",
    licenceNote: "EOX::Maps, free to use with attribution",
    licenceUrl: "https://maps.eox.at/",
    maxZoom: 13,
  },
  satellite: {
    urlTemplate:
      "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg",
    attribution:
      "EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2025)",
    attributionUrl: "https://cloudless.eox.at",
    licenceNote: "CC BY-NC-SA 4.0",
    licenceUrl: "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    maxZoom: 13,
  },
};

// The three example covers of the approved preview (`design-reference/vr/engine.js`): its places,
// windows and limits. The API has no default cover per region, so the first view takes it from
// here.
//
// The triggers and exits are set from the real ERA5-Land cubes (gate H1, built from Google Earth
// Engine, ADR 0019) by one rule: the trigger is the 13th percentile of the example's season index
// and the exit its 3rd percentile, each rounded to the nearest 5 mm, so each example pays in about
// one season in seven and in full in the driest few. Measured with the `pricing` backtest on the
// example point's cell, 1950 to 2025, on 2026-11-11: Sul de Minas pays in 11 of 76 seasons (3 in
// full), Sorriso 11 of 76 (4), Ribeirão Preto 10 of 75 (3). They are not agronomic figures.
const DEFAULT_EXAMPLE_COVERS: Record<string, ExampleCover> = {
  "sul-de-minas": {
    point: { lat: -21.41, lon: -45.48 },
    label: "Três Pontas, MG",
    cover: {
      index: {
        index_type: "rainfall_below",
        window: { start: "09-01", end: "10-31" },
        trigger: 105,
        exit: 70,
      },
      limit: { amount_cents: 30_000_000, currency: "BRL" },
    },
  },
  sorriso: {
    point: { lat: -12.6, lon: -55.66 },
    label: "Sorriso, MT",
    cover: {
      index: {
        index_type: "rainfall_below",
        window: { start: "10-01", end: "11-30" },
        trigger: 255,
        exit: 185,
      },
      limit: { amount_cents: 50_000_000, currency: "BRL" },
    },
  },
  "ribeirao-preto": {
    point: { lat: -21.1, lon: -48.03 },
    label: "Sertãozinho, SP",
    cover: {
      index: {
        index_type: "rainfall_below",
        window: { start: "11-15", end: "02-15" },
        trigger: 460,
        exit: 335,
      },
      limit: { amount_cents: 40_000_000, currency: "BRL" },
    },
  },
};

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

const MONTH_DAY = /^\d{2}-\d{2}$/;

/** Absent, or an `https:` address: these become links in the attribution line. */
function isOptionalUrl(value: unknown): value is string | undefined {
  return value === undefined || (typeof value === "string" && value.startsWith("https://"));
}

function isBasemap(value: unknown): value is BasemapConfig {
  return (
    isObject(value) &&
    typeof value.urlTemplate === "string" &&
    value.urlTemplate !== "" &&
    typeof value.attribution === "string" &&
    value.attribution !== "" &&
    typeof value.licenceNote === "string" &&
    isOptionalUrl(value.attributionUrl) &&
    isOptionalUrl(value.licenceUrl) &&
    isFiniteNumber(value.maxZoom)
  );
}

function isCover(value: unknown): value is CoverDefinition {
  if (!isObject(value) || !isObject(value.index) || !isObject(value.limit)) return false;
  const { index, limit } = value;
  return (
    (index.index_type === "rainfall_below" || index.index_type === "dry_spell_above") &&
    isObject(index.window) &&
    typeof index.window.start === "string" &&
    MONTH_DAY.test(index.window.start) &&
    typeof index.window.end === "string" &&
    MONTH_DAY.test(index.window.end) &&
    isFiniteNumber(index.trigger) &&
    isFiniteNumber(index.exit) &&
    Number.isInteger(limit.amount_cents) &&
    limit.currency === "BRL"
  );
}

function isExampleCover(value: unknown): value is ExampleCover {
  return (
    isObject(value) &&
    isObject(value.point) &&
    isFiniteNumber(value.point.lat) &&
    isFiniteNumber(value.point.lon) &&
    typeof value.label === "string" &&
    isCover(value.cover)
  );
}

function isLandingUrls(value: unknown): value is Record<Locale, string> {
  return (
    isObject(value) &&
    typeof value.en === "string" &&
    value.en.startsWith("https://") &&
    typeof value["pt-BR"] === "string" &&
    value["pt-BR"].startsWith("https://")
  );
}

function isExampleCovers(value: unknown): value is Record<string, ExampleCover> {
  return isObject(value) && Object.values(value).every(isExampleCover);
}

/** Reads one JSON override. A malformed value stops the application instead of being ignored. */
function override<T>(
  env: Readonly<Record<string, unknown>>,
  name: string,
  isValid: (value: unknown) => value is T,
): T | undefined {
  const raw = env[name];
  if (typeof raw !== "string" || raw.trim() === "") return undefined;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`${name} is not valid JSON`);
  }
  if (!isValid(parsed)) {
    throw new Error(`${name} does not have the expected shape (see src/config.ts)`);
  }
  return parsed;
}

export function loadConfig(env: Readonly<Record<string, unknown>>): AppConfig {
  return {
    basemaps: {
      relief: override(env, ENV_BASEMAP_RELIEF, isBasemap) ?? DEFAULT_BASEMAPS.relief,
      satellite: override(env, ENV_BASEMAP_SATELLITE, isBasemap) ?? DEFAULT_BASEMAPS.satellite,
    },
    exampleCovers: {
      ...DEFAULT_EXAMPLE_COVERS,
      ...override(env, ENV_EXAMPLE_COVERS, isExampleCovers),
    },
    landingUrls: override(env, ENV_LANDING_URLS, isLandingUrls) ?? DEFAULT_LANDING_URLS,
  };
}

export const config: AppConfig = loadConfig(import.meta.env);
