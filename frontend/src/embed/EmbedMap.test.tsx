import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { config } from "../config";
import { ALLOWANCE_CODE_STORAGE_KEY } from "../hooks/storage";
import { translate } from "../i18n";
import { createMockState, handle } from "../test/mocks/handlers";
import { problem } from "../test/fixtures/bodies";
import { EMBED_READY, EmbedMap, createEmbedClient, embedParams, isEmbedPath } from "./EmbedMap";

/** The three public reference routes of SPEC 11.2, and nothing else. */
const PUBLIC_ROUTES = [
  /^GET \/api\/v1\/regions$/,
  /^GET \/api\/v1\/regions\/[^/]+\/cells$/,
  /^GET \/api\/v1\/weather\/seasons$/,
];

interface Harness {
  /** Every request the embed made, as the browser would send it. */
  requests: Request[];
  /** `METHOD /path` of every request. */
  routes: () => string[];
  posted: ReturnType<typeof vi.spyOn>;
}

interface Options {
  /** Answers a request before the mock layer does. */
  intercept?: (request: Request) => Promise<Response | null> | Response | null;
}

function renderEmbed(search = "", { intercept }: Options = {}): Harness {
  const state = createMockState("happy");
  const requests: Request[] = [];
  // The embed's own client is under test, so the network is replaced, not the client.
  vi.stubGlobal("fetch", (request: Request) => {
    requests.push(request.clone());
    return Promise.resolve(intercept?.(request) ?? null).then(
      (answer) => answer ?? handle(request, state),
    );
  });
  const posted = vi.spyOn(window.parent, "postMessage").mockImplementation(() => undefined);
  // Outside a browser a request needs an absolute address; the options are the embed's own.
  render(<EmbedMap search={search} client={createEmbedClient("http://veranico.test")} />);
  return {
    requests,
    routes: () => requests.map((request) => `${request.method} ${new URL(request.url).pathname}`),
    posted,
  };
}

function isCells(request: Request): boolean {
  return new URL(request.url).pathname.endsWith("/cells");
}

