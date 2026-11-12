import { readFileSync } from "node:fs";
import { join } from "node:path";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientProvider, createApiClient } from "./api/client";
import type { components } from "./api/schema";
import { STACKED_QUERY, Shell } from "./App";
import { config } from "./config";
import { CONVERSATION_STORAGE_KEY } from "./hooks/storage";
import { I18nProvider, translate, type Locale } from "./i18n";
import { formatMoney } from "./i18n/format";
import { createMockState, handle, type MockState } from "./test/mocks/handlers";
import { ViewProvider } from "./state/view";
import { CONVERSATION_ID, INDEX, PREMIUM_CENTS, QUOTE_ID, REGIONS } from "./test/fixtures/bodies";
import { happyPath } from "./test/fixtures/streams";

type Schemas = components["schemas"];

const BASE_URL = "http://veranico.test";
/** The shell's style sheet as text: jsdom applies no media queries, so its rules are read. */
const styles = readFileSync(join(import.meta.dirname, "app.css"), "utf8");
const EXAMPLE = config.exampleCovers["sul-de-minas"];
if (EXAMPLE === undefined) throw new Error("the first region has an example cover");

/** Every space as a plain space, as Testing Library reads the text of the page. */
function plain(text: string | null | undefined): string {
  return (text ?? "").replaceAll(" ", " ");
}

interface Harness {
  state: MockState;
  /** Every request, as `METHOD /path?query`. */
  calls: string[];
}

interface Options {
  locale?: Locale;
  /** Happy-path turns the stored conversation already has. */
  turns?: number;
  /** Answers a request before the mock layer does. */
  intercept?: (request: Request) => Response | null;
}

