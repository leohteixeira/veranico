import type { components } from "../api/schema";
import type { BasemapId } from "../config";
import { MAP_PAINT, type Theme } from "../design/theme";

type Region = components["schemas"]["Region"];

export const BASEMAP_IDS: readonly BasemapId[] = ["relief", "satellite"];

/** Relief in the light theme, satellite in the dark one, unless the visitor chose. */
export function activeBasemap(theme: Theme, choice: BasemapId | null): BasemapId {
  return choice ?? (theme === "dark" ? "satellite" : "relief");
}

export type LatLngBoundsTuple = [[number, number], [number, number]];

/** The bounds of a region's weather cube: south-west, then north-east. */
export function regionBounds(region: Region): LatLngBoundsTuple {
  return [
    [region.south, region.west],
    [region.north, region.east],
  ];
}

/** Pixels of the stage that the floating cards cover, from each edge. */
export interface Insets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export const NO_INSETS: Insets = { top: 0, right: 0, bottom: 0, left: 0 };

/** Air between the cube and the cards, in pixels. */
export const FIT_MARGIN = 24;

export interface FitPadding {
  paddingTopLeft: [number, number];
  paddingBottomRight: [number, number];
}

/** Leaflet's `fitBounds` padding that keeps the cube inside the area the cards leave free. */
export function fitPadding(insets: Insets, margin = FIT_MARGIN): FitPadding {
  return {
    paddingTopLeft: [insets.left + margin, insets.top + margin],
    paddingBottomRight: [insets.right + margin, insets.bottom + margin],
  };
}

export interface Veil {
  /** The colour behind the tiles; it shows through them. */
  ground: string;
  /** How much of the tiles is left. */
  tileOpacity: number;
}

const RGBA = /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)$/;

/**
 * The veil of the reference paint, laid over the tiles so the risk layer and the cards read on
 * them. A flat colour at alpha `a` over the tiles is the same picture as the tiles at opacity
 * `1 - a` over that colour, which needs no layer that moves with the map.
 */
export function veil(theme: Theme, basemap: BasemapId): Veil {
  const match = RGBA.exec(MAP_PAINT[theme].veil[basemap]);
  if (match === null) return { ground: "transparent", tileOpacity: 1 };
  const [, red, green, blue, alpha] = match;
  return {
    ground: `rgb(${red ?? "0"}, ${green ?? "0"}, ${blue ?? "0"})`,
    tileOpacity: Math.round((1 - Number(alpha)) * 100) / 100,
  };
}
