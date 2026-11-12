import { describe, expect, it } from "vitest";

import { translateCoded, translateProblem, translateValue } from "./coded";
import { LOCALES, lookup } from "./index";

// contracts.md section 1, plus `not_implemented`, `shutting_down`, `unauthorized` and
// `internal_error`: one class each in the kernel.
const PROBLEM_CODES = [
  "not_found",
  "unauthorized",
  "forbidden",
  "invalid_arguments",
  "conflict",
  "rate_limited",
  "allowance_exhausted",
  "spend_ceiling_reached",
  "outside_coverage",
  "location_not_found",
  "location_ambiguous",
  "weather_source_unavailable",
  "dataset_not_found",
  "invalid_cover",
  "insufficient_history",
  "invalid_state",
  "idempotency_conflict",
  "unknown_carrier",
  "delivery_failed",
  "model_unavailable",
  "message_too_long",
  "not_implemented",
  "shutting_down",
  "internal_error",
];

const AUDIT_ACTIONS = [
  "quote_created",
  "term_sheet_rendered",
  "submission_requested",
  "approved",
  "rejected",
  "webhook_attempt",
  "receipt_recorded",
  "delivery_abandoned",
  "redelivery_requested",
];

const TOOLS = [
  "resolve_location",
  "get_weather_history",
  "backtest_index",
  "price_cover",
  "find_extreme_seasons",
  "draft_term_sheet",
  "request_submission",
];

const PRICING_CODES = [
  "warning.trend_significant",
  "warning.seasons_excluded",
  "assumption.index_type",
  "assumption.window",
  "assumption.seasons_used",
  "assumption.simulation_method",
  "assumption.loads",
  "assumption.data_source",
];

const ENUMERATIONS: Record<string, string[]> = {
  "status.quote": ["draft", "pending_approval", "approved", "rejected", "submitted"],
  "status.approval": ["pending", "approved", "rejected"],
  "status.delivery": ["not_started", "delivering", "delivered", "abandoned"],
  actor: ["agent", "human", "api_client", "system", "carrier"],
  admission: ["ok", "visitor_allowance", "day_ceiling", "month_ceiling"],
  stop: ["end_turn", "tool_limit", "budget", "error"],
  toolname: TOOLS,
  step: ["locate", "history", "backtest", "price", "term_sheet", "approval"],
  crop: ["coffee", "soybean", "sugarcane"],
  index: ["rainfall_below", "dry_spell_above"],
  method: ["gamma_mle", "bootstrap"],
  metric: ["trigger_frequency", "season_anomaly"],
  source: ["era5-land/cds", "era5/open-meteo", "synthetic"],
};

