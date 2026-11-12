import { describe, expect, it } from "vitest";

import type { AgentEvent } from "../api/sse";
import { lookup } from "../i18n";
import { CONVERSATION_ID, QUOTE_ID, SUBMISSION_ID } from "../test/fixtures/bodies";
import {
  FLAGGED_VALUE,
  chatEvents,
  conversationView,
  errorEvents,
  flaggedEvents,
  happyPath,
  replayEvents,
} from "../test/fixtures/streams";
import {
  finishedTools,
  initialSession,
  latestResult,
  sessionReducer,
  type SessionAction,
  type SessionState,
  type StopReason,
} from "./session";

function run(actions: readonly SessionAction[], from = initialSession("live")): SessionState {
  return actions.reduce(sessionReducer, from);
}

/** The happy path as the application sees it: each request, then the events of its answer. */
function liveHappyPath(): SessionAction[] {
  const { turns, requests } = happyPath("en");
  return turns.flatMap((events, at): SessionAction[] => [
    { type: "user_sent", text: requests[at] ?? "" },
    ...events,
  ]);
}

function started(messageId = "m-2"): AgentEvent {
  return { type: "started", data: { conversation_id: "cv-1", message_id: messageId } };
}

function done(stopReason: StopReason = "end_turn", messageId = "m-2"): AgentEvent {
  return {
    type: "done",
    data: {
      conversation_id: "cv-1",
      message_id: messageId,
      stop_reason: stopReason,
      prompt_version: "1",
    },
  };
}

function toolStarted(callId: string, tool: string): AgentEvent {
  return { type: "tool_started", data: { call_id: callId, tool, arguments: { query: "x" } } };
}

function toolOk(callId: string, tool: string): AgentEvent {
  return {
    type: "tool_finished",
    data: {
      call_id: callId,
      tool,
      status: "ok",
      duration_ms: 12,
      summary: { code: `tool.${tool}`, params: {} },
      result: { value: 1 },
      error: null,
    },
  };
}

describe("session reducer [R-12.4-2] [R-16.7-1]", () => {
  it("started_sets_the_conversation_identifier", () => {
    const state = run([{ type: "user_sent", text: "hello" }, started()]);

    expect(state.conversationId).toBe("cv-1");
    expect(state.streaming).toBe(true);
    expect(state.turnMessageId).toBe("m-2");
  });

  it("user_message_events_become_user_messages_in_replay_mode", () => {
    const replay = run(replayEvents("en"), initialSession("replay"));
    const { requests } = happyPath("en");

    expect(replay.messages.filter((message) => message.role === "user")).toHaveLength(4);
    expect(replay.messages.map((message) => message.role)).toEqual([
      "user",
      "assistant",
      "user",
      "assistant",
      "user",
      "assistant",
      "user",
      "assistant",
    ]);
    expect(replay.messages[0]?.text).toBe(requests[0]);
    expect(replay.step).toBe(6);
    // A recording creates nothing: no conversation of the visitor's and no approval to decide.
    expect(replay.conversationId).toBeNull();
    expect(replay.pendingApproval).toBeNull();

    const live = run([started(), { type: "user_message", data: { text: "recorded" } }]);
    expect(live.messages).toEqual([]);
  });

  it("happy_path_fixture_reaches_step_six_with_a_pending_approval", () => {
    const state = run(liveHappyPath());

    expect(state.step).toBe(6);
    expect(state.pendingApproval).toEqual({ approval_id: SUBMISSION_ID, quote_id: QUOTE_ID });
    expect(state.conversationId).toBe(CONVERSATION_ID);
    expect(state.streaming).toBe(false);
    expect(state.stopReason).toBe("end_turn");
    expect(finishedTools(state).map((row) => row.tool)).toEqual([
      "resolve_location",
      "get_weather_history",
      "backtest_index",
      "price_cover",
      "draft_term_sheet",
      "request_submission",
    ]);
    expect(latestResult(state, "price_cover")).toMatchObject({ quote_id: QUOTE_ID });
    expect(latestResult(state, "find_extreme_seasons")).toBeNull();
  });

  it("text_deltas_append_to_one_assistant_message", () => {
    const state = run([
      { type: "user_sent", text: "hello" },
      started(),
      { type: "text_delta", data: { text: "Over 74 " } },
      { type: "text_delta", data: { text: "seasons" } },
      done(),
    ]);

    expect(state.messages).toHaveLength(2);
    expect(state.messages[1]).toMatchObject({
      id: "m-2",
      role: "assistant",
      text: "Over 74 seasons",
    });
  });

  it("tool_started_then_finished_updates_one_row", () => {
    const running = run([started(), toolStarted("call-1", "resolve_location")]);

    expect(running.messages[0]?.tools).toEqual([
      expect.objectContaining({ callId: "call-1", status: "running", durationMs: null }),
    ]);
    expect(running.step).toBe(0);

    const finished = sessionReducer(running, toolOk("call-1", "resolve_location"));

    expect(finished.messages[0]?.tools).toEqual([
      {
        callId: "call-1",
        tool: "resolve_location",
        arguments: { query: "x" },
        status: "ok",
        durationMs: 12,
        summary: { code: "tool.resolve_location", params: {} },
        result: { value: 1 },
        error: null,
      },
    ]);
    expect(finished.step).toBe(1);
  });

  it("tool_error_row_keeps_its_error_code", () => {
    const state = run([
      started(),
      toolStarted("call-1", "resolve_location"),
      toolOk("call-1", "resolve_location"),
      toolStarted("call-2", "get_weather_history"),
      {
        type: "tool_finished",
        data: {
          call_id: "call-2",
          tool: "get_weather_history",
          status: "error",
          duration_ms: 30,
          summary: { code: "tool.error", params: { error_code: "weather_source_unavailable" } },
          result: null,
          error: {
            error_code: "weather_source_unavailable",
            message: "The weather source did not answer.",
            retryable: true,
          },
        },
      },
    ]);

    const row = state.messages[0]?.tools[1];
    expect(row?.status).toBe("error");
    expect(row?.error?.error_code).toBe("weather_source_unavailable");
    // A failed tool completes no step.
    expect(state.step).toBe(1);
  });

  it("grounding_flagged_marks_the_values_on_the_message", () => {
    const state = run([{ type: "user_sent", text: "per month?" }, ...flaggedEvents()]);

    const answer = state.messages[1];
    expect(answer?.flagged).toEqual([FLAGGED_VALUE]);
    expect(answer?.text).toContain(FLAGGED_VALUE);
    expect(state.streaming).toBe(false);
  });

  it("error_then_done_lists_completed_tools_and_unlocks_the_composer", () => {
    const state = run([{ type: "user_sent", text: "hello" }, ...errorEvents()]);

    expect(state.error).toEqual({ code: "model_unavailable", completed: ["resolve_location"] });
    expect(state.stopReason).toBe("error");
    expect(state.streaming).toBe(false);
    expect(state.step).toBe(1);
    // The partial answer stays on screen.
    expect(state.messages[1]?.text).not.toBe("");
  });

  it("stop_reasons_map_to_their_notes", () => {
    const reasons: StopReason[] = ["end_turn", "tool_limit", "budget", "error"];

    for (const reason of reasons) {
      const state = run([{ type: "user_sent", text: "hello" }, started(), done(reason)]);

      expect(state.stopReason).toBe(reason);
      expect(state.streaming).toBe(false);
      expect(lookup("en", `stop.${reason}`)).toBeTypeOf("string");
      expect(lookup("pt-BR", `stop.${reason}`)).toBeTypeOf("string");
    }
  });

  it("find_extreme_seasons_does_not_advance_progress", () => {
    const state = run([
      started(),
      toolStarted("call-1", "resolve_location"),
      toolOk("call-1", "resolve_location"),
      toolStarted("call-2", "find_extreme_seasons"),
      toolOk("call-2", "find_extreme_seasons"),
    ]);

    expect(state.step).toBe(1);
    expect(finishedTools(state)).toHaveLength(2);
  });

  it("restored_conversation_equals_the_streamed_one", () => {
    const streamed = run(liveHappyPath());
    const restored = run([{ type: "restored", conversation: conversationView("en") }]);

    // Stored messages keep results, not arguments, and user messages get their stored identifier.
    const comparable = (state: SessionState) =>
      state.messages.map((message) => ({
        ...message,
        id: message.role === "user" ? null : message.id,
        tools: message.tools.map((row) => ({ ...row, arguments: null })),
      }));
    expect(comparable(restored)).toEqual(comparable(streamed));
    expect(restored.step).toBe(streamed.step);
    expect(restored.pendingApproval).toEqual(streamed.pendingApproval);
    expect(restored.conversationId).toBe(streamed.conversationId);
    expect(restored.streaming).toBe(false);
  });
});

