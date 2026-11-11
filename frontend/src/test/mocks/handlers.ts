import { isProblem } from "../../api/problems";
import type { components, paths } from "../../api/schema";
import type { AgentEvent } from "../../api/sse";
import {
  ALLOWANCE,
  API_KEY,
  CONVERSATION_ID,
  DECIDED_AT,
  QUOTE_ID,
  REGIONS,
  SUBMISSION_ID,
  approvalView,
  cellGrid,
  pendingQuote,
  problem,
  quoteSummary,
  quoteView,
  seasonSeries,
  submission,
  type DeliveryStatus,
} from "../fixtures/bodies";
import {
  conversationView,
  errorEvents,
  flaggedEvents,
  happyPath,
  replayEvents,
  serialise,
} from "../fixtures/streams";
import { DEFAULT_SCENARIO, type Scenario } from "./scenarios";

/**
 * The mock of the Veranico API for tests: pure handlers over one small state object, typed by the
 * generated `paths`, so a contract change breaks the type check here. Unit tests call it as a
 * `fetch`, and the Playwright flow answers `/api/v1/**` with it in the test process. It serves
 * SYNTHETIC fixtures and is never part of a build: `scripts/check-dist.mjs` looks for the
 * sentinel below in the built files.
 */
export const MOCK_SENTINEL = "veranico-development-mock-layer";

type Schemas = components["schemas"];
type Locale = Schemas["ChatRequest"]["locale"];

/** Where the one quote of the mock stands. */
type Stage = "none" | "draft" | "pending" | "approved" | "rejected";

export interface MockState {
  scenario: Scenario;
  /** Milliseconds between two stream chunks; `0` in tests. */
  chunkDelayMs: number;
  /** Happy-path turns already answered. */
  turns: number;
  locale: Locale;
  stage: Stage;
  decisionNote: string | null;
  /** Times the approvals were read since the approval: the delivery advances on each read. */
  deliveryReads: number;
}

export function createMockState(
  scenario: Scenario = DEFAULT_SCENARIO,
  chunkDelayMs = 0,
): MockState {
  return {
    scenario,
    chunkDelayMs,
    turns: 0,
    locale: "en",
    stage: "none",
    decisionNote: null,
    deliveryReads: 0,
  };
}

interface Call {
  params: Record<string, string>;
  query: URLSearchParams;
  body: unknown;
}

type Method = "get" | "post";

/** The `200` JSON body of one operation of the contract. */
type OkBody<P extends keyof paths, M extends Method> = paths[P][M] extends {
  responses: { 200: { content: { "application/json": infer Body } } };
}
  ? Body
  : never;

interface Route {
  method: Method;
  pattern: RegExp;
  names: string[];
  respond: (call: Call, state: MockState) => Response;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": status >= 400 ? "application/problem+json" : "application/json",
    },
  });
}

function compile(path: string): { pattern: RegExp; names: string[] } {
  const names: string[] = [];
  const source = path.replace(/\{([a-z_]+)\}/g, (_match, name: string) => {
    names.push(name);
    return "([^/]+)";
  });
  return { pattern: new RegExp(`^${source}$`), names };
}

/** A JSON route: answers with the operation's `200` body or with a problem document. */
function json<P extends keyof paths & string, M extends Method>(
  path: P,
  method: M,
  respond: (call: Call, state: MockState) => OkBody<P, M> | Schemas["Problem"],
): Route {
  return {
    method,
    ...compile(path),
    respond: (call, state) => {
      const body = respond(call, state);
      return isProblem(body) ? jsonResponse(body, body.status) : jsonResponse(body);
    },
  };
}

/** A route that answers with an event stream (or a problem document). */
function stream<P extends keyof paths & string>(
  path: P,
  method: Method,
  respond: (call: Call, state: MockState) => Response,
): Route {
  return { method, ...compile(path), respond };
}