describe("codes from the API", () => {
  it("[R-13-5] every_problem_code_is_translated_in_both_languages", () => {
    for (const locale of LOCALES) {
      for (const code of PROBLEM_CODES) {
        const text = translateProblem(code, locale);
        expect(text, `${code} ${locale}`).not.toBe(code);
        expect(text.trim(), `${code} ${locale}`).not.toBe("");
      }
    }
    expect(translateProblem("allowance_exhausted", "pt-BR")).not.toBe(
      translateProblem("allowance_exhausted", "en"),
    );
  });

  it("[R-13-5] every enumerated value of the API has a translation in both languages", () => {
    for (const locale of LOCALES) {
      for (const [namespace, values] of Object.entries(ENUMERATIONS)) {
        for (const value of values) {
          expect(lookup(locale, `${namespace}.${value}`), `${namespace}.${value}`).toBeDefined();
        }
      }
    }
    expect(translateValue("status.quote", "pending_approval", "pt-BR")).toBe(
      "Aguardando aprovação",
    );
    expect(translateValue("actor", "carrier", "en")).toBe("Carrier");
  });

  it("[R-13-5] every audit action, tool summary and pricing code reads as text without parameters", () => {
    const codes = [
      ...AUDIT_ACTIONS.map((action) => `audit.${action}`),
      ...TOOLS.map((tool) => `tool.${tool}`),
      "tool.resolve_location.candidates",
      "tool.error",
      "warning.trend_significant",
      "warning.seasons_excluded",
    ];
    for (const locale of LOCALES) {
      for (const code of codes) {
        const text = translateCoded({ code, params: {} }, locale);
        expect(text, `${code} ${locale}`).not.toBe(code);
        expect(text, `${code} ${locale}`).not.toMatch(/[{}]/);
      }
    }
  });

  it("[R-13-5] tool summaries and the audit trail name the source and the carrier, never an id", () => {
    const history = {
      code: "tool.get_weather_history",
      params: {
        dataset_id: "cube:sul-de-minas:9:10",
        first_year: 1950,
        last_year: 2025,
        source: "era5-land/cds",
      },
    };
    expect(translateCoded(history, "en")).toBe(
      "ERA5-Land, Copernicus Climate Change Service · 1950 to 2025",
    );
    expect(translateCoded(history, "pt-BR")).toBe(
      "ERA5-Land, Copernicus Climate Change Service · 1950 a 2025",
    );
    const requested = { code: "audit.submission_requested", params: { carrier_id: "carrier-1" } };
    expect(translateCoded(requested, "en")).toBe("Submission requested");
    expect(
      translateCoded(
        { ...requested, params: { ...requested.params, carrier_name: "Seguradora Jatobá (mock)" } },
        "pt-BR",
      ),
    ).toBe("Submissão solicitada para Seguradora Jatobá (mock)");
  });

  it("[R-13-5] the eight pricing codes are translated with the parameters pricing sends", () => {
    const params: Record<string, Record<string, string | number>> = {
      "warning.trend_significant": { slope_per_decade: -12.5, direction: "decreasing" },
      "warning.seasons_excluded": { count: 2, seasons: "1951, 1987" },
      "assumption.index_type": { index_type: "rainfall_below" },
      "assumption.window": { start: "09-01", end: "10-31" },
      "assumption.seasons_used": { seasons_used: 74, first_season: 1950, last_season: 2023 },
      "assumption.simulation_method": { method: "gamma_mle", n: 100000, seed: 42 },
      "assumption.loads": { risk_load_rate: "0.300000", expense_load_rate: "0.150000" },
      "assumption.data_source": { source: "synthetic" },
    };
    for (const locale of LOCALES) {
      for (const code of PRICING_CODES) {
        const text = translateCoded({ code, params: params[code] ?? {} }, locale);
        expect(text, `${code} ${locale}`).not.toBe(code);
        expect(text, `${code} ${locale}`).not.toMatch(/[{}]/);
      }
    }
    expect(
      translateCoded(
        { code: "assumption.window", params: params["assumption.window"] ?? {} },
        "en",
      ),
    ).toBe("Coverage window from Sep 1 to Oct 31; a season is labelled by its start year.");
    expect(
      translateCoded(
        { code: "assumption.seasons_used", params: params["assumption.seasons_used"] ?? {} },
        "en",
      ),
    ).toBe("74 seasons used, 1950 to 2023.");
    expect(
      translateCoded(
        {
          code: "assumption.simulation_method",
          params: params["assumption.simulation_method"] ?? {},
        },
        "pt-BR",
      ),
    ).toBe(
      "Distribuição gama ajustada aos totais por safra; 100.000 safras simuladas; semente 42.",
    );
    expect(
      translateCoded(
        { code: "warning.trend_significant", params: params["warning.trend_significant"] ?? {} },
        "pt-BR",
      ),
    ).toContain("-12,5");
    expect(
      translateCoded({ code: "assumption.data_source", params: { source: "synthetic" } }, "en"),
    ).toContain("synthetic");
  });

  it("[R-12-2] [R-13-4] coded_params_ending_in_cents_and_rate_are_formatted", () => {
    expect(
      translateCoded(
        { code: "tool.price_cover", params: { quote_id: "Q-7K2M9P", premium_cents: 1_234_567 } },
        "pt-BR",
      ),
    ).toBe("Q-7K2M9P · prêmio de R$ 12.345,67");
    expect(
      translateCoded(
        {
          code: "tool.backtest_index",
          params: { seasons_used: 74, trigger_frequency_rate: "0.175676" },
        },
        "en",
      ),
    ).toBe("74 seasons · pays in 17.5676%");
    expect(
      translateCoded(
        {
          code: "assumption.loads",
          params: { risk_load_rate: "0.300000", expense_load_rate: "0.150000" },
        },
        "en",
      ),
    ).toBe("Risk load of 30% on the standard deviation; expense load of 15% on the expected loss.");
  });

  it("[R-13-5] an optional parameter that is absent selects another wording, never a hole", () => {
    expect(
      translateCoded(
        {
          code: "audit.webhook_attempt",
          params: { attempt: 1, duration_ms: 31, status_code: 503 },
        },
        "en",
      ),
    ).toBe("Webhook attempt 1: the carrier answered 503");
    expect(
      translateCoded(
        {
          code: "audit.webhook_attempt",
          params: { attempt: 2, duration_ms: 5000, error_code: "timeout" },
        },
        "en",
      ),
    ).toBe("Webhook attempt 2 failed: timeout");
    expect(translateCoded({ code: "audit.webhook_attempt", params: {} }, "pt-BR")).toBe(
      "Tentativa de webhook",
    );
    expect(
      translateCoded({ code: "tool.error", params: { error_code: "outside_coverage" } }, "en"),
    ).toBe("Failed: This point is outside the area the weather data covers.");
    expect(
      translateCoded({ code: "audit.term_sheet_rendered", params: { locale: "pt-BR" } }, "en"),
    ).toBe("Term sheet rendered (Português)");
  });

  it("[R-13-5] unknown_code_renders_the_code", () => {
    expect(translateCoded({ code: "audit.something_new", params: { a: 1 } }, "en")).toBe(
      "audit.something_new",
    );
    expect(translateCoded({ code: "tool.unknown_tool", params: {} }, "pt-BR")).toBe(
      "tool.unknown_tool",
    );
    // A code outside the four namespaces never reaches another part of the catalogue.
    expect(translateCoded({ code: "app.disclaimer", params: {} }, "en")).toBe("app.disclaimer");
    expect(translateProblem("brand_new_problem", "pt-BR")).toBe("brand_new_problem");
    expect(translateValue("status.quote", "archived", "en")).toBe("archived");
  });
});
