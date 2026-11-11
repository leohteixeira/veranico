import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { LIVE_TILES, mockNetwork } from "./routes";

/**
 * The captures the design finish review reads: the first viewport on a desktop and the same page
 * on a phone, plus the dark theme with a priced quote. Not part of the gate: it runs only with
 * `E2E_REVIEW=1`, normally together with `E2E_LIVE_TILES=1` so the real basemaps are in the
 * picture. The weather in every capture is the SYNTHETIC fixture data, and the screen says so.
 *
 *     E2E_REVIEW=1 E2E_LIVE_TILES=1 pnpm exec playwright test review-captures
 */
const REVIEW = join(import.meta.dirname, "..", "..", ".impeccable", "review");

test.skip(process.env.E2E_REVIEW !== "1", "review captures are made on request");

for (const theme of ["light", "dark"] as const) {
  test(`review captures, ${theme} theme`, async ({ page, baseURL }) => {
    await mockNetwork(page, baseURL ?? "");
    await page.addInitScript((value) => {
      window.localStorage.setItem("veranico.theme", value);
      window.localStorage.setItem("veranico.locale", "en");
    }, theme);
    const settle = async () => {
      await expect(page.locator(".map-insured-point")).toBeVisible();
      await expect(page.getByRole("slider", { name: "Season" }).first()).toBeVisible();
      // Tiles and the fit animation; live tiles need the longer wait.
      await page.waitForTimeout(LIVE_TILES ? 4000 : 800);
    };

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await settle();

    if (theme === "light") {
      await page.screenshot({ path: join(REVIEW, "desktop.png"), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      await settle();
      await page.screenshot({ path: join(REVIEW, "mobile.png"), fullPage: true });
      return;
    }

    // Dark: one turn and the price, so the conversation, the tool rows and the quote are shown.
    await page.locator(".first__example").first().click();
    await expect(page.locator(".steps__label")).toHaveText("Step 4 of 6: Price");
    await page.getByRole("textbox").fill("Yes, price it.");
    await page.getByRole("textbox").press("Enter");
    await expect(page.getByRole("tab", { name: "Quote" })).toHaveAttribute("aria-selected", "true");
    await settle();
    await page.screenshot({ path: join(REVIEW, "desktop-dark-quote.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await settle();
    await page.screenshot({ path: join(REVIEW, "mobile-dark-quote.png"), fullPage: true });
  });
}