describe("embed route [R-12.5-1] [R-16.7-1]", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(640);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(420);
    // jsdom has no canvas: the layer is created and given its grid, and paints nothing.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.localStorage.clear();
    window.sessionStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("the embed has its own path and everything else is the application", () => {
    expect(isEmbedPath("/embed/map")).toBe(true);
    expect(isEmbedPath("/embed/map/")).toBe(true);
    expect(isEmbedPath("/")).toBe(false);
    expect(isEmbedPath("/embed")).toBe(false);
    expect(isEmbedPath("/embed/map/other")).toBe(false);
    expect(embedParams("?region=sorriso&theme=dark")).toEqual({
      regionId: "sorriso",
      theme: "dark",
    });
    expect(embedParams("?theme=sepia")).toEqual({ regionId: null, theme: null });
  });

  it("embed_renders_map_layer_and_timeline_only [R-12.5-1]", async () => {
    renderEmbed("?region=sul-de-minas");

    expect(await screen.findByRole("region", { name: "Map of Sul de Minas" })).toBeInTheDocument();
    expect(document.querySelector("canvas.risk-layer")).not.toBeNull();
    expect(screen.getByRole("region", { name: "Seasons" })).toBeInTheDocument();
    expect(await screen.findByRole("slider", { name: "Season" })).toBeInTheDocument();

    // Read-only: no conversation, no tabs, no top row, nothing to type into.
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("log")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Conversation" })).toBeNull();
  });

  it("embed_reads_region_language_and_theme_from_the_query [R-12.5-1]", async () => {
    const { requests } = renderEmbed("?region=sorriso&lang=pt-BR&theme=dark");

    expect(
      await screen.findByRole("region", {
        name: translate("pt-BR", "map.label", { region: "Sorriso" }),
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: translate("pt-BR", "timeline.label") }),
    ).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("pt-BR");
    expect(document.documentElement.dataset.theme).toBe("dark");
    // The dark theme brings its satellite basemap.
    expect(document.querySelector(".map-stage")).toHaveAttribute("data-basemap", "satellite");
    // The theme of the frame is not a preference of the visitor: nothing is stored.
    expect(window.localStorage.length).toBe(0);

    // The region's example cover is what the layer and the timeline are asked for.
    const example = config.exampleCovers.sorriso;
    await waitFor(() => {
      expect(requests.some(isCells)).toBe(true);
    });
    const cells = new URL(requests.find(isCells)?.url ?? "");
    expect(cells.pathname).toBe("/api/v1/regions/sorriso/cells");
    expect(cells.searchParams.get("trigger")).toBe(String(example?.cover.index.trigger));
  });

  it("embed_calls_only_the_three_read_routes [R-12.5-3]", async () => {
    const { routes, requests } = renderEmbed("?region=sul-de-minas");
    const slider = await screen.findByRole("slider", { name: "Season" });

    // Putting one season on the map asks for that season's cells: still a reference route.
    fireEvent.change(slider, { target: { value: "3" } });
    await waitFor(() => {
      expect(requests.some((request) => new URL(request.url).searchParams.has("season"))).toBe(
        true,
      );
    });

    expect(routes().length).toBeGreaterThanOrEqual(4);
    for (const route of routes()) {
      expect(PUBLIC_ROUTES.some((pattern) => pattern.test(route))).toBe(true);
    }
  });

  it("embed_requests_carry_no_credentials_and_no_allowance_code [R-12.5-3]", async () => {
    // A code left in this browser by the application must not travel with the embed.
    window.sessionStorage.setItem(ALLOWANCE_CODE_STORAGE_KEY, "demo-code");
    const { requests } = renderEmbed("?region=sul-de-minas&code=demo-code");
    await screen.findByRole("slider", { name: "Season" });

    expect(requests.length).toBeGreaterThanOrEqual(3);
    for (const request of requests) {
      // `omit`: no cookie is sent and none is accepted.
      expect(request.credentials).toBe("omit");
      expect(request.headers.has("Veranico-Allowance-Code")).toBe(false);
      expect(request.headers.has("Authorization")).toBe(false);
      expect(request.url).not.toContain("demo-code");
    }
  });

  it("embed_posts_the_ready_message_once_after_the_first_draw [R-12.5-4]", async () => {
    let release: (() => void) | undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { posted, requests } = renderEmbed("?region=sul-de-minas", {
      // The first risk layer waits until the test lets it through.
      intercept: (request) => (isCells(request) ? held.then(() => null) : null),
    });

    // The map and the timeline are there, the risk layer is not: nothing is announced yet.
    await screen.findByRole("slider", { name: "Season" });
    expect(requests.some(isCells)).toBe(true);
    expect(posted).not.toHaveBeenCalled();

    release?.();
    await waitFor(() => {
      expect(posted).toHaveBeenCalledTimes(1);
    });
    // The message carries its type and nothing else.
    expect(posted).toHaveBeenCalledWith({ type: "veranico:embed-ready" }, "*");
    expect(EMBED_READY).toEqual({ type: "veranico:embed-ready" });

    // Later layers (another season) are not announced again.
    fireEvent.change(screen.getByRole("slider", { name: "Season" }), { target: { value: "5" } });
    await waitFor(() => {
      expect(requests.filter(isCells).length).toBeGreaterThanOrEqual(2);
    });
    await screen.findByRole("button", { name: "All seasons" });
    expect(posted).toHaveBeenCalledTimes(1);
  });

  it("embed_posts_nothing_when_the_cells_request_fails [R-12.5-4]", async () => {
    const { posted, requests } = renderEmbed("?region=sul-de-minas", {
      intercept: (request) =>
        isCells(request)
          ? new Response(JSON.stringify(problem("internal_error", 500)), {
              status: 500,
              headers: { "content-type": "application/problem+json" },
            })
          : null,
    });

    await screen.findByRole("slider", { name: "Season" });
    await waitFor(() => {
      expect(requests.some(isCells)).toBe(true);
    });
    // The answer has been read and refused; the host keeps its static image.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(posted).not.toHaveBeenCalled();
  });

  it("embed_keeps_attribution_and_the_synthetic_label [R-12.5-1]", async () => {
    renderEmbed("?region=sul-de-minas");

    // `Region.synthetic` says the weather is generated; the label is on the map.
    expect(await screen.findByText(translate("en", "map.synthetic"))).toBeInTheDocument();

    const attribution = screen.getByLabelText("Sources and licences");
    const relief = config.basemaps.relief;
    expect(attribution).toHaveTextContent(relief.attribution);
    expect(attribution).toHaveTextContent(translate("en", "app.weather_attribution"));
    expect(attribution).toHaveTextContent(translate("en", "app.non_commercial"));
    expect(attribution).toHaveTextContent(translate("en", "app.disclaimer"));
  });

  it("unknown_region_falls_back_to_the_first [R-12.5-1]", async () => {
    const { requests } = renderEmbed("?region=atlantis");

    expect(await screen.findByRole("region", { name: "Map of Sul de Minas" })).toBeInTheDocument();
    await waitFor(() => {
      expect(requests.some(isCells)).toBe(true);
    });
    expect(new URL(requests.find(isCells)?.url ?? "").pathname).toBe(
      "/api/v1/regions/sul-de-minas/cells",
    );
  });
});
