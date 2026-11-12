import { describe, expect, it } from "vitest";

import { createApiClient } from "../../api/client";
import { parseEventText } from "../../api/sse";
import {
  CONVERSATION_ID,
  INDEX,
  LIMIT_CENTS,
  POINT,
  QUOTE_ID,
  SUBMISSION_ID,
  backtestResult,
} from "../fixtures/bodies";
import { chatEvents, happyPath } from "../fixtures/streams";
import { MOCK_SENTINEL, createMockState, handle } from "./handlers";
import { SCENARIOS, scenarioFrom, type Scenario } from "./scenarios";

const BASE_URL = "http://veranico.test";

function mock(scenario: Scenario = "happy") {
  const state = createMockState(scenario);
  const client = createApiClient({ baseUrl: BASE_URL, fetch: (request) => handle(request, state) });
  const chat = async (locale: "en" | "pt-BR" = "en") => {
    const { data, response } = await client.POST("/api/v1/chat", {
      body: { conversation_id: null, message: "hello", locale, map_point: null },
      parseAs: "text",
    });
    return { status: response.status, events: parseEventText(data ?? "") };
  };
  return { state, client, chat };
}

describe("mock API [R-12-1] [R-16.7-1]", () => {
  it("answers the read routes with bodies of the contract", async () => {
    const { client } = mock();

    const regions = await client.GET("/api/v1/regions");
    expect(regions.data?.map((region) => region.region_id)).toEqual([
      "sul-de-minas",
      "sorriso",
      "ribeirao-preto",
    ]);
    // Sul de Minas is the recording's region, served from the real cube; the others are
    // synthetic fixtures and labelled so.
    expect(regions.data?.map((region) => region.synthetic)).toEqual([false, true, true]);

    const cells = await client.GET("/api/v1/regions/{id}/cells", {
      params: {
        path: { id: "sorriso" },
        query: {
          metric: "season_anomaly",
          season: 1987,
          index_type: "rainfall_below",
          window_start: "10-01",
          window_end: "11-30",
          trigger: 280,
          exit: 160,
        },
      },
    });
    expect(cells.data?.metric).toBe("season_anomaly");
    expect(cells.data?.values).toHaveLength((cells.data?.nx ?? 0) * (cells.data?.ny ?? 0));

    const seasons = await client.GET("/api/v1/weather/seasons", {
      params: {
        query: {
          lat: POINT.lat,
          lon: POINT.lon,
          limit_cents: LIMIT_CENTS,
          index_type: INDEX.index_type,
          window_start: INDEX.window.start,
          window_end: INDEX.window.end,
          trigger: INDEX.trigger,
          exit: INDEX.exit,
        },
      },
    });
    // The recorded cover answers the recorded backtest's seasons.
    expect(seasons.data?.seasons).toEqual(backtestResult().seasons);
    expect(seasons.data?.seasons.some((season) => (season.payout?.amount_cents ?? 0) > 0)).toBe(
      true,
    );
    expect(seasons.data?.seasons.some((season) => season.payout?.amount_cents === 0)).toBe(true);

    expect((await client.GET("/api/v1/allowance")).data?.messages_left).toBeGreaterThan(0);
    expect((await client.POST("/api/v1/workspace/api-keys")).data?.key_id).toBeTypeOf("string");
  });

  it("serves the happy path one turn per request and follows the quote through its states", async () => {
    const { client, chat } = mock();
    expect((await client.GET("/api/v1/quotes")).data).toEqual([]);

    const streamed = [];
    for (let turn = 0; turn < 4; turn += 1) streamed.push(...(await chat()).events);
    expect(streamed).toEqual(chatEvents("en"));

    const quote = await client.GET("/api/v1/quotes/{id}", { params: { path: { id: QUOTE_ID } } });
    expect(quote.data?.status).toBe("pending_approval");
    const conversation = await client.GET("/api/v1/conversations/{id}", {
      params: { path: { id: CONVERSATION_ID } },
    });
    expect(conversation.data?.messages).toHaveLength(8);

    const decided = await client.POST("/api/v1/approvals/{id}/decision", {
      params: { path: { id: SUBMISSION_ID } },
      body: { approve: true, note: null },
    });
    expect(decided.data?.status).toBe("approved");

    const again = await client.POST("/api/v1/approvals/{id}/decision", {
      params: { path: { id: SUBMISSION_ID } },
      body: { approve: false, note: null },
    });
    expect(again.response.status).toBe(409);
    expect(again.error?.code).toBe("invalid_state");

    const deliveries = [];
    for (let read = 0; read < 3; read += 1) {
      const approvals = await client.GET("/api/v1/approvals");
      deliveries.push(approvals.data?.[0]?.delivery.status);
    }
    expect(deliveries).toEqual(["not_started", "delivering", "delivered"]);
    const submitted = await client.GET("/api/v1/quotes/{id}", {
      params: { path: { id: QUOTE_ID } },
    });
    expect(submitted.data?.status).toBe("submitted");
    expect(submitted.data?.submission?.delivery.receipt_id).not.toBeNull();
  });

  it("answers in the language of the request", async () => {
    const { chat } = mock();

    expect((await chat("pt-BR")).events).toEqual(happyPath("pt-BR").turns[0]);
  });

  it("each scenario shapes POST /chat", async () => {
    const flagged = await mock("flagged").chat();
    expect(flagged.events.some((event) => event.type === "grounding_flagged")).toBe(true);

    const failed = await mock("error").chat();
    expect(failed.events.map((event) => event.type).slice(-2)).toEqual(["error", "done"]);

    const cut = await mock("cut").chat();
    expect(cut.events[0]?.type).toBe("started");
    expect(cut.events.some((event) => event.type === "done")).toBe(false);

    for (const scenario of ["exhausted", "ceiling"] as const) {
      const { client } = mock(scenario);
      const refused = await client.POST("/api/v1/chat", {
        body: { conversation_id: null, message: "hello", locale: "en", map_point: null },
      });
      expect(refused.response.status).toBe(429);
      expect(refused.error?.replay_available).toBe(true);
    }
  });

  it("answers an unknown route or identifier with a problem document", async () => {
    const { client, state } = mock();

    const missing = await client.GET("/api/v1/quotes/{id}", { params: { path: { id: "Q-NONE" } } });
    expect(missing.response.status).toBe(404);
    expect(missing.error?.code).toBe("not_found");

    const unknown = await handle(new Request(`${BASE_URL}/api/v1/nothing`), state);
    expect(unknown.status).toBe(404);
    expect(unknown.headers.get("content-type")).toBe("application/problem+json");
  });

  it("reads the scenario from the address", () => {
    expect(scenarioFrom("?mock=cut")).toBe("cut");
    expect(scenarioFrom("?mock=nothing")).toBe("happy");
    expect(scenarioFrom("")).toBe("happy");
    expect(SCENARIOS).toContain("happy");
    expect(MOCK_SENTINEL).toBe("veranico-development-mock-layer");
  });
});