function renderApp({ locale = "en", turns = 0, intercept }: Options = {}): Harness {
  const state = createMockState("happy");
  state.turns = turns;
  if (turns >= 4) state.stage = "pending";
  else if (turns >= 2) state.stage = "draft";
  const calls: string[] = [];
  const client = createApiClient({
    baseUrl: BASE_URL,
    fetch: (request) => {
      const url = new URL(request.url);
      calls.push(`${request.method} ${url.pathname}${url.search}`);
      return Promise.resolve(intercept?.(request) ?? null).then(
        (answer) => answer ?? handle(request, state),
      );
    },
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ApiClientProvider client={client}>
        <I18nProvider locale={locale}>
          <ViewProvider>
            <Shell />
          </ViewProvider>
        </I18nProvider>
      </ApiClientProvider>
    </QueryClientProvider>,
  );
  return { state, calls };
}

function cellCalls(calls: readonly string[]): URLSearchParams[] {
  return calls
    .filter((call) => call.startsWith("GET /api/v1/regions/") && call.includes("/cells"))
    .map((call) => new URLSearchParams(call.slice(call.indexOf("?"))));
}

function regionSelect(name = "Region"): HTMLElement {
  return screen.getByRole("combobox", { name: new RegExp(`^${name}`) });
}

/** Opens the region list and picks the option whose text starts with `name`. */
function chooseRegion(name: string): void {
  fireEvent.click(regionSelect());
  fireEvent.click(screen.getByRole("option", { name: new RegExp(`^${name}`) }));
}

/** Makes the page as narrow as the stacked layout, as far as media queries can tell. */
function narrowScreen(): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === STACKED_QUERY,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

describe("application shell [R-12.1-1] [R-16.7-1]", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1280);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(800);
    // jsdom has no canvas: the risk layer draws nothing, which these tests do not look at.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("opens on the first region with its example cover [R-12.1-1] [R-12.1-2]", async () => {
    const { calls } = renderApp();

    await waitFor(() => {
      expect(regionSelect()).toHaveAttribute("data-value", "sul-de-minas");
    });
    expect(await screen.findByRole("region", { name: "Map of Sul de Minas" })).toBeInTheDocument();

    // The risk layer is asked for with the example's index definition, for all seasons.
    await waitFor(() => {
      expect(cellCalls(calls)).toHaveLength(1);
    });
    const [query] = cellCalls(calls);
    expect(query?.get("metric")).toBe("trigger_frequency");
    expect(query?.get("trigger")).toBe(String(EXAMPLE.cover.index.trigger));
    expect(query?.get("season")).toBeNull();

    // The four pieces around the map, and nothing asked of the visitor yet.
    expect(screen.getByRole("heading", { level: 1, name: "Veranico" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Risk" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Conversation" })).toBeInTheDocument();
    expect(await screen.findByRole("slider")).toBeInTheDocument();
    expect(window.localStorage.getItem(CONVERSATION_STORAGE_KEY)).toBeNull();
  });

  it("choosing another region opens it with its own example", async () => {
    const { calls } = renderApp();
    await waitFor(() => {
      expect(regionSelect()).toHaveAttribute("data-value", "sul-de-minas");
    });

    chooseRegion("Sorriso");
    expect(await screen.findByRole("region", { name: "Map of Sorriso" })).toBeInTheDocument();
    await waitFor(() => {
      expect(calls.some((call) => call.startsWith("GET /api/v1/regions/sorriso/cells"))).toBe(true);
    });
  });

  it("reload_restores_conversation_tabs_and_map [R-12.2-5]", async () => {
    window.localStorage.setItem(CONVERSATION_STORAGE_KEY, CONVERSATION_ID);
    const { calls } = renderApp({ turns: 4 });

    // The conversation is back, with what the visitor asked.
    const [firstRequest] = happyPath("en").requests;
    // (The first example offers the same words until the conversation is restored.)
    await waitFor(() => {
      expect(document.querySelector(".msg--user .msg__text")?.textContent).toBe(firstRequest);
    });

    // The priced quote is pinned: its tab is open on it, and the approval waits in the queue.
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Quote" })).toHaveAttribute("aria-selected", "true");
    });
    expect(await screen.findByRole("heading", { name: QUOTE_ID })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /^Approvals\s*1 pending$/ })).toBeInTheDocument();
    });

    // The map is on the region of the resolved place, coloured for the quote's index definition.
    expect(regionSelect()).toHaveAttribute("data-value", "sul-de-minas");
    await waitFor(() => {
      const last = cellCalls(calls).at(-1);
      expect(last?.get("trigger")).toBe(String(INDEX.trigger));
      expect(last?.get("exit")).toBe(String(INDEX.exit));
    });
    expect(calls).toContain(`GET /api/v1/conversations/${CONVERSATION_ID}`);
    expect(calls).toContain(`GET /api/v1/quotes/${QUOTE_ID}`);
    // Restoring reads; it never sends a message.
    expect(calls.some((call) => call.startsWith("POST"))).toBe(false);
  });

  it("start over returns to the region's example and the Risk tab", async () => {
    window.localStorage.setItem(CONVERSATION_STORAGE_KEY, CONVERSATION_ID);
    const { calls } = renderApp({ turns: 4 });
    expect(await screen.findByRole("heading", { name: QUOTE_ID })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Start over" }));

    expect(screen.getByRole("tab", { name: "Risk" })).toHaveAttribute("aria-selected", "true");
    expect(window.localStorage.getItem(CONVERSATION_STORAGE_KEY)).toBeNull();
    await waitFor(() => {
      expect(cellCalls(calls).at(-1)?.get("trigger")).toBe(String(EXAMPLE.cover.index.trigger));
    });
    // The conversation is gone; the region's example is offered again.
    expect(document.querySelector(".msg--user")).toBeNull();
    expect(screen.getByRole("button", { name: new RegExp(EXAMPLE.label) })).toBeVisible();
  });

  it("the conversation stops saying an approval waits once a person has decided it [R-12.4-7]", async () => {
    window.localStorage.setItem(CONVERSATION_STORAGE_KEY, CONVERSATION_ID);
    const { state } = renderApp({ turns: 4 });
    const waiting = "A person decides this submission in the Approvals tab.";
    expect(await screen.findByText(waiting)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Approvals/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(state.stage).toBe("approved");
      expect(screen.queryByText(waiting)).not.toBeInTheDocument();
    });
  });

  it("unknown_stored_conversation_starts_fresh", async () => {
    window.localStorage.setItem(CONVERSATION_STORAGE_KEY, "cv-forgotten");
    const { calls } = renderApp();

    await waitFor(() => {
      expect(calls).toContain("GET /api/v1/conversations/cv-forgotten");
    });
    // The identifier nobody knows is forgotten, and the application opens as on a first visit.
    await waitFor(() => {
      expect(window.localStorage.getItem(CONVERSATION_STORAGE_KEY)).toBeNull();
    });
    await waitFor(() => {
      expect(regionSelect()).toHaveAttribute("data-value", "sul-de-minas");
    });
    expect(screen.getByRole("tab", { name: "Risk" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(cellCalls(calls).at(-1)?.get("trigger")).toBe(String(EXAMPLE.cover.index.trigger));
    });
  });

  it("a restored place outside every region shows the single-cell state [R-12.4-6]", async () => {
    const outside: Schemas["ConversationView"] = {
      conversation_id: "cv-outside",
      messages: [
        {
          message_id: "m-0001",
          role: "user",
          created_at: "2026-11-10T14:05:00Z",
          text: "A farm near Cascavel.",
          tools: [],
          flagged: [],
        },
        {
          message_id: "m-0002",
          role: "assistant",
          created_at: "2026-11-10T14:05:20Z",
          text: "",
          tools: [
            {
              call_id: "call-1",
              tool: "resolve_location",
              status: "ok",
              duration_ms: 300,
              summary: {
                code: "tool.resolve_location",
                params: { label: "Cascavel, PR", lat: -24.96, lon: -53.46 },
              },
              result: { label: "Cascavel, PR", lat: -24.96, lon: -53.46 },
              error: null,
            },
          ],
          flagged: [],
        },
      ],
    };
    window.localStorage.setItem(CONVERSATION_STORAGE_KEY, "cv-outside");
    const { calls } = renderApp({
      intercept: (request) =>
        new URL(request.url).pathname === "/api/v1/conversations/cv-outside"
          ? new Response(JSON.stringify(outside), {
              headers: { "content-type": "application/json" },
            })
          : null,
    });

    await waitFor(() => {
      expect(regionSelect()).toHaveTextContent("Outside the showcase regions");
    });
    expect(screen.getByText(translate("en", "map.outside_showcase"))).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Map" })).toBeInTheDocument();
    // No region, so no regional layer and no season series are asked for the place.
    expect(calls.some((call) => call.includes("lat=-24.96"))).toBe(false);
    expect(cellCalls(calls).every((query) => query.get("trigger") !== null)).toBe(true);
    expect(calls.filter((call) => call.includes("/cells")).length).toBeLessThanOrEqual(1);

    // A showcase region is one choice away.
    chooseRegion("Sorriso");
    expect(await screen.findByRole("region", { name: "Map of Sorriso" })).toBeInTheDocument();
  });

  it("a synthetic region is not credited to ERA5-Land in the attribution [R-12.6-2]", async () => {
    // The recorded region is real: here the API says every region is generated.
    renderApp({
      intercept: (request) =>
        new URL(request.url).pathname === "/api/v1/regions"
          ? new Response(JSON.stringify(REGIONS.map((item) => ({ ...item, synthetic: true }))), {
              headers: { "content-type": "application/json" },
            })
          : null,
    });

    await screen.findByRole("slider");
    const attribution = screen.getByLabelText(translate("en", "attribution.label"));
    expect(attribution).toHaveTextContent(translate("en", "app.weather_attribution_synthetic"));
    expect(attribution).not.toHaveTextContent("ERA5-Land");
  });

  it("a region with real weather keeps the reanalysis credit [R-12.6-2]", async () => {
    renderApp({
      locale: "pt-BR",
      intercept: (request) =>
        new URL(request.url).pathname === "/api/v1/regions"
          ? new Response(JSON.stringify(REGIONS.map((item) => ({ ...item, synthetic: false }))), {
              headers: { "content-type": "application/json" },
            })
          : null,
    });

    await screen.findByRole("slider");
    const attribution = screen.getByLabelText(translate("pt-BR", "attribution.label"));
    expect(attribution).toHaveTextContent(translate("pt-BR", "app.weather_attribution"));
    expect(attribution).not.toHaveTextContent(
      translate("pt-BR", "app.weather_attribution_synthetic"),
    );
  });

  it("language_switch_rerenders_every_text_and_number [R-12.1-2]", async () => {
    window.localStorage.setItem(CONVERSATION_STORAGE_KEY, CONVERSATION_ID);
    renderApp({ turns: 4 });
    const quote = await screen.findByRole("tabpanel");
    await within(quote).findByRole("heading", { name: QUOTE_ID });
    expect(plain(quote.textContent)).toContain(plain(formatMoney(PREMIUM_CENTS, "en")));
    expect(document.documentElement.lang).toBe("en");

    fireEvent.click(screen.getByRole("button", { name: /Português/ }));

    // Numbers follow the language: the same premium, written the Brazilian way.
    const premium = plain(formatMoney(PREMIUM_CENTS, "pt-BR"));
    expect(premium).not.toBe(plain(formatMoney(PREMIUM_CENTS, "en")));
    expect(plain(screen.getByRole("tabpanel").textContent)).toContain(premium);
    expect(plain(screen.getByRole("tabpanel").textContent)).not.toContain(
      plain(formatMoney(PREMIUM_CENTS, "en")),
    );

    // Every piece of the screen is in Portuguese: top row, map, tabs, conversation, timeline.
    expect(document.documentElement.lang).toBe("pt-BR");
    const select = regionSelect(translate("pt-BR", "region.label"));
    expect(select).toHaveTextContent("Sul de Minas · Café");
    expect(
      screen.getByRole("region", {
        name: translate("pt-BR", "map.label", { region: "Sul de Minas" }),
      }),
    ).toBeInTheDocument();
    for (const key of ["tab.risk", "tab.history", "tab.quote"] as const) {
      expect(screen.getByRole("tab", { name: translate("pt-BR", key) })).toBeInTheDocument();
    }
    expect(
      screen.getByRole("heading", { name: translate("pt-BR", "chat.title") }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: translate("pt-BR", "timeline.label") }),
    ).toBeInTheDocument();
    expect(screen.getByText(translate("pt-BR", "quote.premium"))).toBeInTheDocument();
    expect(screen.queryByText(translate("en", "quote.premium"))).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Conversation" })).not.toBeInTheDocument();
  });

  it("layout_stacks_in_order_below_1100 [R-12.1-6]", async () => {
    narrowScreen();
    renderApp();
    await waitFor(() => {
      expect(regionSelect()).toHaveAttribute("data-value", "sul-de-minas");
    });

    // One document order serves both layouts; stacked, it is the order on the page.
    const app = screen.getByRole("main");
    expect(app).toHaveAttribute("data-layout", "stacked");
    expect([...app.children].map((child) => child.className.split(" ").at(-1))).toEqual([
      "app__top",
      "app__map",
      "app__timeline",
      "app__tabs",
      "app__chat",
    ]);
    expect(REGIONS).toHaveLength(3);

    // The style sheet stacks at the same width the shell stops reserving room for the cards,
    // and nothing in the stacked rules keeps a fixed card width that could overflow 390 pixels.
    const media = `@media ${STACKED_QUERY}`;
    expect(styles).toContain(media);
    const stackedRules = styles.slice(styles.indexOf(media));
    expect(stackedRules).toContain("flex-direction: column");
    expect(stackedRules).toContain("position: static");
    expect(stackedRules).toContain("width: auto");
    expect(stackedRules).not.toMatch(/(?<![-\w])width:\s*\d/);
  });

  it("on a wide screen the map is the stage under the cards [R-12.1-1]", async () => {
    renderApp();
    await waitFor(() => {
      expect(regionSelect()).toHaveAttribute("data-value", "sul-de-minas");
    });
    const app = screen.getByRole("main");
    expect(app).toHaveAttribute("data-layout", "stage");
    expect(app.querySelector(".app__map .map-stage")).not.toBeNull();
    // Risk leaves the room to the map; a tab of tables and charts takes more of it.
    expect(app).not.toHaveAttribute("data-wide");
    fireEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(app).toHaveAttribute("data-wide");
  });
});