describe("session reducer: refusals, cuts and resets [R-10.3-6]", () => {
  it("a refused request leaves the list and goes back to the composer", () => {
    const state = run([
      { type: "user_sent", text: "Price it." },
      { type: "problem", code: "allowance_exhausted", traceId: "abc", replayAvailable: true },
    ]);

    expect(state.messages).toEqual([]);
    expect(state.rejectedText).toBe("Price it.");
    expect(state.problem).toEqual({ code: "allowance_exhausted", traceId: "abc" });
    expect(state.replayOffered).toBe(true);
    expect(state.streaming).toBe(false);
  });

  it("the next request clears the refusal", () => {
    const state = run([
      { type: "user_sent", text: "Price it." },
      { type: "problem", code: "rate_limited", traceId: null, replayAvailable: false },
      { type: "user_sent", text: "Price it." },
    ]);

    expect(state.problem).toBeNull();
    expect(state.rejectedText).toBeNull();
    expect(state.messages).toHaveLength(1);
  });

  it("a cut stream unlocks the composer and is marked interrupted", () => {
    const [first, second, third] = chatEvents("en");
    if (first === undefined || second === undefined || third === undefined) {
      throw new Error("the fixture is too short");
    }

    const state = run([
      { type: "user_sent", text: "hello" },
      first,
      second,
      third,
      { type: "stream_cut" },
    ]);

    expect(state.streaming).toBe(false);
    expect(state.interrupted).toBe(true);
    expect(state.stopReason).toBeNull();

    const reloaded = sessionReducer(state, {
      type: "restored",
      conversation: conversationView("en", 1),
      afterCut: true,
    });
    expect(reloaded.interrupted).toBe(true);
    expect(reloaded.messages).toHaveLength(2);
  });

  it("reset starts over in the mode asked for", () => {
    const state = run(liveHappyPath());

    expect(sessionReducer(state, { type: "reset" })).toEqual(initialSession("live"));
    expect(sessionReducer(state, { type: "reset", mode: "replay" })).toEqual(
      initialSession("replay"),
    );
  });
});
