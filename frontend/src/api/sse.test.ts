import { describe, expect, it } from "vitest";

import { chatEvents, errorEvents, replayEvents, serialise } from "../test/fixtures/streams";
import {
  consumeEvents,
  parseEventStream,
  parseEventText,
  readChunks,
  serialiseEvent,
  splitTurns,
  type AgentEvent,
} from "./sse";

const encoder = new TextEncoder();

async function* chunksOf(parts: readonly Uint8Array[]): AsyncGenerator<Uint8Array> {
  for (const part of parts) {
    await Promise.resolve();
    yield part;
  }
}

async function collect(parts: readonly Uint8Array[]): Promise<AgentEvent[]> {
  const events: AgentEvent[] = [];
  for await (const event of parseEventStream(chunksOf(parts))) events.push(event);
  return events;
}

/** The bytes cut into pieces of `size` bytes. */
function slices(bytes: Uint8Array, size: number): Uint8Array[] {
  const parts: Uint8Array[] = [];
  for (let at = 0; at < bytes.length; at += size) parts.push(bytes.slice(at, at + size));
  return parts;
}

const STARTED: AgentEvent = {
  type: "started",
  data: { conversation_id: "cv-1", message_id: "m-2" },
};
const DELTA: AgentEvent = { type: "text_delta", data: { text: "Três Pontas, ação" } };
const DONE: AgentEvent = {
  type: "done",
  data: {
    conversation_id: "cv-1",
    message_id: "m-2",
    stop_reason: "end_turn",
    prompt_version: "1",
  },
};

describe("event stream parser [R-12.4-2] [R-16.7-1]", () => {
  it("event_split_across_chunks", async () => {
    const turn = errorEvents();
    const bytes = encoder.encode(serialise(turn));

    for (const size of [1, 7, 64]) {
      expect(await collect(slices(bytes, size))).toEqual(turn);
    }
  });

  it("two_events_in_one_chunk", async () => {
    const chunk = encoder.encode(serialiseEvent(STARTED) + serialiseEvent(DELTA));

    expect(await collect([chunk])).toEqual([STARTED, DELTA]);
  });

  it("multibyte_character_split_across_chunks", async () => {
    const bytes = encoder.encode(serialiseEvent(DELTA));
    // "ê" takes two bytes in UTF-8: cut between them.
    const cut = bytes.indexOf(0xc3) + 1;

    expect(await collect([bytes.slice(0, cut), bytes.slice(cut)])).toEqual([DELTA]);
  });

  it("unknown_event_name_is_ignored", async () => {
    const text =
      serialiseEvent(STARTED) +
      'event: heartbeat\ndata: {"at":1}\n\n' +
      ": a comment\n\n" +
      serialiseEvent(DONE);

    expect(await collect([encoder.encode(text)])).toEqual([STARTED, DONE]);
  });

  it("malformed_json_ends_the_stream_as_cut", async () => {
    const text =
      serialiseEvent(STARTED) + 'event: text_delta\ndata: {"text": \n\n' + serialiseEvent(DONE);
    const seen: AgentEvent[] = [];

    const end = await consumeEvents(parseEventStream(chunksOf([encoder.encode(text)])), (event) =>
      seen.push(event),
    );

    expect(seen).toEqual([STARTED]);
    expect(end).toBe("cut");
  });

  it("stream_without_done_is_reported_as_cut", async () => {
    const text = serialiseEvent(STARTED) + serialiseEvent(DELTA);
    const seen: AgentEvent[] = [];

    const end = await consumeEvents(parseEventStream(chunksOf([encoder.encode(text)])), (event) =>
      seen.push(event),
    );

    expect(seen).toEqual([STARTED, DELTA]);
    expect(end).toBe("cut");
  });

  it("a stream that ends with done is reported as done and nothing after it is read", async () => {
    const text = serialiseEvent(STARTED) + serialiseEvent(DONE) + serialiseEvent(DELTA);
    const seen: AgentEvent[] = [];

    const end = await consumeEvents(parseEventStream(chunksOf([encoder.encode(text)])), (event) =>
      seen.push(event),
    );

    expect(seen).toEqual([STARTED, DONE]);
    expect(end).toBe("done");
  });

  it("a connection that breaks while reading is a cut stream", async () => {
    async function* broken(): AsyncGenerator<Uint8Array> {
      yield encoder.encode(serialiseEvent(STARTED));
      await Promise.resolve();
      throw new TypeError("network error");
    }
    const seen: AgentEvent[] = [];

    const end = await consumeEvents(parseEventStream(broken()), (event) => seen.push(event));

    expect(seen).toEqual([STARTED]);
    expect(end).toBe("cut");
  });

  it("accepts CRLF line endings", async () => {
    const text = serialiseEvent(STARTED).replace(/\n/g, "\r\n");

    expect(await collect([encoder.encode(text)])).toEqual([STARTED]);
  });

  it("reads the chunks of a response body", async () => {
    const body = new Response(serialiseEvent(STARTED) + serialiseEvent(DONE)).body;
    if (body === null) throw new Error("the response has no body");
    const events: AgentEvent[] = [];

    for await (const event of parseEventStream(readChunks(body))) events.push(event);

    expect(events).toEqual([STARTED, DONE]);
  });
});

describe("recorded streams", () => {
  it("parses every turn of a recording, past each done", () => {
    const events = replayEvents("pt-BR");

    expect(parseEventText(serialise(events))).toEqual(events);
  });

  it("splits a recording into turns that each run from started to done", () => {
    const turns = splitTurns(chatEvents("en"));

    expect(turns).toHaveLength(4);
    for (const turn of turns) {
      expect(turn[0]?.type).toBe("started");
      expect(turn[turn.length - 1]?.type).toBe("done");
    }
  });
});
