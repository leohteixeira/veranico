import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// Read from disk: Vitest does not process stylesheets, so a `?raw` import of one is empty.
const globalCss = readFileSync(join(import.meta.dirname, "global.css"), "utf8");
const tokensCss = readFileSync(join(import.meta.dirname, "tokens.css"), "utf8");

const LIGHT = ':root:not([data-theme="dark"])';
const DARK = ':root[data-theme="dark"]';

/** Custom properties of one flat rule block of tokens.css. */
function block(css: string, selector: string): Map<string, string> {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const tokens = new Map<string, string>();
  for (const match of withoutComments.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (match[1]?.trim() !== selector) continue;
    for (const declaration of (match[2] ?? "").split(";")) {
      const colon = declaration.indexOf(":");
      if (colon < 0) continue;
      const name = declaration.slice(0, colon).trim();
      if (name.startsWith("--")) tokens.set(name, declaration.slice(colon + 1).trim());
    }
  }
  return tokens;
}

function luminance(hex: string): number {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (match === null) throw new Error(`not a six-digit hex colour: ${hex}`);
  const value = parseInt(match[1] ?? "", 16);
  const channels = [(value >> 16) & 255, (value >> 8) & 255, value & 255].map((channel) => {
    const c = channel / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * (channels[0] ?? 0) + 0.7152 * (channels[1] ?? 0) + 0.0722 * (channels[2] ?? 0);
}

/** WCAG 2 contrast ratio of two opaque colours. */
function contrast(a: string, b: string): number {
  const [low, high] = [luminance(a), luminance(b)].sort((x, y) => x - y);
  return ((high ?? 0) + 0.05) / ((low ?? 0) + 0.05);
}

// Every pairing of text colour and background the interface uses for text, as [text, background].
const TEXT_PAIRS: ReadonlyArray<readonly [string, string]> = [
  ["--ink", "--card"],
  ["--ink-2", "--card"],
  ["--ink-3", "--card"],
  ["--accent", "--card"],
  ["--ok", "--card"],
  ["--danger", "--card"],
  ["--pay", "--card"],
  ["--ink", "--soft"],
  ["--ink-2", "--soft"],
  ["--ink-3", "--soft"],
  ["--accent", "--soft"],
  ["--ink", "--bg"],
  ["--accent", "--accent-wash"],
  ["--ok", "--ok-wash"],
  ["--danger", "--danger-wash"],
  ["--ink", "--warn-wash"],
  ["--btn-ink", "--btn"],
  ["--on-accent", "--accent"],
  ["--on-ok", "--ok"],
];

describe("design tokens", () => {
  it("[R-12.6-1] every_token_is_defined_in_both_themes", () => {
    const light = [...block(tokensCss, LIGHT).keys()].sort();
    const dark = [...block(tokensCss, DARK).keys()].sort();

    expect(light.length).toBeGreaterThan(20);
    expect(dark).toEqual(light);
  });

  it("[R-12.6-1] themes share type, radii and motion: those tokens are defined once", () => {
    const shared = block(tokensCss, ":root");
    const light = block(tokensCss, LIGHT);

    for (const name of ["--font-display", "--font-sans", "--font-mono", "--r", "--r-sm"]) {
      expect(shared.has(name), name).toBe(true);
      expect(light.has(name), name).toBe(false);
    }
    expect(shared.get("--font-display")).toContain("Fraunces");
    expect(shared.get("--font-sans")).toContain("IBM Plex Sans");
    expect(shared.get("--font-mono")).toContain("IBM Plex Mono");
  });

  it.each([
    ["light", LIGHT],
    ["dark", DARK],
  ])(
    "[R-12.6-1] text_and_background_pairs_meet_aa_contrast_in_both_themes (%s)",
    (_theme, selector) => {
      const tokens = block(tokensCss, selector);
      for (const [text, background] of TEXT_PAIRS) {
        const ratio = contrast(tokens.get(text) ?? "", tokens.get(background) ?? "");
        expect(ratio, `${text} on ${background}`).toBeGreaterThanOrEqual(4.5);
      }
    },
  );

  it("the focus ring is defined once for every control and motion respects the system setting", () => {
    expect(globalCss).toMatch(/:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--accent\)/);
    expect(globalCss).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
  });
});
