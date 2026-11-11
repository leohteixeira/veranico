import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientProvider, createApiClient } from "../../api/client";
import type { AgentEvent } from "../../api/sse";
import { config } from "../../config";
import { I18nProvider, type Locale } from "../../i18n";
import { formatMoney } from "../../i18n/format";
import { createMockState, handle } from "../../mocks/handlers";
import type { Scenario } from "../../mocks/scenarios";
import {
  initialSession,
  sessionReducer,
  type SessionAction,
  type SessionMode,
  type SessionState,
} from "../../state/session";
import { ViewProvider, useView } from "../../state/view";
import {
  ALLOWANCE,
  POINT,
  POINT_LABEL,
  PREMIUM_CENTS,
  QUOTE_ID,
  problem,
} from "../../test/fixtures/bodies";
import {
  FLAGGED_VALUE,
  errorEvents,
  flaggedEvents,
  happyPath,
  replayEvents,
} from "../../test/fixtures/streams";
import { ConversationCard, type ConversationCardProps } from "./ConversationCard";
import { exampleRequests } from "./exampleRequests";
import { useConversationCard } from "./useConversationCard";

const BASE_URL = "http://veranico.test";
const EXAMPLES = exampleRequests(config.exampleCovers, "en");

/** Every space as a plain space, as Testing Library reads the text of the page. */
function plain(text: string): string {
  return text.replaceAll(" ", " ");
}

function reduce(actions: readonly SessionAction[], mode: SessionMode = "live"): SessionState {
  return actions.reduce(sessionReducer, initialSession(mode));
}

/** The live session after the first `turnCount` turns of the happy path. */
function liveSession(turnCount: number, locale: Locale = "en"): SessionState {
  const { turns, requests } = happyPath(locale);
  const actions: SessionAction[] = [];
  turns.slice(0, turnCount).forEach((events, at) => {
    actions.push({ type: "user_sent", text: requests[at] ?? "" }, ...events);
  });
  return reduce(actions);
}

function cardProps(overrides: Partial<ConversationCardProps> = {}): ConversationCardProps {
  return {
    session: initialSession("live"),
    allowance: ALLOWANCE,
    examples: EXAMPLES,
    replay: { status: "idle", play: vi.fn() },
    onSend: vi.fn(),
    onReset: vi.fn(),
    onOpen: vi.fn(),
    ...overrides,
  };
}

function renderCard(overrides: Partial<ConversationCardProps> = {}, locale: Locale = "en") {
  const props = cardProps(overrides);
  const view = render(
    <I18nProvider locale={locale}>
      <ConversationCard {...props} />
    </I18nProvider>,
  );
  const rerender = (next: Partial<ConversationCardProps>) => {
    view.rerender(
      <I18nProvider locale={locale}>
        <ConversationCard {...props} {...next} />
      </I18nProvider>,
    );
  };
  return { props, rerender };
}

type Transport = (request: Request) => Promise<Response>;

/** The card connected to the session, the allowance, the recording and the view store. */
function Connected({ reducedMotion }: { reducedMotion: boolean }) {
  const conversation = useConversationCard({ restore: false, reducedMotion });
  const { view } = useView();
  return (
    <>
      <ConversationCard {...conversation.card} />
      <output data-testid="view">{`${view.tab}:${view.highlight ?? ""}`}</output>
    </>
  );
}

