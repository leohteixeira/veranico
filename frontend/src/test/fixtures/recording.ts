import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { components } from "../../api/schema";
import type { AgentEvent, AgentEventName } from "../../api/sse";
import type { Locale } from "../../i18n";

/**
 * The recorded happy path, read from the backend's versioned recordings (SPEC 9.6): one
 * `<locale>.jsonl` per language, a metadata line and then the events `GET /replays/{locale}`
 * streams. They were made by `make record-replay` with the real model on the real ERA5-Land cubes
 * (gate H1). The stream fixtures and the mock API's bodies are derived from them here and in
 * `bodies.ts`, so a new recording changes the tests' figures without any edit.
 *
 * `recorded-cells.json` is the per-cell grids of the same cube (the recording carries none),
 * written by `backend/scripts/export_cells.py`.
 */

type Schemas = components["schemas"];

const REPLAYS = join(
  import.meta.dirname,
  "..",
  "..",
  "..",
  "..",
  "backend",
  "src",
  "veranico",
  "modules",
  "assistant",
  "replays",
);

export interface RecordingHeader {
  prompt_version: string;
  model: string;
  recorded_on: string;
  locale: Locale;
  data_source: string;
  synthetic: boolean;
  cube_checksum: string | null;
}

export interface Recording {
  header: RecordingHeader;
  events: AgentEvent[];
}

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

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parse(locale: Locale): Recording {
  const lines = readFileSync(join(REPLAYS, `${locale}.jsonl`), "utf8")
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line) => JSON.parse(line) as unknown);
  const [header, ...rest] = lines;
  if (!isObject(header) || header.locale !== locale) {
    throw new Error(`replays/${locale}.jsonl does not start with its metadata`);
  }
  const events = rest.map((line, at) => {
    if (!isObject(line) || typeof line.event !== "string" || !EVENT_NAMES.has(line.event)) {
      throw new Error(`replays/${locale}.jsonl: line ${at + 2} is not an agent event`);
    }
    // The payload shape is the contract of the generated client; the wire name selects it.
    return { type: line.event, data: line.data } as AgentEvent;
  });
  return { header: header as unknown as RecordingHeader, events };
}

const RECORDINGS = new Map<Locale, Recording>();

export function recording(locale: Locale): Recording {
  let found = RECORDINGS.get(locale);
  if (found === undefined) {
    found = parse(locale);
    RECORDINGS.set(locale, found);
  }
  return found;
}

/** The result of the one successful call of `tool` in the recording of `locale`. */
export function recordedResult(locale: Locale, tool: string): Record<string, unknown> {
  for (const event of recording(locale).events) {
    if (event.type === "tool_finished" && event.data.tool === tool && event.data.status === "ok") {
      if (isObject(event.data.result)) return event.data.result;
    }
  }
  throw new Error(`the ${locale} recording has no result of ${tool}`);
}

/** The identifiers the recording of one language carries. */
export interface RecordedIds {
  conversationId: string;
  quoteId: string;
  submissionId: string;
}

export function recordedIds(locale: Locale): RecordedIds {
  const started = recording(locale).events.find((event) => event.type === "started");
  if (started?.type !== "started") throw new Error(`the ${locale} recording has no turn`);
  return {
    conversationId: started.data.conversation_id,
    quoteId: String(recordedResult(locale, "price_cover").quote_id),
    submissionId: String(recordedResult(locale, "request_submission").submission_id),
  };
}

/** The grids of one season's anomaly, without the fields every grid of the region shares. */
interface SeasonAnomaly {
  values: (number | null)[];
  breaks: number[];
  cells_paying: number | null;
}

export interface RecordedCells {
  source: { cube_checksum: string; replay: string };
  region: Schemas["Region"];
  index: Schemas["IndexDefinition"];
  trigger_frequency: Schemas["CellGrid"];
  season_anomaly: Record<string, SeasonAnomaly>;
}

export const RECORDED_CELLS = JSON.parse(
  readFileSync(join(import.meta.dirname, "recorded-cells.json"), "utf8"),
) as RecordedCells;
