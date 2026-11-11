import type { components } from "../../api/schema";
import type { Locale } from "../../i18n";
import { RECORDED_CELLS, recordedIds, recordedResult } from "./recording";

/**
 * Response bodies for the mock layer and the tests, typed by the generated client so a contract
 * change breaks the type check.
 *
 * The happy path's bodies come from the recorded conversation (`recording.ts`): the place, the
 * dataset, the cover, the backtest, the priced quote and the submission are the tool results of
 * the English recording, and the Sul de Minas region and its cell grids are what the API serves
 * from the same ERA5-Land cube (`recorded-cells.json`). What the recording cannot hold is authored
 * here: the workspace, the timestamps of the quote's audit trail, the delivery and its receipt,
 * the API key, and the two other regions, whose grids and season values stay SYNTHETIC (generated
 * from a seed and labelled `synthetic: true`), as do the season values of any other cover.
 *
 * Fixture code may compute (it stands in for the backend); the interface never does.
 */

type Schemas = components["schemas"];

const RECORDED: Locale = "en";
const LOCATION = recordedResult(RECORDED, "resolve_location");
const HISTORY = recordedResult(RECORDED, "get_weather_history");
const BACKTEST = recordedResult(RECORDED, "backtest_index") as unknown as Schemas["BacktestResult"];
const PRICED = recordedResult(RECORDED, "price_cover").priced as Schemas["PricedCover"];
const SUBMISSION = recordedResult(
  RECORDED,
  "request_submission",
) as unknown as Schemas["Submission"];

export const CONVERSATION_ID = recordedIds(RECORDED).conversationId;
export const QUOTE_ID = recordedIds(RECORDED).quoteId;
export const SUBMISSION_ID = recordedIds(RECORDED).submissionId;
export const RECEIPT_ID = "R-9B3WQZ";
export const CARRIER_ID = SUBMISSION.carrier_id;
/** The name `carriers` gives `carrier-1` (`carriers/domain/directory.py`). */
export const CARRIER_NAME = "Seguradora Jatobá (mock)";
export const WORKSPACE_ID = "ws-fixture";

export const REGIONS: Schemas["Region"][] = [
  RECORDED_CELLS.region,
  {
    region_id: "sorriso",
    name: "Sorriso",
    crop: "soybean",
    north: -11.55,
    south: -13.55,
    west: -56.75,
    east: -54.75,
    step_deg: 0.1,
    nx: 20,
    ny: 20,
    synthetic: true,
  },
  {
    region_id: "ribeirao-preto",
    name: "Ribeirão Preto",
    crop: "sugarcane",
    north: -20.15,
    south: -22.15,
    west: -48.85,
    east: -46.85,
    step_deg: 0.1,
    nx: 20,
    ny: 20,
    synthetic: true,
  },
];

/** The example of the happy path: the farm near Três Pontas, as the recording located it. */
export const POINT = { lat: Number(LOCATION.lat), lon: Number(LOCATION.lon) };
export const POINT_LABEL = String(LOCATION.label);
export const H3_CELL = String(LOCATION.h3_cell);
export const ADMIN_REGION = String(LOCATION.admin_region);
export const DATASET_ID = String(HISTORY.dataset_id);
const [, , insuredRow, insuredCol] = DATASET_ID.split(":");
export const INSURED_ROW = Number(insuredRow);
export const INSURED_COL = Number(insuredCol);
/** `get_weather_history`'s whole result, as the recording holds it. */
export const HISTORY_RESULT: Record<string, unknown> = HISTORY;

export const COVER: Schemas["CoverDefinition"] = BACKTEST.cover;
export const INDEX: Schemas["IndexDefinition"] = COVER.index;
export const LIMIT_CENTS = COVER.limit.amount_cents;

export const SEASONS: number[] = BACKTEST.seasons.map((season) => season.season);
export const FIRST_SEASON = SEASONS[0] ?? 0;
export const LAST_SEASON = SEASONS.at(-1) ?? 0;

/** A small seeded generator (mulberry32), so fixtures are the same on every run. */
function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const money = (amount_cents: number): Schemas["Money"] => ({ amount_cents, currency: "BRL" });