/** An event stream delivered one event per chunk. `cutAfter` closes it early, without `done`. */
function eventStream(events: readonly AgentEvent[], delayMs: number, cutAfter?: number): Response {
  const encoder = new TextEncoder();
  const sent = cutAfter === undefined ? events : events.slice(0, cutAfter);
  let at = 0;
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      const event = sent[at];
      if (event === undefined) {
        controller.close();
        return;
      }
      if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
      controller.enqueue(encoder.encode(serialise([event])));
      at += 1;
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

function deliveryStatus(state: MockState): DeliveryStatus {
  if (state.stage !== "approved") return "not_started";
  if (state.deliveryReads <= 1) return "not_started";
  return state.deliveryReads === 2 ? "delivering" : "delivered";
}

/** The audit trail once a human decided: the pending trail, then the decision with its note. */
function decidedAudit(state: MockState, approved: boolean): Schemas["AuditEntry"][] {
  return [
    ...pendingQuote().audit,
    {
      at: DECIDED_AT,
      actor: "human",
      action: { code: approved ? "audit.approved" : "audit.rejected", params: {} },
      note: state.decisionNote,
    },
  ];
}

function currentQuote(state: MockState): Schemas["QuoteView"] | null {
  switch (state.stage) {
    case "none":
      return null;
    case "draft":
      return quoteView();
    case "pending":
      return pendingQuote();
    case "approved": {
      const status = deliveryStatus(state);
      return {
        ...pendingQuote(),
        status: status === "delivered" ? "submitted" : "approved",
        submission: submission(status, true, state.decisionNote),
        audit: decidedAudit(state, true),
      };
    }
    case "rejected":
      return {
        ...pendingQuote(),
        status: "rejected",
        submission: { ...submission("not_started", true, state.decisionNote) },
        audit: decidedAudit(state, false),
      };
  }
}

function currentApproval(state: MockState): Schemas["ApprovalView"] | null {
  switch (state.stage) {
    case "none":
    case "draft":
      return null;
    case "pending":
      return approvalView("pending");
    case "approved":
      return approvalView("approved", deliveryStatus(state));
    case "rejected":
      return approvalView("rejected");
  }
}

/** What each happy-path turn leaves behind: a draft after pricing, a pending approval at the end. */
const STAGE_AFTER_TURN: readonly Stage[] = ["none", "draft", "draft", "pending"];

function chat(call: Call, state: MockState): Response {
  const body = call.body as Partial<Schemas["ChatRequest"]> | null;
  const locale: Locale = body?.locale === "pt-BR" ? "pt-BR" : "en";
  state.locale = locale;
  switch (state.scenario) {
    case "exhausted":
      return jsonResponse(problem("allowance_exhausted", 429, true), 429);
    case "ceiling":
      return jsonResponse(problem("spend_ceiling_reached", 429, true), 429);
    case "flagged":
      return eventStream(flaggedEvents(), state.chunkDelayMs);
    case "error":
      return eventStream(errorEvents(), state.chunkDelayMs);
    case "cut": {
      const events = happyPath(locale).turns[0] ?? [];
      state.turns = 1;
      return eventStream(events, state.chunkDelayMs, Math.ceil(events.length / 2));
    }
    case "happy": {
      const { turns } = happyPath(locale);
      const at = state.turns % turns.length;
      if (at === 0) {
        state.stage = "none";
        state.decisionNote = null;
        state.deliveryReads = 0;
      }
      state.turns = at + 1;
      state.stage = STAGE_AFTER_TURN[at] ?? state.stage;
      return eventStream(turns[at] ?? [], state.chunkDelayMs);
    }
  }
}

const NOT_FOUND = () => problem("not_found", 404);

export const ROUTES: readonly Route[] = [
  json("/api/v1/regions", "get", () => REGIONS),
  json("/api/v1/regions/{id}/cells", "get", ({ params, query }) => {
    const region = REGIONS.find((candidate) => candidate.region_id === params.id);
    if (region === undefined) return NOT_FOUND();
    const season = query.get("season");
    return cellGrid(region, {
      metric: query.get("metric") === "season_anomaly" ? "season_anomaly" : "trigger_frequency",
      season: season === null ? null : Number(season),
    });
  }),
  json("/api/v1/weather/seasons", "get", ({ query }) => {
    const limit = query.get("limit_cents");
    return seasonSeries(
      {
        index_type:
          query.get("index_type") === "dry_spell_above" ? "dry_spell_above" : "rainfall_below",
        window: { start: query.get("window_start") ?? "", end: query.get("window_end") ?? "" },
        trigger: Number(query.get("trigger")),
        exit: Number(query.get("exit")),
      },
      limit === null ? null : Number(limit),
    );
  }),
  json("/api/v1/quotes", "get", (_call, state) => {
    const quote = currentQuote(state);
    return quote === null ? [] : [quoteSummary(quote)];
  }),
  json("/api/v1/quotes/{id}", "get", ({ params }, state) => {
    const quote = currentQuote(state);
    return quote === null || params.id !== QUOTE_ID ? NOT_FOUND() : quote;
  }),
  json("/api/v1/approvals", "get", ({ query }, state) => {
    if (state.stage === "approved") state.deliveryReads += 1;
    const approval = currentApproval(state);
    const wanted = query.get("status");
    if (approval === null || (wanted !== null && wanted !== approval.status)) return [];
    return [approval];
  }),
  json("/api/v1/approvals/{id}/decision", "post", ({ params, body }, state) => {
    if (params.id !== SUBMISSION_ID || state.stage === "none" || state.stage === "draft") {
      return NOT_FOUND();
    }
    if (state.stage !== "pending") return problem("invalid_state", 409);
    const decision = body as Partial<Schemas["Decision"]> | null;
    state.stage = decision?.approve === true ? "approved" : "rejected";
    state.decisionNote = typeof decision?.note === "string" ? decision.note : null;
    state.deliveryReads = 0;
    return currentApproval(state) ?? NOT_FOUND();
  }),
  json("/api/v1/approvals/{id}/redeliver", "post", ({ params }, state) => {
    if (params.id !== SUBMISSION_ID || state.stage !== "approved") return NOT_FOUND();
    state.deliveryReads = 1;
    return currentApproval(state) ?? NOT_FOUND();
  }),
  json("/api/v1/allowance", "get", (_call, state) =>
    state.scenario === "exhausted"
      ? { ...ALLOWANCE, conversations_left: 0, messages_left: 0 }
      : ALLOWANCE,
  ),
  json("/api/v1/workspace/api-keys", "post", () => API_KEY),
  json("/api/v1/conversations/{id}", "get", ({ params }, state) =>
    params.id === CONVERSATION_ID && state.turns > 0
      ? conversationView(state.locale, state.turns)
      : NOT_FOUND(),
  ),
  stream("/api/v1/chat", "post", chat),
  stream("/api/v1/replays/{locale}", "get", ({ params }, state) =>
    eventStream(replayEvents(params.locale === "pt-BR" ? "pt-BR" : "en"), state.chunkDelayMs),
  ),
];

/** Answers one request from the state, or with `not_found` when no route matches. */
export async function handle(request: Request, state: MockState): Promise<Response> {
  const url = new URL(request.url);
  const method = request.method.toLowerCase();
  for (const route of ROUTES) {
    if (route.method !== method) continue;
    const match = route.pattern.exec(url.pathname);
    if (match === null) continue;
    const params: Record<string, string> = {};
    route.names.forEach((name, at) => {
      params[name] = decodeURIComponent(match[at + 1] ?? "");
    });
    let body: unknown = null;
    if (method === "post") {
      const text = await request.text();
      try {
        body = text === "" ? null : (JSON.parse(text) as unknown);
      } catch {
        return jsonResponse(problem("invalid_arguments", 422), 422);
      }
    }
    return route.respond({ params, query: url.searchParams, body }, state);
  }
  return jsonResponse(NOT_FOUND(), 404);
}
