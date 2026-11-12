import type { components } from "../api/schema";
import type { AgentEvent } from "../api/sse";

type Schemas = components["schemas"];

export type StopReason = Schemas["Done"]["stop_reason"];

/** `live`: the agent answers. `replay`: a recording is played and nothing real is created. */
export type SessionMode = "live" | "replay";

export interface ToolRow {
  callId: string;
  tool: string;
  /** `null` for a restored conversation: stored messages keep results, not arguments. */
  arguments: Record<string, unknown> | null;
  status: "running" | "ok" | "error";
  durationMs: number | null;
  summary: Schemas["Coded"] | null;
  result: Record<string, unknown> | null;
  error: Schemas["ToolError"] | null;
}

export interface SessionMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  tools: ToolRow[];
  /** Figures of this answer that the grounding check found in no tool output. */
  flagged: string[];
}

export interface SessionProblem {
  code: string;
  traceId: string | null;
}

export interface SessionState {
  mode: SessionMode;
  conversationId: string | null;
  messages: SessionMessage[];
  /** A turn is in progress: the composer is locked. */
  streaming: boolean;
  /** The identifier `started` gave to the answer of the turn in progress. */
  turnMessageId: string | null;
  /** How many of the six steps are done (0 to 6). */
  step: number;
  /** The approval waiting for the visitor's decision. Never set by a replay. */
  pendingApproval: Schemas["ApprovalRequired"] | null;
  stopReason: StopReason | null;
  /** The `error` event of the last turn: its code and the tools that had completed. */
  error: Schemas["StreamError"] | null;
  /** The last stream closed without `done`. */
  interrupted: boolean;
  /** The last request was refused before any event. */
  problem: SessionProblem | null;
  /** The live agent is unavailable to this visitor and the recording can be played. */
  replayOffered: boolean;
  /** The text of a refused request, handed back to the composer. */
  rejectedText: string | null;
}

export type SessionAction =
  | AgentEvent
  | { type: "user_sent"; text: string }
  | { type: "stream_cut" }
  | { type: "problem"; code: string; traceId: string | null; replayAvailable: boolean }
  | { type: "restored"; conversation: Schemas["ConversationView"]; afterCut?: boolean }
  | { type: "reset"; mode?: SessionMode };

export function initialSession(mode: SessionMode = "live"): SessionState {
  return {
    mode,
    conversationId: null,
    messages: [],
    streaming: false,
    turnMessageId: null,
    step: 0,
    pendingApproval: null,
    stopReason: null,
    error: null,
    interrupted: false,
    problem: null,
    replayOffered: false,
    rejectedText: null,
  };
}

export const STEP_COUNT = 6;

/** The step a tool completes. `find_extreme_seasons` is a side question and completes none. */
const STEP_OF_TOOL: Readonly<Record<string, number>> = {
  resolve_location: 1,
  get_weather_history: 2,
  backtest_index: 3,
  price_cover: 4,
  draft_term_sheet: 5,
  request_submission: 6,
};

function stepAfter(step: number, row: ToolRow): number {
  if (row.status !== "ok") return step;
  return Math.max(step, STEP_OF_TOOL[row.tool] ?? 0);
}

function finishedRow(event: Schemas["ToolFinished"], args: ToolRow["arguments"]): ToolRow {
  return {
    callId: event.call_id,
    tool: event.tool,
    arguments: args,
    status: event.status,
    durationMs: event.duration_ms,
    summary: event.summary,
    result: event.result,
    error: event.error,
  };
}

function userMessage(id: string, text: string): SessionMessage {
  return { id, role: "user", text, tools: [], flagged: [] };
}

/** Updates the assistant message with this identifier, creating it on the first event. */
function withAssistant(
  messages: readonly SessionMessage[],
  messageId: string,
  update: (message: SessionMessage) => SessionMessage,
): SessionMessage[] {
  const index = messages.findIndex(
    (message) => message.role === "assistant" && message.id === messageId,
  );
  if (index >= 0) {
    return messages.map((message, at) => (at === index ? update(message) : message));
  }
  return [
    ...messages,
    update({ id: messageId, role: "assistant", text: "", tools: [], flagged: [] }),
  ];
}

function turnId(state: SessionState): string {
  return state.turnMessageId ?? `turn-${state.messages.length}`;
}

function stringField(record: Record<string, unknown> | null, name: string): string | null {
  const value = record?.[name];
  return typeof value === "string" ? value : null;
}

/** The approval a restored conversation is waiting on, read back from its stored tool results. */
function approvalFrom(messages: readonly SessionMessage[]): Schemas["ApprovalRequired"] | null {
  let quoteId: string | null = null;
  let approval: Schemas["ApprovalRequired"] | null = null;
  for (const message of messages) {
    for (const row of message.tools) {
      if (row.status !== "ok") continue;
      if (row.tool === "price_cover") quoteId = stringField(row.result, "quote_id") ?? quoteId;
      if (row.tool === "request_submission") {
        const submissionId = stringField(row.result, "submission_id");
        if (submissionId !== null && quoteId !== null) {
          approval = { approval_id: submissionId, quote_id: quoteId };
        }
      }
    }
  }
  return approval;
}