function renderConnected(
  options: { scenario?: Scenario; transport?: Transport; reducedMotion?: boolean } = {},
) {
  const state = createMockState(options.scenario ?? "happy");
  const calls: string[] = [];
  const client = createApiClient({
    baseUrl: BASE_URL,
    fetch: (request) => {
      calls.push(`${request.method} ${new URL(request.url).pathname}`);
      return (options.transport ?? ((next) => handle(next, state)))(request);
    },
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ApiClientProvider client={client}>
        <I18nProvider locale="en">
          <ViewProvider>{children}</ViewProvider>
        </I18nProvider>
      </ApiClientProvider>
    </QueryClientProvider>
  );
  render(<Connected reducedMotion={options.reducedMotion ?? true} />, { wrapper });
  return { calls, state };
}

function userTexts(): string[] {
  return [...document.querySelectorAll(".msg--user .msg__text")].map(
    (element) => element.textContent ?? "",
  );
}

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("conversation card [R-12.1-3]", () => {
  it("first_run_shows_the_three_example_requests [R-12.4-1]", () => {
    renderCard();
    const list = screen.getByRole("log", { name: "Messages" });
    const examples = within(list).getAllByRole("button");
    expect(examples).toHaveLength(3);
    for (const example of EXAMPLES) {
      expect(within(list).getByRole("button", { name: new RegExp(example.title) })).toBeVisible();
    }
    expect(screen.getByRole("textbox", { name: "Message to the agent" })).toBeVisible();
  });

  it("example_click_sends_its_text [R-12.4-1]", () => {
    const { props } = renderCard();
    const first = EXAMPLES[0];
    if (first === undefined) throw new Error("no example");
    fireEvent.click(screen.getByRole("button", { name: new RegExp(first.title) }));
    expect(props.onSend).toHaveBeenCalledExactlyOnceWith(first.text, null);
  });

  it("progress_follows_finished_tools [R-12.1-3]", () => {
    const { rerender } = renderCard();
    const states = () =>
      within(screen.getByRole("list", { name: "Progress" }))
        .getAllByRole("listitem")
        .map((item) => item.getAttribute("data-state"));
    expect(states()).toEqual(["current", "todo", "todo", "todo", "todo", "todo"]);
    expect(screen.getByText("Step 1 of 6: Locate")).toBeVisible();

    // The first turn resolves the location, loads the history and backtests.
    rerender({ session: liveSession(1) });
    expect(states()).toEqual(["done", "done", "done", "current", "todo", "todo"]);
    expect(screen.getByText("Step 4 of 6: Price")).toBeVisible();

    rerender({ session: liveSession(4) });
    expect(states()).toEqual(["done", "done", "done", "done", "done", "done"]);
    expect(screen.getByText("All 6 steps done")).toBeVisible();
  });

  it("header shows the messages left, without a total", () => {
    renderCard();
    expect(screen.getByText("15 messages left today")).toBeVisible();
  });

  it("tool_row_shows_running_then_duration_and_summary [R-12.4-2]", () => {
    const [started, toolStarted, toolFinished] = happyPath("en").turns[0] ?? [];
    if (started === undefined || toolStarted === undefined || toolFinished === undefined) {
      throw new Error("the first turn has no tool");
    }
    const running = reduce([{ type: "user_sent", text: "Coffee farm" }, started, toolStarted]);
    const { rerender } = renderCard({ session: running });
    const row = () => {
      const item = document.querySelector('[data-tool="resolve_location"]');
      if (!(item instanceof HTMLElement)) throw new Error("no tool row");
      return item;
    };
    expect(row()).toHaveAttribute("data-status", "running");
    expect(within(row()).getByText("resolve_location")).toBeVisible();
    expect(within(row()).getByText("Resolve the location")).toBeVisible();
    expect(within(row()).getByText("running")).toBeVisible();
    expect(within(row()).queryByText(/ms$/)).toBeNull();

    rerender({ session: sessionReducer(running, toolFinished) });
    expect(row()).toHaveAttribute("data-status", "ok");
    expect(within(row()).getByText("412 ms")).toBeVisible();
    expect(within(row()).getByText(POINT_LABEL)).toBeVisible();
    expect(within(row()).queryByText("running")).toBeNull();
  });

  it("tool_row_expands_to_arguments [R-12.1-3]", () => {
    renderCard({ session: liveSession(1) });
    const toggle = screen.getByRole("button", { name: /resolve_location/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const panel = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(panel).not.toBeVisible();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(panel).toBeVisible();
    expect(panel).toHaveTextContent("Arguments");
    expect(panel).toHaveTextContent(`"query": "${POINT_LABEL}"`);

    fireEvent.click(toggle);
    expect(panel).not.toBeVisible();
  });

  it("tool_error_row_shows_the_translated_code [R-12.4-2]", () => {
    const session = reduce([
      { type: "user_sent", text: "Coffee farm" },
      { type: "started", data: { conversation_id: "cv-1", message_id: "m-0002" } },
      {
        type: "tool_started",
        data: { call_id: "call-1", tool: "get_weather_history", arguments: { lat: 1, lon: 2 } },
      },
      {
        type: "tool_finished",
        data: {
          call_id: "call-1",
          tool: "get_weather_history",
          status: "error",
          duration_ms: 3004,
          summary: { code: "tool.error", params: { error_code: "weather_source_unavailable" } },
          result: null,
          error: {
            error_code: "weather_source_unavailable",
            message: "upstream timed out",
            retryable: true,
          },
        },
      },
    ]);
    renderCard({ session });
    const row = document.querySelector('[data-tool="get_weather_history"]');
    expect(row).toHaveAttribute("data-status", "error");
    expect(row).toHaveTextContent(
      "Failed: The weather source did not answer. Try again in a moment.",
    );
    expect(row).toHaveTextContent("failed");
    // The API's English prose is never shown.
    expect(row).not.toHaveTextContent("upstream timed out");
    // A failed tool completes no step.
    expect(screen.getByText("Step 1 of 6: Locate")).toBeVisible();
  });

  it("tool_not_executed_row_says_the_call_was_not_run [R-12.4-2]", () => {
    const session = reduce([
      { type: "user_sent", text: "Coffee farm" },
      { type: "started", data: { conversation_id: "cv-1", message_id: "m-0002" } },
      {
        type: "tool_finished",
        data: {
          call_id: "call-9",
          tool: "price_cover",
          status: "error",
          duration_ms: 0,
          summary: { code: "tool.error", params: { error_code: "tool_not_executed" } },
          result: null,
          error: { error_code: "tool_not_executed", message: "not executed", retryable: false },
        },
      },
    ]);
    renderCard({ session });
    const row = document.querySelector('[data-tool="price_cover"]');
    expect(row).toHaveTextContent(
      "This call was not run: the agent had used its calls or attempts for this request.",
    );
    expect(row).toHaveTextContent("not run");
    expect(row).not.toHaveTextContent("Failed");
    expect(row).not.toHaveTextContent("0 ms");
  });

  it("figure_links_to_its_tab_and_field [R-12.3-5]", () => {
    const { props } = renderCard({ session: liveSession(2) });
    const premium = plain(formatMoney(PREMIUM_CENTS, "en"));
    fireEvent.click(
      screen.getByRole("button", {
        name: (name) => plain(name) === `${premium}: show its source in the Quote tab`,
      }),
    );
    expect(props.onOpen).toHaveBeenLastCalledWith("quote", "premium");

    fireEvent.click(
      screen.getByRole("button", { name: "8.28%: show its source in the Quote tab" }),
    );
    expect(props.onOpen).toHaveBeenLastCalledWith("quote", "rate_on_line");

    // The backtest answer of the first turn points at the History tab.
    const history = screen.getAllByRole("button", { name: /show its source in the History tab/ });
    expect(history.length).toBeGreaterThan(0);
    const burnCost = history.find((button) => button.getAttribute("data-key") === "burn_cost");
    if (burnCost === undefined) throw new Error("the burn cost is not linked");
    fireEvent.click(burnCost);
    expect(props.onOpen).toHaveBeenLastCalledWith("history", "burn_cost");
  });

  it("flagged_figure_is_marked_with_the_note [R-12.3-5] [R-12.4-3] [R-9.5-2]", () => {
    const session = reduce([{ type: "user_sent", text: "And per month?" }, ...flaggedEvents()]);
    renderCard({ session });
    const marked = screen.getByText(plain(FLAGGED_VALUE));
    expect(marked.tagName).toBe("MARK");
    expect(marked).toHaveAttribute("data-flagged", "true");
    expect(marked).toHaveTextContent("not found in any tool output");
    expect(screen.queryByRole("button", { name: new RegExp("2,070") })).toBeNull();
    expect(
      screen.getByText(
        "1 figure in this answer was not found in any tool output. Treat it as unverified.",
      ),
    ).toBeVisible();
  });

  it("composer_is_locked_only_while_streaming [R-12.4-2]", () => {
    const [started] = happyPath("en").turns[0] ?? [];
    if (started === undefined) throw new Error("no turn");
    const streaming = reduce([{ type: "user_sent", text: "Coffee farm" }, started]);
    const { props, rerender } = renderCard({ session: streaming });
    const input = () => screen.getByRole("textbox", { name: "Message to the agent" });
    const send = () => screen.getByRole("button", { name: "Send" });
    expect(input()).toHaveAttribute("readonly");
    expect(send()).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("The agent is working");

    rerender({ session: liveSession(1) });
    expect(input()).not.toHaveAttribute("readonly");
    // Nothing to send yet.
    expect(send()).toBeDisabled();
    fireEvent.change(input(), { target: { value: "Yes, price it." } });
    expect(send()).toBeEnabled();
    fireEvent.keyDown(input(), { key: "Enter", shiftKey: true });
    expect(props.onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(props.onSend).toHaveBeenCalledExactlyOnceWith("Yes, price it.", null);
    expect(input()).toHaveValue("");
  });

  it("message_too_long_is_shown_inline [R-12.1-3]", async () => {
    const state = createMockState("happy");
    const { calls } = renderConnected({
      transport: (request) =>
        request.method === "POST" && new URL(request.url).pathname === "/api/v1/chat"
          ? Promise.resolve(
              new Response(JSON.stringify(problem("message_too_long", 422)), {
                status: 422,
                headers: { "content-type": "application/problem+json" },
              }),
            )
          : handle(request, state),
    });
    const input = screen.getByRole("textbox", { name: "Message to the agent" });
    fireEvent.change(input, { target: { value: "A very long request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The message is too long. Shorten it and send again.");
    // The refused text is back in the composer, which stays in place.
    expect(screen.getByRole("textbox", { name: "Message to the agent" })).toHaveValue(
      "A very long request",
    );
    expect(userTexts()).toEqual([]);
    expect(calls.filter((call) => call === "POST /api/v1/chat")).toHaveLength(1);
  });

  it("allowance_reached_replaces_the_composer_with_the_replay_offer [R-12.4-4]", async () => {
    renderConnected({ scenario: "exhausted" });
    expect(await screen.findByText("0 messages left today")).toBeVisible();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(
      screen.getByText(/Today's allowance for the live agent is used\. You can still watch/),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Play the recorded conversation" })).toBeEnabled();
  });

  it("ceiling_reached_offers_the_replay_with_its_reason [R-12.4-4]", () => {
    const session = reduce([
      { type: "user_sent", text: "Coffee farm" },
      { type: "problem", code: "spend_ceiling_reached", traceId: null, replayAvailable: true },
    ]);
    renderCard({ session });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(
      screen.getByText(/The demo reached its spend ceiling for the live agent\./),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Play the recorded conversation" })).toBeVisible();
  });

  it("replay_plays_recorded_turns_with_the_recording_banner [R-12.4-5] [R-9.6-2]", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { calls } = renderConnected({ scenario: "exhausted", reducedMotion: false });
    const { requests } = happyPath("en");
    fireEvent.click(await screen.findByRole("button", { name: "Play the recorded conversation" }));

    // The recording is paced in the browser: soon after the start only the first request is shown.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(document.querySelector(".replay-banner")).toHaveAttribute("role", "status");
    expect(screen.getByText(/^Recording\. This conversation was recorded earlier/)).toBeVisible();
    expect(userTexts()).toEqual([requests[0]]);
    expect(screen.queryByRole("textbox")).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(userTexts()).toEqual(requests);
    expect(screen.getByText(/The recording has ended\./)).toBeVisible();
    expect(screen.getByRole("button", { name: "Play it again" })).toBeVisible();
    // A recording creates nothing and decides nothing: no approval note, no chat request.
    expect(document.querySelector('[data-note="approval"]')).toBeNull();
    expect(calls).not.toContain("POST /api/v1/chat");
    expect(calls.filter((call) => call === "GET /api/v1/replays/en")).toHaveLength(1);
  });

  it("replay_user_messages_come_from_user_message_events [R-9.6-2]", () => {
    const events: AgentEvent[] = replayEvents("pt-BR");
    renderCard(
      { session: reduce(events, "replay"), replay: { status: "ended", play: vi.fn() } },
      "pt-BR",
    );
    expect(userTexts()).toEqual(happyPath("pt-BR").requests);
    expect(screen.getByText(/^Gravação\. Esta conversa foi gravada antes/)).toBeVisible();
  });

  it("replay_respects_reduced_motion [R-12.4-5]", async () => {
    renderConnected({ scenario: "exhausted", reducedMotion: true });
    fireEvent.click(await screen.findByRole("button", { name: "Play the recorded conversation" }));
    // No pacing: the whole recording is shown at once, with no timer to wait for.
    await waitFor(() => {
      expect(userTexts()).toEqual(happyPath("en").requests);
    });
    expect(screen.getByText(/The recording has ended\./)).toBeVisible();
  });

  it("quote_id_is_a_link_to_the_quote_tab [R-12.3-5]", async () => {
    renderConnected({ scenario: "exhausted", reducedMotion: true });
    fireEvent.click(await screen.findByRole("button", { name: "Play the recorded conversation" }));
    const links = await screen.findAllByRole("button", {
      name: `${QUOTE_ID}: show its source in the Quote tab`,
    });
    expect(screen.getByTestId("view")).toHaveTextContent("risk:");
    const first = links[0];
    if (first === undefined) throw new Error("the quote identifier is not linked");
    fireEvent.click(first);
    expect(screen.getByTestId("view")).toHaveTextContent("quote:quote_id");
  });

  it("interrupted_turn_shows_what_completed [R-12.1-3]", () => {
    const session = reduce([{ type: "user_sent", text: "Coffee farm" }, ...errorEvents()]);
    const { rerender } = renderCard({ session });
    const note = () => document.querySelector('[data-note="interrupted"]');
    expect(note()).toHaveTextContent(
      "The agent is unavailable right now. Try again in a moment. Completed before the interruption: Resolve the location.",
    );
    // What had streamed stays on the screen, and the composer is free again.
    expect(screen.getByText("I found the place and I am loading")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Message to the agent" })).not.toHaveAttribute(
      "readonly",
    );

    // A stream that closes without `done`: the same note, from the tools that finished.
    const turn = happyPath("en").turns[0] ?? [];
    const cut = reduce([
      { type: "user_sent", text: "Coffee farm" },
      ...turn.slice(0, 5),
      { type: "stream_cut" },
    ]);
    rerender({ session: cut });
    expect(note()).toHaveTextContent(
      "The connection closed before the answer finished. Completed before the interruption: Resolve the location, Load the weather history.",
    );
  });

  it("map_click_prefills_a_request_with_the_point [R-12.1-3]", () => {
    const onClearMapPoint = vi.fn();
    const { props, rerender } = renderCard({ onClearMapPoint });
    const input = () => screen.getByRole("textbox", { name: "Message to the agent" });
    expect(input()).toHaveValue("");

    rerender({ mapPoint: POINT });
    expect(input()).toHaveValue(
      `Price a cover for the point I marked on the map (${POINT.lat}, ${POINT.lon}).`,
    );
    expect(screen.getByText(`Point from the map: ${POINT.lat}, ${POINT.lon}`)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(props.onSend).toHaveBeenCalledExactlyOnceWith(
      `Price a cover for the point I marked on the map (${POINT.lat}, ${POINT.lon}).`,
      POINT,
    );
    expect(onClearMapPoint).toHaveBeenCalledOnce();
  });

  it("start_over_is_offered_once_there_is_something_to_forget", () => {
    const { props, rerender } = renderCard();
    expect(screen.getByRole("button", { name: "Start over" })).toBeDisabled();
    rerender({ session: liveSession(1) });
    fireEvent.click(screen.getByRole("button", { name: "Start over" }));
    expect(props.onReset).toHaveBeenCalledOnce();
  });

  it("pending_approval_points_at_the_approvals_tab [R-12.1-3]", () => {
    const { props } = renderCard({ session: liveSession(4) });
    fireEvent.click(screen.getByRole("button", { name: "Open approvals" }));
    expect(props.onOpen).toHaveBeenLastCalledWith("approvals", null);
  });
});
