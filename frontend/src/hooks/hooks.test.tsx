import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientProvider, createApiClient } from "../api/client";
import { ApiProblem } from "../api/problems";
import { serialiseEvent, type AgentEvent } from "../api/sse";
import { createMockState, handle, type MockState } from "../mocks/handlers";
import type { Scenario } from "../mocks/scenarios";
import { CONVERSATION_ID, INDEX, QUOTE_ID, SUBMISSION_ID, problem } from "../test/fixtures/bodies";
import { happyPath } from "../test/fixtures/streams";
import {
  ALLOWANCE_CODE_STORAGE_KEY,
  CONVERSATION_STORAGE_KEY,
  storedConversationId,
} from "./storage";
import { useAllowance } from "./useAllowance";
import { DELIVERY_POLL_MS, deliveryInProgress, useApprovals } from "./useApprovals";
import { useCells } from "./useCells";
import { useChat } from "./useChat";
import { useDecision } from "./useDecision";
import { useQuotes } from "./useQuotes";
import { useRegions } from "./useRegions";
import { useReplay } from "./useReplay";

const BASE_URL = "http://veranico.test";
const HEADER = "Veranico-Allowance-Code";

type Transport = (request: Request) => Promise<Response>;

interface Harness {
  /** `METHOD /path` of every request, in order. */
  calls: string[];
  /** The requests themselves, for their headers and bodies. */
  requests: Request[];
  wrapper: (props: { children: ReactNode }) => ReactNode;
  queryClient: QueryClient;
}