function payoutCents(index: Schemas["IndexDefinition"], limitCents: number, value: number): number {
  const share =
    index.index_type === "rainfall_below"
      ? (index.trigger - value) / (index.trigger - index.exit)
      : (value - index.trigger) / (index.exit - index.trigger);
  return Math.round(limitCents * Math.min(1, Math.max(0, share)));
}

/** Synthetic seasonal index values around a mean, one decimal place, the same for the same seed. */
function seasonValues(mean: number, seed: number): number[] {
  const random = seeded(seed);
  return SEASONS.map(() => {
    const spread = (random() + random() + random()) / 3 - 0.5;
    return Math.round(mean * (1 + 1.5 * spread) * 10) / 10;
  });
}

function sameIndex(a: Schemas["IndexDefinition"], b: Schemas["IndexDefinition"]): boolean {
  return (
    a.index_type === b.index_type &&
    a.window.start === b.window.start &&
    a.window.end === b.window.end &&
    a.trigger === b.trigger &&
    a.exit === b.exit
  );
}

/**
 * `GET /weather/seasons` at the insured point. For the recorded cover it is the recorded backtest's
 * seasons (without payouts when no limit is asked); any other cover gets SYNTHETIC values.
 */
export function seasonSeries(
  index: Schemas["IndexDefinition"] = INDEX,
  limitCents: number | null = LIMIT_CENTS,
  seed = 1107,
): Schemas["SeasonSeries"] {
  if (sameIndex(index, INDEX) && (limitCents === null || limitCents === LIMIT_CENTS)) {
    return {
      dataset_id: DATASET_ID,
      index,
      seasons: BACKTEST.seasons.map((season) => ({
        ...season,
        payout: limitCents === null ? null : season.payout,
      })),
      seasons_excluded: BACKTEST.seasons_excluded,
    };
  }
  // The mean sits above the trigger so that only some seasons pay.
  const mean = index.index_type === "rainfall_below" ? index.trigger * 1.42 : index.trigger * 0.7;
  return {
    dataset_id: DATASET_ID,
    index,
    seasons: seasonValues(mean, seed).map((value, at) => ({
      season: SEASONS[at] ?? FIRST_SEASON,
      index_value: value,
      payout: limitCents === null ? null : money(payoutCents(index, limitCents, value)),
    })),
    seasons_excluded: [],
  };
}

/** A significant trend, authored: the recorded index has none (p = 0.126). */
const SIGNIFICANT_TREND: Pick<Schemas["BacktestResult"], "trend" | "warnings"> = {
  trend: { slope_per_decade: -6.1, p_value: "0.031000", significant: true },
  warnings: [
    {
      code: "warning.trend_significant",
      params: { slope_per_decade: -6.1, direction: "decreasing" },
    },
  ],
};

/** The recorded backtest; `trendSignificant` swaps in an authored significant trend. */
export function backtestResult(trendSignificant = false): Schemas["BacktestResult"] {
  return trendSignificant ? { ...BACKTEST, ...SIGNIFICANT_TREND } : { ...BACKTEST };
}

/** The recorded premium of the recorded quote. */
export const PREMIUM_CENTS = PRICED.premium.premium.amount_cents;

/** The recorded priced cover of `price_cover`. */
export function pricedCover(): Schemas["PricedCover"] {
  return PRICED;
}

/** Authored, around the recorded request: the recording holds no quote document or decision. */
export const CREATED_AT = "2026-11-11T22:58:20Z";
export const REQUESTED_AT = SUBMISSION.requested_at;
export const DECIDED_AT = "2026-11-11T23:00:00Z";

export type DeliveryStatus = Schemas["DeliveryState"]["status"];

export function delivery(status: DeliveryStatus = "not_started"): Schemas["DeliveryState"] {
  switch (status) {
    case "not_started":
      return { status, attempts: 0, receipt_id: null, last_error_code: null };
    case "delivering":
      return { status, attempts: 1, receipt_id: null, last_error_code: "http_503" };
    case "delivered":
      return { status, attempts: 2, receipt_id: RECEIPT_ID, last_error_code: null };
    case "abandoned":
      return { status, attempts: 5, receipt_id: null, last_error_code: "http_503" };
  }
}

