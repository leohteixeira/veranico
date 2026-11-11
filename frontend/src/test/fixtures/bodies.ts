import type { components } from "../../api/schema";

/**
 * Response bodies for the mock layer and the tests, typed by the generated client so a contract
 * change breaks the type check. Every weather value and every figure here is SYNTHETIC: generated
 * from a seed for tests and development, never weather history or a real quote.
 *
 * Fixture code may compute (it stands in for the backend); the interface never does.
 */

type Schemas = components["schemas"];

export const CONVERSATION_ID = "cv-01hx7m3k9q";
export const QUOTE_ID = "Q-7K2M9P";
export const SUBMISSION_ID = "S-4HX8TD";
export const RECEIPT_ID = "R-9B3WQZ";
export const CARRIER_ID = "carrier-1";
export const CARRIER_NAME = "Aurora Re (mock)";
export const WORKSPACE_ID = "ws-fixture";

export const REGIONS: Schemas["Region"][] = [
  {
    region_id: "sul-de-minas",
    name: "Sul de Minas",
    crop: "coffee",
    north: -20.45,
    south: -22.45,
    west: -46.55,
    east: -44.55,
    step_deg: 0.1,
    nx: 20,
    ny: 20,
    synthetic: true,
  },
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

/** The example of the happy path: the coffee farm near Três Pontas. */
export const POINT = { lat: -21.41, lon: -45.48 };
export const POINT_LABEL = "Três Pontas, MG";
export const INSURED_ROW = 9;
export const INSURED_COL = 10;
export const DATASET_ID = `cube:sul-de-minas:${INSURED_ROW}:${INSURED_COL}`;

export const INDEX: Schemas["IndexDefinition"] = {
  index_type: "rainfall_below",
  window: { start: "09-01", end: "10-31" },
  trigger: 150,
  exit: 75,
};
export const LIMIT_CENTS = 30_000_000;
export const COVER: Schemas["CoverDefinition"] = {
  index: INDEX,
  limit: { amount_cents: LIMIT_CENTS, currency: "BRL" },
};

export const FIRST_SEASON = 1950;
export const LAST_SEASON = 2023;
export const SEASONS: number[] = Array.from(
  { length: LAST_SEASON - FIRST_SEASON + 1 },
  (_, offset) => FIRST_SEASON + offset,
);

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

/** A rate as the API writes it: six decimal places. */
const rate = (value: number): string => value.toFixed(6);

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

export function seasonSeries(
  index: Schemas["IndexDefinition"] = INDEX,
  limitCents: number | null = LIMIT_CENTS,
  seed = 1107,
): Schemas["SeasonSeries"] {
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

export function backtestResult(trendSignificant = true): Schemas["BacktestResult"] {
  const seasons = seasonSeries().seasons;
  const payouts = seasons.map((season) => season.payout?.amount_cents ?? 0);
  const paying = payouts.filter((payout) => payout > 0).length;
  const largest = Math.max(...payouts);
  return {
    dataset_id: DATASET_ID,
    cover: COVER,
    seasons,
    seasons_used: seasons.length,
    seasons_excluded: [],
    trigger_frequency: rate(paying / seasons.length),
    burn_cost: money(Math.round(payouts.reduce((sum, payout) => sum + payout, 0) / seasons.length)),
    max_payout: money(largest),
    max_payout_season: largest > 0 ? (seasons[payouts.indexOf(largest)]?.season ?? null) : null,
    trend: { slope_per_decade: -4.2, p_value: "0.031000", significant: trendSignificant },
    warnings: trendSignificant
      ? [
          {
            code: "warning.trend_significant",
            params: { slope_per_decade: -4.2, direction: "decreasing" },
          },
        ]
      : [],
  };
}

const EXPECTED_LOSS_CENTS = 1_620_000;
const STD_DEV_CENTS = 2_070_000;
/** Expected loss + 0.3 × standard deviation + 0.15 × expected loss, as `pricing` would return. */
export const PREMIUM_CENTS = 2_484_000;

export function pricedCover(): Schemas["PricedCover"] {
  const backtest = backtestResult();
  return {
    backtest,
    simulation: {
      method: "gamma_mle",
      n: 100_000,
      seed: 42,
      expected_loss: money(EXPECTED_LOSS_CENTS),
      std_dev: money(STD_DEV_CENTS),
      probability_of_payout: "0.171200",
      payout_1_in_10: money(6_300_000),
      payout_1_in_100: money(21_450_000),
      gap_to_burn_cost: money(EXPECTED_LOSS_CENTS - backtest.burn_cost.amount_cents),
    },
    premium: {
      premium: money(PREMIUM_CENTS),
      rate_on_line: "0.082800",
      risk_load: "0.300000",
      expense_load: "0.150000",
    },
    assumptions: [
      { code: "assumption.index_type", params: { index_type: INDEX.index_type } },
      { code: "assumption.window", params: { start: INDEX.window.start, end: INDEX.window.end } },
      {
        code: "assumption.seasons_used",
        params: {
          seasons_used: backtest.seasons_used,
          first_season: FIRST_SEASON,
          last_season: LAST_SEASON,
        },
      },
      {
        code: "assumption.simulation_method",
        params: { method: "gamma_mle", n: 100_000, seed: 42 },
      },
      {
        code: "assumption.loads",
        params: { risk_load_rate: "0.300000", expense_load_rate: "0.150000" },
      },
      { code: "assumption.data_source", params: { source: "synthetic" } },
    ],
  };
}

export const CREATED_AT = "2026-11-10T14:05:00Z";
export const REQUESTED_AT = "2026-11-10T14:07:30Z";
export const DECIDED_AT = "2026-11-10T14:09:00Z";

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
  at: "2026-11-10T14:06:40Z",
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
): Schemas["Submission"] {
  return {
    submission_id: SUBMISSION_ID,
    carrier_id: CARRIER_ID,
    requested_at: REQUESTED_AT,
    decided_at: decided ? DECIDED_AT : null,
    decision_note: note,
    delivery: delivery(status),
  };
}

/** A quote of the happy path. Without overrides it is the draft the agent has just priced. */
export function quoteView(overrides: Partial<Schemas["QuoteView"]> = {}): Schemas["QuoteView"] {
  return {
    quote_id: QUOTE_ID,
    workspace_id: WORKSPACE_ID,
    created_at: CREATED_AT,
    status: "draft",
    location: {
      label: POINT_LABEL,
      lat: POINT.lat,
      lon: POINT.lon,
      h3_cell: "86a8a0c57ffffff",
      admin_region: "Minas Gerais",
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
export function pendingQuote(): Schemas["QuoteView"] {
  return quoteView({
    status: "pending_approval",
    submission: submission(),
    audit: [AUDIT_CREATED, AUDIT_TERM_SHEET, AUDIT_REQUESTED],
  });
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
): Schemas["ApprovalView"] {
  return {
    approval_id: SUBMISSION_ID,
    quote_id: QUOTE_ID,
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

export const FREQUENCY_BREAKS = [0.06, 0.12, 0.18, 0.24, 0.32];
export const ANOMALY_BREAKS = [-0.4, -0.2, -0.05, 0.05, 0.2, 0.4];
export const SUGGESTED_SEASON = 1987;

interface CellGridRequest {
  metric: Schemas["CellGrid"]["metric"];
  season?: number | null;
}

/**
 * A synthetic per-cell grid: a smooth field over the 20 by 20 cube, so the surface has a shape.
 * The insured cell carries the trigger frequency of the backtest fixture, so the map and the
 * History tab agree.
 */
export function cellGrid(
  region: Schemas["Region"] = REGIONS[0] as Schemas["Region"],
  request: CellGridRequest = { metric: "trigger_frequency" },
): Schemas["CellGrid"] {
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
  if (request.metric === "trigger_frequency" && region.region_id === "sul-de-minas") {
    values[INSURED_ROW * region.nx + INSURED_COL] = Number(backtestResult().trigger_frequency);
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
    breaks: request.metric === "trigger_frequency" ? FREQUENCY_BREAKS : ANOMALY_BREAKS,
    seasons: SEASONS,
    cells_paying:
      request.metric === "season_anomaly"
        ? values.filter((value) => value !== null && value < -0.2).length
        : null,
    suggested_season: SUGGESTED_SEASON,
  };
}
