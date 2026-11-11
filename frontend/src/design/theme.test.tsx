import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MAP_PAINT, THEME_STORAGE_KEY, applyTheme, resolveTheme, useTheme } from "./theme";

/** A stand-in for the system colour scheme, with a switch the test can flip. */
function stubSystem(initiallyDark: boolean) {
  const listeners = new Set<() => void>();
  const query = {
    matches: initiallyDark,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => query),
  );
  return {
    set(dark: boolean) {
      query.matches = dark;
      for (const listener of listeners) listener();
    },
  };
}

beforeEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("theme", () => {
  it("[R-12.6-1] theme_follows_system_until_switched", () => {
    const system = stubSystem(false);
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");

    act(() => system.set(true));
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");

    act(() => result.current.setTheme("light"));
    expect(result.current.theme).toBe("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    act(() => system.set(false));
    act(() => system.set(true));
    expect(result.current.theme).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("[R-12.6-1] stored_theme_wins_over_system", () => {
    stubSystem(false);
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("an unknown stored value is ignored", () => {
    expect(resolveTheme("sepia", true)).toBe("dark");
    expect(resolveTheme(null, false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
  });

  it("a forced theme is applied without being stored", () => {
    stubSystem(false);

    const { result } = renderHook(() => useTheme("dark"));

    expect(result.current.theme).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it("follows the system when storage is unavailable", () => {
    stubSystem(true);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");

    act(() => result.current.setTheme("light"));
    expect(result.current.theme).toBe("light");
  });

  it("applies the theme to the given root", () => {
    const root = document.createElement("div");
    applyTheme("dark", root);
    expect(root.dataset.theme).toBe("dark");
  });

  it("[R-12.6-1] both themes carry the same map paint: six sequential and seven diverging stops", () => {
    for (const paint of [MAP_PAINT.light, MAP_PAINT.dark]) {
      expect(paint.sequential).toHaveLength(6);
      expect(paint.diverging).toHaveLength(7);
      expect(Object.keys(paint.veil).sort()).toEqual(["relief", "satellite"]);
    }
    expect(Object.keys(MAP_PAINT.dark).sort()).toEqual(Object.keys(MAP_PAINT.light).sort());
  });

  it("the marker and its label keep their contrast over any basemap and any risk colour", () => {
    const channel = (value: number) => {
      const c = value / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    const luminance = ([r, g, b]: readonly number[]) =>
      0.2126 * channel(r ?? 0) + 0.7152 * channel(g ?? 0) + 0.0722 * channel(b ?? 0);
    const contrast = (a: readonly number[], b: readonly number[]) => {
      const [low, high] = [luminance(a), luminance(b)].sort((x, y) => x - y);
      return ((high ?? 0) + 0.05) / ((low ?? 0) + 0.05);
    };
    const hex = (value: string) => {
      const digits = /^#([0-9a-f]{6})$/i.exec(value)?.[1];
      if (digits === undefined) throw new Error(`not a six-digit hex colour: ${value}`);
      return [0, 2, 4].map((at) => parseInt(digits.slice(at, at + 2), 16));
    };
    /** A translucent colour laid over an opaque one. */
    const over = (rgba: string, under: readonly number[]) => {
      const parts = /^rgba\((\d+),(\d+),(\d+),([\d.]+)\)$/.exec(rgba.replaceAll(" ", ""));
      if (parts === null) throw new Error(`not an rgba colour: ${rgba}`);
      const alpha = Number(parts[4]);
      return [1, 2, 3].map(
        (at, channelAt) => Number(parts[at]) * alpha + (under[channelAt] ?? 0) * (1 - alpha),
      );
    };

    for (const paint of [MAP_PAINT.light, MAP_PAINT.dark]) {
      // The word on the marker is text: AA for text.
      expect(contrast(hex(paint.markerInk), hex(paint.marker))).toBeGreaterThanOrEqual(4.5);
      // The ring and the cell outline are drawn on a halo. Whatever is under the halo, from white
      // to black, the stroke keeps the 3:1 of a graphic that carries meaning.
      for (const ground of [
        [255, 255, 255],
        [0, 0, 0],
      ]) {
        expect(contrast(hex(paint.marker), over(paint.halo, ground))).toBeGreaterThanOrEqual(3);
        expect(contrast(hex(paint.label), over(paint.halo, ground))).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
