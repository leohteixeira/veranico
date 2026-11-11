import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import type { BasemapId } from "../config";

export type Theme = "light" | "dark";

/** One of the three things the application keeps in local storage (with locale and conversation). */
export const THEME_STORAGE_KEY = "veranico.theme";

const SYSTEM_DARK = "(prefers-color-scheme: dark)";

function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark";
}

/** The stored choice wins; without one the theme follows the system. */
export function resolveTheme(stored: string | null, systemPrefersDark: boolean): Theme {
  if (isTheme(stored)) return stored;
  return systemPrefersDark ? "dark" : "light";
}

// Storage can be unavailable (a third-party frame, private mode): the theme then follows the system.
export function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : null;
  } catch {
    return null;
  }
}

function writeStoredTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // The choice still holds for this page view.
  }
}

function systemQuery(): MediaQueryList | null {
  return typeof window.matchMedia === "function" ? window.matchMedia(SYSTEM_DARK) : null;
}

function subscribeToSystem(onChange: () => void): () => void {
  const query = systemQuery();
  if (query === null) return () => undefined;
  query.addEventListener("change", onChange);
  return () => {
    query.removeEventListener("change", onChange);
  };
}

function systemPrefersDark(): boolean {
  return systemQuery()?.matches ?? false;
}

export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement): void {
  root.dataset.theme = theme;
}

export interface ThemeController {
  theme: Theme;
  /** An explicit choice: stored, and from then on it wins over the system. */
  setTheme: (theme: Theme) => void;
}

/**
 * The active theme. It follows the system until the visitor switches. `forced` pins the theme
 * without storing it (the embed route takes it from its query string).
 */
export function useTheme(forced?: Theme): ThemeController {
  const [stored, setStored] = useState<Theme | null>(readStoredTheme);
  const systemDark = useSyncExternalStore(subscribeToSystem, systemPrefersDark, () => false);
  const theme = forced ?? resolveTheme(stored, systemDark);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    writeStoredTheme(next);
    setStored(next);
  }, []);

  return { theme, setTheme };
}

/** Red, green, blue (0 to 255) and alpha (0 to 1). */
export type Rgba = readonly [number, number, number, number];

/** What the map canvas and the vector layers are painted with; CSS tokens cannot reach a canvas. */
export interface MapPaint {
  /** Laid over the tiles so the risk layer and the cards read on top of them. */
  veil: Record<BasemapId, string>;
  /** Wash over the area outside the weather cube. */
  outside: Record<BasemapId, string>;
  /** Flat stand-in for the basemap under a legend swatch. */
  swatchBase: Record<BasemapId, string>;
  /** Trigger frequency, low to high: six stops. */
  sequential: readonly Rgba[];
  /** Season anomaly, dry to wet through a neutral midpoint: seven stops. */
  diverging: readonly Rgba[];
  label: string;
  halo: string;
  marker: string;
  markerInk: string;
  grid: string;
  cube: string;
}

// Light: the `atlas` paint of the approved preview. Dark: its `noturno` paint (darkened satellite,
// luminous ramp). Source: design-reference/vr/app.js, `DIR`.
export const MAP_PAINT: Record<Theme, MapPaint> = {
  light: {
    veil: { satellite: "rgba(250,246,238,.40)", relief: "rgba(255,250,240,.12)" },
    outside: { satellite: "rgba(250,246,238,.34)", relief: "rgba(239,234,223,.46)" },
    swatchBase: { satellite: "#a9b0a0", relief: "#f1ede4" },
    sequential: [
      [251, 233, 200, 0.6],
      [246, 201, 138, 0.7],
      [236, 159, 90, 0.76],
      [217, 113, 60, 0.82],
      [179, 71, 42, 0.86],
      [125, 38, 23, 0.9],
    ],
    diverging: [
      [163, 57, 31, 0.88],
      [217, 113, 60, 0.78],
      [241, 192, 143, 0.68],
      [232, 228, 220, 0.5],
      [167, 211, 214, 0.68],
      [78, 163, 176, 0.8],
      [18, 112, 127, 0.9],
    ],
    label: "#1b2428",
    halo: "rgba(255,253,248,.92)",
    marker: "#143c44",
    markerInk: "#fffdf8",
    grid: "rgba(27,36,40,.13)",
    cube: "rgba(27,36,40,.55)",
  },
  dark: {
    veil: { satellite: "rgba(6,10,16,.52)", relief: "rgba(8,12,18,.80)" },
    outside: { satellite: "rgba(6,10,16,.32)", relief: "rgba(6,10,16,.3)" },
    swatchBase: { satellite: "#17201c", relief: "#2a2d31" },
    sequential: [
      [58, 32, 96, 0.32],
      [120, 44, 130, 0.48],
      [190, 60, 112, 0.62],
      [236, 104, 64, 0.74],
      [248, 168, 52, 0.84],
      [255, 230, 128, 0.92],
    ],
    diverging: [
      [255, 218, 110, 0.92],
      [242, 124, 62, 0.8],
      [172, 62, 112, 0.58],
      [70, 72, 92, 0.26],
      [46, 104, 170, 0.56],
      [52, 150, 222, 0.76],
      [104, 200, 250, 0.88],
    ],
    label: "#eef2f6",
    halo: "rgba(6,10,16,.88)",
    marker: "#ffffff",
    markerInk: "#0a0e13",
    grid: "rgba(255,255,255,.14)",
    cube: "rgba(255,255,255,.6)",
  },
};