export function sessionReducer(state: SessionState, action: SessionAction): SessionState {
  switch (action.type) {
    case "user_sent":
      return {
        ...state,
        messages: [...state.messages, userMessage(`local-${state.messages.length}`, action.text)],
        streaming: true,
        turnMessageId: null,
        stopReason: null,
        error: null,
        interrupted: false,
        problem: null,
        replayOffered: false,
        rejectedText: null,
      };

    case "started":
      return {
        ...state,
        // A recording's conversation is not this visitor's: its identifier is never kept.
        conversationId: state.mode === "live" ? action.data.conversation_id : null,
        turnMessageId: action.data.message_id,
        streaming: true,
        stopReason: null,
        error: null,
        interrupted: false,
      };

    case "user_message":
      // Only a replay carries the recorded request; a chat stream never does.
      if (state.mode !== "replay") return state;
      return {
        ...state,
        messages: [
          ...state.messages,
          userMessage(`recorded-${state.messages.length}`, action.data.text),
        ],
      };

    case "text_delta":
      return {
        ...state,
        messages: withAssistant(state.messages, turnId(state), (message) => ({
          ...message,
          text: message.text + action.data.text,
        })),
      };

    case "tool_started":
      return {
        ...state,
        messages: withAssistant(state.messages, turnId(state), (message) => ({
          ...message,
          tools: [
            ...message.tools,
            {
              callId: action.data.call_id,
              tool: action.data.tool,
              arguments: action.data.arguments,
              status: "running",
              durationMs: null,
              summary: null,
              result: null,
              error: null,
            },
          ],
        })),
      };

    case "tool_finished": {
      const id = turnId(state);
      const running = state.messages
        .find((message) => message.role === "assistant" && message.id === id)
        ?.tools.find((row) => row.callId === action.data.call_id);
      const row = finishedRow(action.data, running?.arguments ?? null);
      return {
        ...state,
        messages: withAssistant(state.messages, id, (message) => ({
          ...message,
          tools:
            running === undefined
              ? [...message.tools, row]
              : message.tools.map((existing) => (existing === running ? row : existing)),
        })),
        step: stepAfter(state.step, row),
      };
    }

    case "approval_required":
      // A replay creates no approval and must not imply one.
      if (state.mode !== "live") return state;
      return { ...state, pendingApproval: action.data };

    case "grounding_flagged":
      return {
        ...state,
        messages: withAssistant(state.messages, action.data.message_id, (message) => ({
          ...message,
          flagged: [...new Set([...message.flagged, ...action.data.values])],
        })),
      };

    case "error":
      return { ...state, error: action.data };

    case "done":
      return {
        ...state,
        conversationId: state.mode === "live" ? action.data.conversation_id : null,
        streaming: false,
        turnMessageId: null,
        stopReason: action.data.stop_reason,
      };

    case "stream_cut":
      return { ...state, streaming: false, turnMessageId: null, interrupted: true };

    case "problem": {
      const last = state.messages[state.messages.length - 1];
      const optimistic = last !== undefined && last.role === "user" && last.id.startsWith("local-");
      return {
        ...state,
        // Nothing was stored: the request leaves the list and goes back to the composer.
        messages: optimistic ? state.messages.slice(0, -1) : state.messages,
        streaming: false,
        turnMessageId: null,
        problem: { code: action.code, traceId: action.traceId },
        replayOffered: action.replayAvailable,
        rejectedText: optimistic ? last.text : null,
      };
    }

    case "restored": {
      const messages: SessionMessage[] = action.conversation.messages.map((message) => ({
        id: message.message_id,
        role: message.role,
        text: message.text,
        tools: message.tools.map((tool) => finishedRow(tool, null)),
        flagged: [...message.flagged],
      }));
      let step = 0;
      for (const message of messages) {
        for (const row of message.tools) step = stepAfter(step, row);
      }
      const afterCut = action.afterCut === true;
      return {
        ...initialSession("live"),
        conversationId: action.conversation.conversation_id,
        messages,
        step,
        pendingApproval: approvalFrom(messages),
        // After a cut stream the stored conversation is shown, still marked as interrupted.
        interrupted: afterCut,
        error: afterCut ? state.error : null,
      };
    }

    case "reset":
      return initialSession(action.mode ?? "live");
  }
}

/** Every finished tool row of the conversation, oldest first. */
export function finishedTools(state: SessionState): ToolRow[] {
  return state.messages.flatMap((message) =>
    message.tools.filter((row) => row.status !== "running"),
  );
}

/** The most recent successful result of a tool, or `null`. */
export function latestResult(state: SessionState, tool: string): Record<string, unknown> | null {
  const rows = finishedTools(state).filter((row) => row.tool === tool && row.status === "ok");
  return rows[rows.length - 1]?.result ?? null;
}
