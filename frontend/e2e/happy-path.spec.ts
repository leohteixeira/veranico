import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { QUOTE_ID, RECEIPT_ID } from "../src/test/fixtures/bodies";
import { happyPath } from "../src/test/fixtures/streams";
import { LIVE_TILES, mockNetwork } from "./routes";

const EVIDENCE = join(import.meta.dirname, "evidence");
const [, PRICE_IT, DRAFT_IT, SUBMIT_IT] = happyPath("en").requests;
const DECISION_NOTE = "Checked against the client's brief.";

async function say(page: Page, text: string): Promise<void> {
  const composer = page.getByRole("textbox");
  await expect(composer).toBeEditable();
  await composer.fill(text);
  await composer.press("Enter");
}

/** The centre of one season's column on the timeline. */
async function seasonColumn(page: Page, season: number): Promise<{ x: number; y: number }> {
  const box = await page
    .locator(`.timeline-bars g[data-season="${season}"] .timeline-bars__hit`)
    .boundingBox();
  if (box === null) throw new Error(`season ${season} is not on the timeline`);
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

test("happy path: example, quote, season view, approval, delivery [R-16.7-2] [R-12.4-7] [R-12.4-9] [R-12.2-4]", async ({
  page,
  baseURL,
}) => {
  test.setTimeout(120_000);
  const api = await mockNetwork(page, baseURL ?? "");
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Region" })).toHaveValue("sul-de-minas");

  // Turn 1: the first example. The recorded stream plays: location, history, backtest.
  await page.locator(".first__example").first().click();
  await expect(page.locator(".steps__label")).toHaveText("Step 4 of 6: Price");
  await expect(page.locator(".tool__id", { hasText: "backtest_index" })).toBeVisible();

  // The map shows the marker and the risk layer, recoloured for the backtest's index.
  await expect(page.locator(".map-insured-point")).toBeVisible();
  await expect
    .poll(() =>
      api.calls
        .filter((call) => call.path.endsWith("/cells"))
        .at(-1)
        ?.query.get("trigger"),
    )
    .toBe("150");
  const painted = await page.locator("canvas.risk-layer").evaluate((canvas: HTMLCanvasElement) => {
    const context = canvas.getContext("2d");
    if (context === null) return 0;
    const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
    let count = 0;
    for (let at = 3; at < data.length; at += 4) if ((data[at] ?? 0) > 0) count += 1;
    return count;
  });
  expect(painted).toBeGreaterThan(1000);

  // Turn 2: the price. The quote is pinned and its tab opens.
  await say(page, PRICE_IT ?? "");
  await expect(page.getByRole("tab", { name: "Quote" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: QUOTE_ID })).toBeVisible();

  // From another tab, the premium in the answer opens the Quote tab on its field.
  await page.getByRole("tab", { name: "History" }).click();
  await page.locator('.fig[data-key="premium"]').last().click();
  await expect(page.getByRole("tab", { name: "Quote" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-field="premium"]')).toHaveAttribute("data-highlight", "true");

  // Turns 3 and 4: the term sheet, then the submission, which waits for a person.
  await say(page, DRAFT_IT ?? "");
  await expect(page.locator(".steps__label")).toHaveText("Step 6 of 6: Approval");
  await say(page, SUBMIT_IT ?? "");
  await expect(page.locator('.steps__segment[data-state="done"]')).toHaveCount(6);
  await expect(
    page.getByText("A person decides this submission in the Approvals tab."),
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: /Approvals\s*1 pending/ })).toBeVisible();
  expect(api.calls.filter((call) => call.path === "/api/v1/chat")).toHaveLength(4);

  // Dragging the timeline puts one season on the map, in the Risk tab and in the History chart.
  const from = await seasonColumn(page, 1990);
  const to = await seasonColumn(page, 1995);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move((from.x + to.x) / 2, to.y, { steps: 4 });
  await page.mouse.move(to.x, to.y, { steps: 4 });
  await page.mouse.up();
  await expect(page.locator(".timeline__readout")).toContainText("1995");
  await expect
    .poll(() => {
      const last = api.calls.filter((call) => call.path.endsWith("/cells")).at(-1);
      return `${last?.query.get("metric")}:${last?.query.get("season")}`;
    })
    .toBe("season_anomaly:1995");
  await page.getByRole("tab", { name: "Risk" }).click();
  await expect(page.locator(".risk")).toHaveAttribute("data-metric", "season_anomaly");
  await expect(page.locator(".legend__title")).toContainText("against the cell's median");
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByRole("tabpanel").getByRole("slider", { name: "Season" })).toHaveAttribute(
    "aria-valuetext",
    /1995/,
  );

  // The person decides: approve with a note. The delivery runs to the carrier's receipt.
  await page.getByRole("tab", { name: /Approvals/ }).click();
  await page.getByLabel("Note (optional)").fill(DECISION_NOTE);
  await page.getByRole("button", { name: "Approve" }).click();
  const delivered = page.locator('[data-delivery="delivered"]');
  await expect(delivered).toBeVisible({ timeout: 20_000 });
  await expect(delivered).toContainText(RECEIPT_ID);
  const decision = api.calls.find((call) => call.path.endsWith("/decision"));
  expect(decision?.method).toBe("POST");

  // The audit trail of the quote lists the human decision with its note.
  await page.getByRole("tab", { name: "Quote" }).click();
  const approved = page.locator('.audit__entry[data-action="audit.approved"]');
  await expect(approved).toBeVisible();
  await expect(approved.locator('[data-actor="human"]')).toHaveText("You");
  await expect(approved).toContainText(DECISION_NOTE);
  await approved.scrollIntoViewIfNeeded();

  // The weather is synthetic and the screen says so wherever its figures are.
  await expect(page.locator(".map-notes__synthetic")).toBeVisible();
  await page.screenshot({ path: join(EVIDENCE, "happy-path-1440.png") });

  // The same state on a phone: the pieces stack in order and nothing scrolls sideways.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("main")).toHaveAttribute("data-layout", "stacked");
  const layout = await page.evaluate(() => {
    const root = document.documentElement;
    const top = (name: string) =>
      (document.querySelector(`.app__${name}`)?.getBoundingClientRect().top ?? NaN) +
      window.scrollY;
    return {
      overflow: root.scrollWidth - root.clientWidth,
      tops: ["top", "map", "timeline", "tabs", "chat"].map(top),
    };
  });
  expect(layout.overflow).toBe(0);
  expect(layout.tops).toEqual([...layout.tops].sort((a, b) => a - b));
  expect(new Set(layout.tops).size).toBe(5);
  await page.screenshot({ path: join(EVIDENCE, "happy-path-390.png"), fullPage: true });

  // Nothing left the application except the basemap tiles, and nothing broke on the page.
  if (!LIVE_TILES) expect(api.external.every((url) => /\.(jpg|jpeg|png)$/.test(url))).toBe(true);
  expect(pageErrors).toEqual([]);
});
