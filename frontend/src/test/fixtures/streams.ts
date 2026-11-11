import type { components } from "../../api/schema";
import { serialiseEvent, type AgentEvent } from "../../api/sse";
import type { Locale } from "../../i18n";
import { CONVERSATION_ID, POINT, POINT_LABEL } from "./bodies";
import { recordedIds, recording } from "./recording";

/**
 * The agent stream fixtures. The happy path is the recorded conversation of each language
 * (`recording.ts`, SPEC 9.6), event for event; the flagged and the error streams have no recording
 * and stay authored. `fixtures.test.ts` keeps the `.sse` files of this folder, their serialised
 * form in the wire format, in step with this module.
 */

type Schemas = components["schemas"];

/** The prompt version of the recordings; the authored streams claim the same one. */
export const PROMPT_VERSION = recording("en").header.prompt_version;

type Record_ = Record<string, unknown>;

/** Splits a text into the small pieces a model stream delivers. */
function deltas(text: string): AgentEvent[] {
  const words = text.split(" ");
  const events: AgentEvent[] = [];
  for (let at = 0; at < words.length; at += 4) {
    const piece = words.slice(at, at + 4).join(" ");
    events.push({
      type: "text_delta",
      data: { text: at + 4 < words.length ? `${piece} ` : piece },
    });
  }
  return events;
}

function tool(
  callId: string,
  name: string,
  args: Record_,
  durationMs: number,
  summary: Schemas["Coded"],
  result: Record_,
): AgentEvent[] {
  return [
    { type: "tool_started", data: { call_id: callId, tool: name, arguments: args } },
    {
      type: "tool_finished",
      data: {
        call_id: callId,
        tool: name,
        status: "ok",
        duration_ms: durationMs,
        summary,
        result,
        error: null,
      },
    },
  ];
}

function turn(
  messageId: string,
  body: AgentEvent[],
  stopReason: Schemas["Done"]["stop_reason"] = "end_turn",
): AgentEvent[] {
  return [
    { type: "started", data: { conversation_id: CONVERSATION_ID, message_id: messageId } },
    ...body,
    {
      type: "done",
      data: {
        conversation_id: CONVERSATION_ID,
        message_id: messageId,
        stop_reason: stopReason,
        prompt_version: PROMPT_VERSION,
      },
    },
  ];
}

const COPY = {
  flagged: (value: string) => `That is roughly ${value} a month over the season.`,
  interrupted: "I found the place and I am loading",
};

export interface HappyPath {
  /** One list of events per turn, each from `started` to `done`. */
  turns: AgentEvent[][];
  /** The request that opens each turn. */
  requests: string[];
}

/**
 * The full flow in four turns (backtest, price, term sheet, submission request), as recorded: the
 * recording's `user_message` events become the requests and the rest are the turns.
 */
export function happyPath(locale: Locale): HappyPath {
  const turns: AgentEvent[][] = [];
  const requests: string[] = [];
  for (const event of recording(locale).events) {
    if (event.type === "started") turns.push([]);
    if (event.type === "user_message") requests.push(event.data.text);
    else turns.at(-1)?.push(event);
  }
  return { turns, requests };
}

/** What `POST /chat` streams over the whole flow: the turns, one after another. */
export function chatEvents(locale: Locale): AgentEvent[] {
  return happyPath(locale).turns.flat();
}

/** What `GET /replays/{locale}` streams: the recording, each request after its turn's `started`. */
export function replayEvents(locale: Locale): AgentEvent[] {
  return [...recording(locale).events];
}

/** One stored message from the events of one turn, as `GET /conversations/{id}` returns it. */
function assistantMessage(
  events: readonly AgentEvent[],
  createdAt: string,
): Schemas["MessageView"] {
  const message: Schemas["MessageView"] = {
    message_id: "",
    role: "assistant",
    created_at: createdAt,
    text: "",
    tools: [],
    flagged: [],
  };
  for (const event of events) {
    if (event.type === "started") message.message_id = event.data.message_id;
    if (event.type === "text_delta") message.text += event.data.text;
    if (event.type === "tool_finished") message.tools.push(event.data);
    if (event.type === "grounding_flagged") message.flagged.push(...event.data.values);
  }
  return message;
}

/**
 * The stored conversation after the first `turnCount` turns of the happy path. User messages take
 * the identifier before their answer's (`m-0001` before `m-0002`).
 */
export function conversationView(locale: Locale, turnCount = 4): Schemas["ConversationView"] {
  const { turns, requests } = happyPath(locale);
  const messages: Schemas["MessageView"][] = [];
  turns.slice(0, turnCount).forEach((events, at) => {
    const minute = String(5 + at).padStart(2, "0");
    messages.push({
      message_id: `m-${String(at * 2 + 1).padStart(4, "0")}`,
      role: "user",
      created_at: `2026-11-10T14:${minute}:00Z`,
      text: requests[at] ?? "",
      tools: [],
      flagged: [],
    });
    messages.push(assistantMessage(events, `2026-11-10T14:${minute}:20Z`));
  });
  return { conversation_id: recordedIds(locale).conversationId, messages };
}

/** The figure the grounding check does not find in any tool output. */
export const FLAGGED_VALUE = "R$ 2,070.00";

/** One turn whose answer carries a figure the grounding check flags. */
export function flaggedEvents(): AgentEvent[] {
  return turn("m-0010", [
    ...deltas(COPY.flagged(FLAGGED_VALUE)),
    { type: "grounding_flagged", data: { message_id: "m-0010", values: [FLAGGED_VALUE] } },
  ]);
}

/** One turn in which the model fails after the first tool: `error`, then `done`. */
export function errorEvents(): AgentEvent[] {
  const [started, finished] = tool(
    "call-1",
    "resolve_location",
    { query: POINT_LABEL },
    412,
    {
      code: "tool.resolve_location",
      params: { label: POINT_LABEL, lat: POINT.lat, lon: POINT.lon },
    },
    { label: POINT_LABEL, lat: POINT.lat, lon: POINT.lon },
  );
  return turn(
    "m-0002",
    [
      ...(started === undefined || finished === undefined ? [] : [started, finished]),
      ...deltas(COPY.interrupted),
      { type: "error", data: { code: "model_unavailable", completed: ["resolve_location"] } },
    ],
    "error",
  );
}

export function serialise(events: readonly AgentEvent[]): string {
  return events.map(serialiseEvent).join("");
}

/** File name in this folder to its content. */
export const STREAM_FIXTURES: Readonly<Record<string, () => string>> = {
  "chat-happy-path.en.sse": () => serialise(chatEvents("en")),
  "chat-happy-path.pt-BR.sse": () => serialise(chatEvents("pt-BR")),
  "replay-happy-path.en.sse": () => serialise(replayEvents("en")),
  "replay-happy-path.pt-BR.sse": () => serialise(replayEvents("pt-BR")),
  "chat-flagged.sse": () => serialise(flaggedEvents()),
  "chat-error.sse": () => serialise(errorEvents()),
};