function harness(transport: Transport): Harness {
  const calls: string[] = [];
  const requests: Request[] = [];
  const client = createApiClient({
    baseUrl: BASE_URL,
    fetch: (request) => {
      const url = new URL(request.url);
      calls.push(`${request.method} ${url.pathname}`);
      requests.push(request.clone());
      return transport(request);
    },
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ApiClientProvider client={client}>{children}</ApiClientProvider>
    </QueryClientProvider>
  );
  return { calls, requests, wrapper, queryClient };
}

function mockApi(scenario: Scenario = "happy"): Harness & { state: MockState } {
  const state = createMockState(scenario);
  return { ...harness((request) => handle(request, state)), state };
}

function count(calls: readonly string[], call: string): number {
  return calls.filter((candidate) => candidate === call).length;
}

function eventStream(events: readonly AgentEvent[]): Response {
  return new Response(events.map(serialiseEvent).join(""), {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
});

describe("useChat [R-12-1] [R-12.4-2] [R-16.7-1]", () => {
  it("streams a turn into the session and stores the conversation identifier", async () => {
    const api = mockApi();
    const { result } = renderHook(() => useChat("en"), { wrapper: api.wrapper });

    await act(() => result.current.send("Coffee farm near Três Pontas."));

    expect(result.current.session.step).toBe(3);
    expect(result.current.session.streaming).toBe(false);
    expect(result.current.session.conversationId).toBe(CONVERSATION_ID);
    expect(storedConversationId()).toBe(CONVERSATION_ID);

    await act(() => result.current.send("Yes, price it."));

    expect(result.current.session.step).toBe(4);
    const second = api.requests.filter((request) => request.method === "POST")[1];
    expect(await second?.json()).toEqual({
      conversation_id: CONVERSATION_ID,
      message: "Yes, price it.",
      locale: "en",
      map_point: null,
    });
  });

  it("chat_is_not_retried", async () => {
    const refused = harness(() =>
      Promise.resolve(Response.json(problem("model_unavailable", 503), { status: 503 })),
    );
    const first = renderHook(() => useChat("en"), { wrapper: refused.wrapper });

    await act(() => first.result.current.send("hello"));

    expect(count(refused.calls, "POST /api/v1/chat")).toBe(1);
    expect(first.result.current.session.problem?.code).toBe("model_unavailable");
    expect(first.result.current.session.rejectedText).toBe("hello");

    const offline = harness(() => Promise.reject(new TypeError("Failed to fetch")));
    const second = renderHook(() => useChat("en"), { wrapper: offline.wrapper });

    await act(() => second.result.current.send("hello"));

    expect(count(offline.calls, "POST /api/v1/chat")).toBe(1);
    expect(second.result.current.session.problem?.code).toBe("network");
    expect(second.result.current.session.streaming).toBe(false);
  });

  it("allowance_code_from_the_url_is_sent_as_a_header_on_chat_and_allowance_only [R-10.3-2]", async () => {
    window.history.replaceState({}, "", "/?code=friend-code");
    const api = mockApi();
    const { result } = renderHook(
      () => ({ chat: useChat("en"), allowance: useAllowance(), regions: useRegions() }),
      { wrapper: api.wrapper },
    );

    await act(() => result.current.chat.send("hello"));
    await waitFor(() => {
      expect(result.current.regions.isSuccess).toBe(true);
      expect(result.current.allowance.isSuccess).toBe(true);
    });

    const withHeader = new Set<string>();
    const withoutHeader = new Set<string>();
    for (const request of api.requests) {
      const path = new URL(request.url).pathname;
      if (request.headers.get(HEADER) === "friend-code") withHeader.add(path);
      else withoutHeader.add(path);
    }
    expect([...withHeader].sort()).toEqual(["/api/v1/allowance", "/api/v1/chat"]);
    expect([...withoutHeader]).toEqual(["/api/v1/regions"]);
    // Kept for the session only, and never in the address of a request.
    expect(window.sessionStorage.getItem(ALLOWANCE_CODE_STORAGE_KEY)).toBe("friend-code");
    expect(window.localStorage.getItem(ALLOWANCE_CODE_STORAGE_KEY)).toBeNull();
    expect(api.requests.every((request) => !request.url.includes("friend-code"))).toBe(true);
  });

  it("no_code_sends_no_header [R-10.3-2]", async () => {
    const api = mockApi();
    const { result } = renderHook(() => ({ chat: useChat("en"), allowance: useAllowance() }), {
      wrapper: api.wrapper,
    });

    await act(() => result.current.chat.send("hello"));
    await waitFor(() => {
      expect(result.current.allowance.isSuccess).toBe(true);
    });

    expect(api.requests.length).toBeGreaterThan(1);
    expect(api.requests.every((request) => !request.headers.has(HEADER))).toBe(true);
  });

  it("problem_with_replay_available_sets_the_offer [R-10.3-6]", async () => {
    for (const scenario of ["exhausted", "ceiling"] as const) {
      const api = mockApi(scenario);
      const { result, unmount } = renderHook(() => useChat("en"), { wrapper: api.wrapper });

      await act(() => result.current.send("hello"));

      expect(result.current.session.replayOffered).toBe(true);
      expect(result.current.session.problem?.code).toBe(
        scenario === "exhausted" ? "allowance_exhausted" : "spend_ceiling_reached",
      );
      expect(result.current.session.problem?.traceId).toBe(problem("x", 429).trace_id);
      expect(result.current.session.streaming).toBe(false);
      expect(result.current.session.messages).toEqual([]);
      expect(count(api.calls, "POST /api/v1/chat")).toBe(1);
      unmount();
    }

    // Another refusal carries no offer.
    const other = harness(() =>
      Promise.resolve(Response.json(problem("rate_limited", 429), { status: 429 })),
    );
    const { result } = renderHook(() => useChat("en"), { wrapper: other.wrapper });
    await act(() => result.current.send("hello"));
    expect(result.current.session.replayOffered).toBe(false);
  });

  it("shutting_down_error_unlocks_the_composer_without_resending", async () => {
    const api = harness(() =>
      Promise.resolve(
        eventStream([
          { type: "started", data: { conversation_id: CONVERSATION_ID, message_id: "m-0002" } },
          { type: "text_delta", data: { text: "Loading" } },
          { type: "error", data: { code: "shutting_down", completed: [] } },
          {
            type: "done",
            data: {
              conversation_id: CONVERSATION_ID,
              message_id: "m-0002",
              stop_reason: "error",
              prompt_version: "1",
            },
          },
        ]),
      ),
    );
    const { result } = renderHook(() => useChat("en"), { wrapper: api.wrapper });

    await act(() => result.current.send("hello"));

    expect(result.current.session.error?.code).toBe("shutting_down");
    expect(result.current.session.streaming).toBe(false);
    expect(result.current.session.interrupted).toBe(false);
    expect(count(api.calls, "POST /api/v1/chat")).toBe(1);
    expect(count(api.calls, `GET /api/v1/conversations/${CONVERSATION_ID}`)).toBe(0);
  });

  it("cut_stream_after_started_reloads_the_conversation_once", async () => {
    const api = mockApi("cut");
    const { result } = renderHook(() => useChat("en"), { wrapper: api.wrapper });

    await act(() => result.current.send("hello"));

    expect(count(api.calls, "POST /api/v1/chat")).toBe(1);
    expect(count(api.calls, `GET /api/v1/conversations/${CONVERSATION_ID}`)).toBe(1);
    expect(result.current.session.interrupted).toBe(true);
    expect(result.current.session.streaming).toBe(false);
    // The stored turn replaces what was streamed.
    expect(result.current.session.messages.map((message) => message.id)).toEqual([
      "m-0001",
      "m-0002",
    ]);
  });

  it("a stream cut before started reloads nothing", async () => {
    const api = harness(() => Promise.resolve(eventStream([])));
    const { result } = renderHook(() => useChat("en"), { wrapper: api.wrapper });

    await act(() => result.current.send("hello"));

    expect(api.calls).toEqual(["POST /api/v1/chat"]);
    expect(result.current.session.interrupted).toBe(true);
    expect(result.current.session.streaming).toBe(false);
  });

  it("restores the stored conversation on mount and forgets an unknown one", async () => {
    const api = mockApi();
    api.state.turns = 4;
    window.localStorage.setItem(CONVERSATION_STORAGE_KEY, CONVERSATION_ID);
    const known = renderHook(() => useChat("en"), { wrapper: api.wrapper });

    await waitFor(() => {
      expect(known.result.current.session.step).toBe(6);
    });
    expect(known.result.current.session.pendingApproval).toEqual({
      approval_id: SUBMISSION_ID,
      quote_id: QUOTE_ID,
    });
    known.unmount();

    window.localStorage.setItem(CONVERSATION_STORAGE_KEY, "cv-expired");
    const unknown = renderHook(() => useChat("en"), { wrapper: api.wrapper });

    await waitFor(() => {
      expect(storedConversationId()).toBeNull();
    });
    expect(unknown.result.current.session.messages).toEqual([]);
  });

  it("reset forgets the conversation and replay events never store one", async () => {
    const api = mockApi();
    const { result } = renderHook(() => useChat("en"), { wrapper: api.wrapper });
    await act(() => result.current.send("hello"));

    act(() => {
      result.current.reset();
    });

    expect(storedConversationId()).toBeNull();
    expect(result.current.session.messages).toEqual([]);

    const [turn] = happyPath("en").turns;
    act(() => {
      result.current.beginReplay();
      for (const event of turn ?? []) result.current.pushReplayEvent(event);
    });

    expect(result.current.session.mode).toBe("replay");
    expect(result.current.session.step).toBe(3);
    expect(result.current.session.conversationId).toBeNull();
    expect(storedConversationId()).toBeNull();
  });
});

describe("query hooks [R-12-1] [R-16.7-1]", () => {
  it("approvals_poll_only_while_a_delivery_is_in_progress", async () => {
    vi.useFakeTimers();
    const READ = "GET /api/v1/approvals";

    // A pending approval waits for a person: nothing to poll.
    const idle = mockApi();
    idle.state.stage = "pending";
    const waiting = renderHook(() => useApprovals(), { wrapper: idle.wrapper });
    await act(() => vi.advanceTimersByTimeAsync(DELIVERY_POLL_MS * 5));
    expect(waiting.result.current.data?.[0]?.status).toBe("pending");
    expect(count(idle.calls, READ)).toBe(1);
    waiting.unmount();

    // Approved: polled until the delivery reaches a final state, then no more.
    const busy = mockApi();
    busy.state.stage = "approved";
    const delivering = renderHook(() => useApprovals(), { wrapper: busy.wrapper });
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(delivering.result.current.data?.[0]?.delivery.status).toBe("not_started");
    // A little more than one interval, so the answer of the poll has been applied.
    await act(() => vi.advanceTimersByTimeAsync(DELIVERY_POLL_MS + 50));
    expect(delivering.result.current.data?.[0]?.delivery.status).toBe("delivering");
    await act(() => vi.advanceTimersByTimeAsync(DELIVERY_POLL_MS + 50));
    expect(delivering.result.current.data?.[0]?.delivery.status).toBe("delivered");
    expect(count(busy.calls, READ)).toBe(3);
    await act(() => vi.advanceTimersByTimeAsync(DELIVERY_POLL_MS * 5));
    expect(count(busy.calls, READ)).toBe(3);
  });

  it("delivery is in progress only for an approved submission that is not final", () => {
    const api = createMockState();
    api.stage = "approved";
    const of = (
      status: "pending" | "approved" | "rejected",
      delivery: "not_started" | "delivering" | "delivered" | "abandoned",
    ) =>
      deliveryInProgress({
        approval_id: SUBMISSION_ID,
        quote_id: QUOTE_ID,
        carrier_id: "carrier-1",
        carrier_name: "Carrier",
        location_label: "Somewhere",
        limit: { amount_cents: 1, currency: "BRL" },
        premium: { amount_cents: 1, currency: "BRL" },
        status,
        delivery: { status: delivery, attempts: 0, receipt_id: null, last_error_code: null },
        requested_at: "2026-11-10T14:07:30Z",
      });

    expect(of("approved", "not_started")).toBe(true);
    expect(of("approved", "delivering")).toBe(true);
    expect(of("approved", "delivered")).toBe(false);
    expect(of("approved", "abandoned")).toBe(false);
    expect(of("pending", "not_started")).toBe(false);
    expect(of("rejected", "not_started")).toBe(false);
  });

  it("cells_keep_previous_data_while_the_season_changes", async () => {
    const state = createMockState();
    let release: () => void = () => undefined;
    let hold = false;
    const api = harness(async (request) => {
      if (hold) {
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      }
      return handle(request, state);
    });
    const { result, rerender } = renderHook(
      ({ season }: { season: number | null }) =>
        useCells("sul-de-minas", { metric: "season_anomaly", index: INDEX, season }),
      { wrapper: api.wrapper, initialProps: { season: 1987 } },
    );
    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });
    const first = result.current.data;

    hold = true;
    rerender({ season: 1988 });
    await waitFor(() => {
      expect(api.calls).toHaveLength(2);
    });

    expect(result.current.data).toBe(first);
    expect(result.current.isPlaceholderData).toBe(true);

    await act(async () => {
      release();
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(result.current.isPlaceholderData).toBe(false);
    });
    expect(result.current.data).not.toEqual(first);
    expect(new URL(api.requests[1]?.url ?? BASE_URL).searchParams.get("season")).toBe("1988");
  });

  it("a problem document becomes an ApiProblem with its code and trace identifier", async () => {
    const api = harness(() =>
      Promise.resolve(Response.json(problem("weather_source_unavailable", 503), { status: 503 })),
    );
    const { result } = renderHook(() => useRegions(), { wrapper: api.wrapper });

    await waitFor(() => {
      expect(result.current.isError).toBe(true);
    });

    const error = result.current.error;
    expect(error).toBeInstanceOf(ApiProblem);
    expect(error).toMatchObject({
      code: "weather_source_unavailable",
      status: 503,
      traceId: problem("x", 503).trace_id,
      replayAvailable: false,
    });
  });

  it("a decision reloads the queue and the quotes", async () => {
    const api = mockApi();
    api.state.stage = "pending";
    const { result } = renderHook(
      () => ({ approvals: useApprovals(), quotes: useQuotes(), decision: useDecision() }),
      { wrapper: api.wrapper },
    );
    await waitFor(() => {
      expect(result.current.approvals.data?.[0]?.status).toBe("pending");
      expect(result.current.quotes.data?.[0]?.status).toBe("pending_approval");
    });

    await act(() =>
      result.current.decision.mutateAsync({
        approvalId: SUBMISSION_ID,
        decision: { approve: false, note: "Limit too high." },
      }),
    );

    await waitFor(() => {
      expect(result.current.approvals.data?.[0]?.status).toBe("rejected");
      expect(result.current.quotes.data?.[0]?.status).toBe("rejected");
    });
  });

  it("the replay is loaded only when asked for and holds every recorded turn", async () => {
    const api = mockApi();
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useReplay("pt-BR", enabled),
      { wrapper: api.wrapper, initialProps: { enabled: false } },
    );
    expect(api.calls).toEqual([]);

    rerender({ enabled: true });
    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(api.calls).toEqual(["GET /api/v1/replays/pt-BR"]);
    const events = result.current.data ?? [];
    expect(events.filter((event) => event.type === "user_message")).toHaveLength(4);
    expect(events.filter((event) => event.type === "done")).toHaveLength(4);
  });
});