const AUDIT_CREATED: Schemas["AuditEntry"] = {
  at: CREATED_AT,
  actor: "agent",
  action: { code: "audit.quote_created", params: {} },
};
const AUDIT_TERM_SHEET: Schemas["AuditEntry"] = {
  at: "2026-11-11T22:58:28Z",
  actor: "agent",
  action: { code: "audit.term_sheet_rendered", params: { locale: "en" } },
};
const AUDIT_REQUESTED: Schemas["AuditEntry"] = {
  at: REQUESTED_AT,
  actor: "agent",
  action: { code: "audit.submission_requested", params: { carrier_id: CARRIER_ID } },
};

export function submission(
  status: DeliveryStatus = "not_started",
  decided = false,
  note: string | null = null,
  locale: Locale = RECORDED,
): Schemas["Submission"] {
  return {
    submission_id: recordedIds(locale).submissionId,
    carrier_id: CARRIER_ID,
    requested_at: REQUESTED_AT,
    decided_at: decided ? DECIDED_AT : null,
    decision_note: note,
    delivery: delivery(status),
  };
}

/**
 * A quote of the happy path. Without overrides it is the draft the agent has just priced. Each
 * recording priced its own quote (the figures are the same); `locale` picks its identifiers.
 */
export function quoteView(
  overrides: Partial<Schemas["QuoteView"]> = {},
  locale: Locale = RECORDED,
): Schemas["QuoteView"] {
  return {
    quote_id: recordedIds(locale).quoteId,
    workspace_id: WORKSPACE_ID,
    created_at: CREATED_AT,
    status: "draft",
    location: {
      label: POINT_LABEL,
      lat: POINT.lat,
      lon: POINT.lon,
      h3_cell: H3_CELL,
      admin_region: ADMIN_REGION,
    },
    dataset_id: DATASET_ID,
    cover: COVER,
    priced: pricedCover(),
    submission: null,
    audit: [AUDIT_CREATED],
    ...overrides,
  };
}

/** The quote once the agent has requested the submission: waiting for the human decision. */
export function pendingQuote(locale: Locale = RECORDED): Schemas["QuoteView"] {
  return quoteView(
    {
      status: "pending_approval",
      submission: submission("not_started", false, null, locale),
      audit: [AUDIT_CREATED, AUDIT_TERM_SHEET, AUDIT_REQUESTED],
    },
    locale,
  );
}

export function quoteSummary(quote: Schemas["QuoteView"]): Schemas["QuoteSummary"] {
  return {
    quote_id: quote.quote_id,
    created_at: quote.created_at,
    status: quote.status,
    location_label: quote.location.label,
    premium: quote.priced.premium.premium,
  };
}

export function approvalView(
  status: Schemas["ApprovalView"]["status"] = "pending",
  deliveryStatus: DeliveryStatus = "not_started",
  locale: Locale = RECORDED,
): Schemas["ApprovalView"] {
  const ids = recordedIds(locale);
  return {
    approval_id: ids.submissionId,
    quote_id: ids.quoteId,
    carrier_id: CARRIER_ID,
    carrier_name: CARRIER_NAME,
    location_label: POINT_LABEL,
    limit: money(LIMIT_CENTS),
    premium: money(PREMIUM_CENTS),
    status,
    delivery: delivery(deliveryStatus),
    requested_at: REQUESTED_AT,
  };
}

export const ALLOWANCE: Schemas["Allowance"] = {
  conversations_left: 2,
  messages_left: 15,
  resets_at: "2026-11-11T00:00:00Z",
  boosted: false,
};

export const API_KEY: Schemas["ApiKeyIssued"] = {
  key_id: "key-fixture",
  // Not a credential: a fixed string of the mock layer.
  secret: "vr_fixture_key_shown_once",
  expires_at: "2026-11-24T14:05:00Z",
};

export function problem(code: string, status: number, replayAvailable = false): Schemas["Problem"] {
  return {
    type: `https://veranico.dev/problems/${code}`,
    title: code,
    status,
    code,
    detail: null,
    trace_id: "0af7651916cd43dd8448eb211c80319c",
    replay_available: replayAvailable ? true : null,
  };
}

