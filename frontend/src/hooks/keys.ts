import type { components } from "../api/schema";

type Schemas = components["schemas"];

export interface CellsRequest {
  metric: Schemas["CellGrid"]["metric"];
  index: Schemas["IndexDefinition"];
  season: number | null;
}

export interface SeasonsRequest {
  lat: number;
  lon: number;
  index: Schemas["IndexDefinition"];
  limitCents: number | null;
}

/** An index definition as the flat query parameters of SPEC 11.2. */
export function indexQuery(index: Schemas["IndexDefinition"]) {
  return {
    index_type: index.index_type,
    window_start: index.window.start,
    window_end: index.window.end,
    trigger: index.trigger,
    exit: index.exit,
  };
}

/** Query keys, in one place so a mutation invalidates exactly what it changed. */
export const keys = {
  regions: ["regions"] as const,
  cells: (regionId: string | null, request: CellsRequest | null) =>
    ["cells", regionId, request] as const,
  seasons: (request: SeasonsRequest | null) => ["seasons", request] as const,
  quotes: ["quotes"] as const,
  quote: (quoteId: string | null) => ["quotes", quoteId] as const,
  approvals: ["approvals"] as const,
  allowance: ["allowance"] as const,
  conversation: (conversationId: string | null) => ["conversation", conversationId] as const,
  replay: (locale: string) => ["replay", locale] as const,
};
