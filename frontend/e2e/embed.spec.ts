import { expect, test } from "@playwright/test";

import { mockNetwork } from "./routes";

/** The three public reference routes of SPEC 11.2. */
const PUBLIC_ROUTES = [
  /^\/api\/v1\/regions$/,
  /^\/api\/v1\/regions\/[^/]+\/cells$/,
  /^\/api\/v1\/weather\/seasons$/,
];

/** A host page as the portfolio would write it: a frame, and a listener for its messages. */
const HOST_PAGE = `<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><title>Embed host</title></head>
  <body style="margin: 0">
    <iframe
      id="veranico"
      title="Veranico map"
      src="/embed/map?region=sorriso&lang=en&theme=light"
      style="width: 720px; height: 480px; border: 0"
    ></iframe>
    <script>
      window.received = [];
      window.addEventListener("message", (event) => {
        const frame = document.getElementById("veranico");
        if (event.source === frame.contentWindow && event.origin === window.location.origin) {
          window.received.push(event.data);
        }
      });
    </script>
  </body>
</html>`;

test("embed in a frame: map, timeline, ready message, public routes only [R-12.5-4] [R-12.5-3] [R-12.5-1]", async ({
  page,
  context,
  baseURL,
}) => {
  const api = await mockNetwork(page, baseURL ?? "");
  await page.route("**/embed-host.html", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: HOST_PAGE }),
  );
  // A workspace cookie left by the application on this origin: the embed must not send it.
  await context.addCookies([
    { name: "veranico_workspace", value: "ws-of-another-visit", url: baseURL ?? "" },
  ]);

  await page.goto("/embed-host.html");
  const frame = page.frameLocator("#veranico");

  await expect(frame.getByRole("region", { name: "Map of Sorriso" })).toBeVisible();
  await expect(frame.locator("canvas.risk-layer")).toBeVisible();
  await expect(frame.getByRole("slider", { name: "Season" })).toBeVisible();
  await expect(frame.locator(".map-notes__synthetic")).toBeVisible();
  await expect(frame.getByRole("textbox")).toHaveCount(0);
  await expect(frame.getByRole("tablist")).toHaveCount(0);

  // The host page hears from the frame once the map has drawn, and only that.
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { received: unknown[] }).received))
    .toEqual([{ type: "veranico:embed-ready" }]);

  // Another season is another reference request, and no second announcement.
  await frame.getByRole("button", { name: "Show one season" }).click();
  await expect.poll(() => api.calls.some((call) => call.query.has("season"))).toBe(true);
  await expect(frame.getByRole("button", { name: "All seasons" })).toBeVisible();

  expect(api.calls.length).toBeGreaterThanOrEqual(4);
  for (const call of api.calls) {
    expect(call.method).toBe("GET");
    expect(PUBLIC_ROUTES.some((route) => route.test(call.path))).toBe(true);
    expect(call.headers.cookie).toBeUndefined();
    expect(call.headers["veranico-allowance-code"]).toBeUndefined();
  }
  expect(api.calls.some((call) => call.path.endsWith("/chat"))).toBe(false);
  expect(
    await page.evaluate(() => (window as unknown as { received: unknown[] }).received),
  ).toHaveLength(1);
});
