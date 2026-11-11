import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { Page } from "@playwright/test";

import { createMockState, handle, type MockState } from "../src/test/mocks/handlers";

/** The one local tile every basemap request is answered with (see `fixtures/make-tile.mjs`). */
const TILE = readFileSync(join(import.meta.dirname, "fixtures", "tile.png"));

/** With `E2E_LIVE_TILES=1` the basemaps come from their real providers, for evidence only. */
export const LIVE_TILES = process.env.E2E_LIVE_TILES === "1";

export interface ApiCall {
  method: string;
  path: string;
  query: URLSearchParams;
  /** Every header the browser sent, cookies included. */
  headers: Record<string, string>;
}

export interface MockedApi {
  state: MockState;
  calls: ApiCall[];
  /** Requests to anywhere but the application, tiles included, as URLs. */
  external: string[];
}

/**
 * Answers the page's network in the test process. Every `/api/v1/**` request goes to the handlers
 * of the mock layer, so `POST /chat` is answered with the recorded stream fixture, one turn per
 * request. Every request that leaves the application's origin is answered with the local tile when
 * it asks for an image, and refused otherwise: the run needs no network.
 */
export async function mockNetwork(page: Page, baseURL: string): Promise<MockedApi> {
  const state = createMockState("happy");
  const calls: ApiCall[] = [];
  const external: string[] = [];
  const origin = new URL(baseURL).origin;

  await page.route(
    (url) => url.origin !== origin,
    async (route) => {
      const request = route.request();
      external.push(request.url());
      if (request.resourceType() !== "image") await route.abort();
      else if (LIVE_TILES) await route.continue();
      else await route.fulfill({ status: 200, contentType: "image/png", body: TILE });
    },
  );

  await page.route(
    (url) => url.origin === origin && url.pathname.startsWith("/api/v1/"),
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      calls.push({
        method: request.method(),
        path: url.pathname,
        query: url.searchParams,
        headers: await request.allHeaders(),
      });
      const answer = await handle(
        new Request(request.url(), {
          method: request.method(),
          body: request.postData() ?? undefined,
        }),
        state,
      );
      await route.fulfill({
        status: answer.status,
        contentType: answer.headers.get("content-type") ?? "application/json",
        body: Buffer.from(await answer.arrayBuffer()),
      });
    },
  );

  return { state, calls, external };
}
