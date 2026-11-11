import type { components } from "./schema";

type Schemas = components["schemas"];

/** The nine events of the agent stream (contracts section 8), tagged by their wire name. */
export type AgentEvent =
  | { type: "started"; data: Schemas["Started"] }
  | { type: "user_message"; data: Schemas["UserMessage"] }
  | { type: "text_delta"; data: Schemas["TextDelta"] }
  | { type: "tool_started"; data: Schemas["ToolStarted"] }
  | { type: "tool_finished"; data: Schemas["ToolFinished"] }
  | { type: "approval_required"; data: Schemas["ApprovalRequired"] }
  | { type: "grounding_flagged"; data: Schemas["GroundingFlagged"] }
  | { type: "error"; data: Schemas["StreamError"] }
  | { type: "done"; data: Schemas["Done"] };

export type AgentEventName = AgentEvent["type"];

const EVENT_NAMES: ReadonlySet<string> = new Set<AgentEventName>([
  "started",
  "user_message",
  "text_delta",
  "tool_started",
  "tool_finished",
  "approval_required",
  "grounding_flagged",
  "error",
  "done",
]);

function isEventName(name: string): name is AgentEventName {
  return EVENT_NAMES.has(name);
}

/** One event in the wire format: `event: <name>\ndata: <json>\n\n`. */
export function serialiseEvent(event: AgentEvent): string {
  return `event: ${event.type}\ndata: ${JSON.stringify(event.data)}\n\n`;
}

/** `undefined`: nothing to deliver (a comment or an unknown event). `null`: the block is broken. */
function parseBlock(block: string): AgentEvent | null | undefined {
  let name = "";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") name = value;
    else if (field === "data") data.push(value);
  }
  if (name === "" && data.length === 0) return undefined;
  if (!isEventName(name)) return undefined;
  let parsed: unknown;
  try {
    parsed = JSON.parse(data.join("\n"));
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
  // The payload shape is the contract of the generated client; the wire name selects it.
  return { type: name, data: parsed } as AgentEvent;
}

/**
 * Parses a server-sent event stream into agent events. An event may be split across chunks, and
 * so may a multibyte character. An unknown event name is skipped. Parsing stops after `done`, and
 * also at a block whose JSON is malformed: the stream then ends without `done`, which the consumer
 * treats as a cut stream.
 */
export async function* parseEventStream(
  chunks: AsyncIterable<Uint8Array>,
): AsyncGenerator<AgentEvent, void, undefined> {
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  for await (const chunk of chunks) {
    buffer += decoder.decode(chunk, { stream: true }).replace(/\r\n?/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const event = parseBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (event === null) return;
      if (event !== undefined) {
        yield event;
        if (event.type === "done") return;
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}

/** The chunks of a response body. */
export async function* readChunks(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<Uint8Array, void, undefined> {
  const reader = body.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      yield value;
    }
  } finally {
    reader.releaseLock();
  }
}

/** `done`: the server ended the stream. `cut`: it closed, or broke, before `done`. */
export type StreamEnd = "done" | "cut";

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/**
 * Hands each event to `onEvent` and reports how the stream ended. A connection that breaks while
 * reading is a cut stream; an abort asked for by the application is rethrown.
 */
export async function consumeEvents(
  events: AsyncIterable<AgentEvent>,
  onEvent: (event: AgentEvent) => void,
): Promise<StreamEnd> {
  let end: StreamEnd = "cut";
  try {
    for await (const event of events) {
      onEvent(event);
      if (event.type === "done") end = "done";
    }
  } catch (error) {
    if (isAbort(error)) throw error;
    return "cut";
  }
  return end;
}

/**
 * Every event of a complete text in the wire format. Unlike a live stream, a recording holds
 * several turns, each ending with its own `done`, so this does not stop at the first one. It stops
 * at a malformed block.
 */
export function parseEventText(text: string): AgentEvent[] {
  const events: AgentEvent[] = [];
  for (const block of text.replace(/\r\n?/g, "\n").split("\n\n")) {
    const event = parseBlock(block);
    if (event === null) break;
    if (event !== undefined) events.push(event);
  }
  return events;
}

/** The turns of a recording: each one runs from `started` to its `done`. */
export function splitTurns(events: readonly AgentEvent[]): AgentEvent[][] {
  const turns: AgentEvent[][] = [];
  let current: AgentEvent[] = [];
  for (const event of events) {
    current.push(event);
    if (event.type === "done") {
      turns.push(current);
      current = [];
    }
  }
  if (current.length > 0) turns.push(current);
  return turns;
}