/** Five frequency classes and six anomaly classes, as the API classifies them. */
export const FREQUENCY_CLASSES = 5;
export const ANOMALY_CLASSES = 6;
/** The season the API suggests for the recorded cover in Sul de Minas. */
export const SUGGESTED_SEASON = RECORDED_CELLS.trigger_frequency.suggested_season ?? FIRST_SEASON;

/**
 * Class edges as the API returns them, both ends included: `classes + 1` edges. Frequency runs
 * from the lowest value of the grid to the highest; anomaly is symmetric around zero.
 */
function classEdges(values: readonly (number | null)[], metric: Schemas["CellGrid"]["metric"]) {
  const present = values.filter((value): value is number => value !== null);
  if (present.length === 0) return [];
  const symmetric = Math.max(...present.map((value) => Math.abs(value)));
  const low = metric === "trigger_frequency" ? Math.min(...present) : -symmetric;
  const high = metric === "trigger_frequency" ? Math.max(...present) : symmetric;
  if (low === high) return [low, high];
  const classes = metric === "trigger_frequency" ? FREQUENCY_CLASSES : ANOMALY_CLASSES;
  return Array.from({ length: classes + 1 }, (_, at) =>
    at === classes ? high : Math.round((low + ((high - low) * at) / classes) * 1e6) / 1e6,
  );
}

interface CellGridRequest {
  metric: Schemas["CellGrid"]["metric"];
  season?: number | null;
  /** The cover's index; absent means the recorded one. */
  index?: Schemas["IndexDefinition"];
}

/** The API's grid for the recorded cover in Sul de Minas, or `null` when it has none. */
function recordedGrid(
  region: Schemas["Region"],
  request: CellGridRequest,
): Schemas["CellGrid"] | null {
  if (region.region_id !== RECORDED_CELLS.region.region_id) return null;
  if (request.index !== undefined && !sameIndex(request.index, RECORDED_CELLS.index)) return null;
  const frequency = RECORDED_CELLS.trigger_frequency;
  if (request.metric === "trigger_frequency") return frequency;
  const season = RECORDED_CELLS.season_anomaly[String(request.season ?? "")];
  return season === undefined ? null : { ...frequency, metric: "season_anomaly", ...season };
}

/**
 * A per-cell grid. Sul de Minas with the recorded cover answers what the API computed from the
 * recording's cube, whose insured cell is the recorded trigger frequency. Anything else gets a
 * SYNTHETIC smooth field over the 20 by 20 cube, so the surface has a shape.
 */
export function cellGrid(
  region: Schemas["Region"] = REGIONS[0] as Schemas["Region"],
  request: CellGridRequest = { metric: "trigger_frequency" },
): Schemas["CellGrid"] {
  const recorded = recordedGrid(region, request);
  if (recorded !== null) return recorded;
  const season = request.season ?? null;
  const phase = season === null ? 0 : (season - FIRST_SEASON) * 0.37;
  const values: (number | null)[] = [];
  for (let row = 0; row < region.ny; row += 1) {
    for (let col = 0; col < region.nx; col += 1) {
      const x = (col + 0.5) / region.nx;
      const y = (row + 0.5) / region.ny;
      const wave =
        Math.sin(5.1 * x + 1.3 * y + phase) * 0.6 + Math.sin(2.2 * y - 3.4 * x + 0.8 + phase) * 0.4;
      const value = request.metric === "trigger_frequency" ? 0.2 + 0.17 * wave : 0.55 * wave;
      values.push(Math.round(value * 1000) / 1000);
    }
  }
  return {
    region_id: region.region_id,
    metric: request.metric,
    nx: region.nx,
    ny: region.ny,
    north: region.north,
    west: region.west,
    step_deg: region.step_deg,
    values,
    breaks: classEdges(values, request.metric),
    seasons: SEASONS,
    cells_paying:
      request.metric === "season_anomaly"
        ? values.filter((value) => value !== null && value < -0.2).length
        : null,
    suggested_season: SUGGESTED_SEASON,
  };
}
