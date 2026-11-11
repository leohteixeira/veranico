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
});
