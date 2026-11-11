import { describe, expect, it } from "vitest";

import type { AgentEvent } from "../../api/sse";
import { formatMoney, formatRate } from "../../i18n/format";
import type { Locale } from "../../i18n";
import { finishedTools, initialSession, sessionReducer } from "../../state/session";
import { PREMIUM_CENTS, QUOTE_ID, pricedCover } from "../../test/fixtures/bodies";
import { happyPath } from "../../test/fixtures/streams";
import { linkFigures, type Segment } from "./figures";

function rowsAfter(locale: Locale, turnCount: number) {
  const events: AgentEvent[] = happyPath(locale).turns.slice(0, turnCount).flat();
  return finishedTools(events.reduce(sessionReducer, initialSession("live")));
}

function figures(segments: readonly Segment[]) {
  return segments.filter((segment) => segment.kind !== "text");
}

describe("linkFigures [R-12.3-5]", () => {
  it("links every priced figure to its field in the Quote tab", () => {
    const priced = pricedCover();
    const text = `Premium ${formatMoney(PREMIUM_CENTS, "en")}, rate on line ${formatRate(
      priced.premium.rate_on_line,
      "en",
      2,
    )}, expected loss ${formatMoney(
      priced.simulation.expected_loss.amount_cents,
      "en",
    )}, tails ${formatMoney(priced.simulation.payout_1_in_10.amount_cents, "en")} and ${formatMoney(
      priced.simulation.payout_1_in_100.amount_cents,
      "en",
    )}, limit R$ 300,000.`;
    const found = figures(linkFigures(text, rowsAfter("en", 2), [], "en"));
    // In the recording the one-in-a-hundred payout is the whole limit, R$ 300,000.00: the same
    // text, so the limit links to the first field that holds it.
    expect(found.map((segment) => (segment.kind === "figure" ? segment.key : "flagged"))).toEqual([
      "premium",
      "rate_on_line",
      "expected_loss",
      "payout_1_in_10",
      "payout_1_in_100",
      "payout_1_in_100",
    ]);
    expect(found.every((segment) => segment.kind === "figure" && segment.tab === "quote")).toBe(
      true,
    );
  });

  it("links the backtest figures to the History tab", () => {
    const rows = rowsAfter("en", 1);
    const backtest = pricedCover().backtest;
    const text = `Burn cost ${formatMoney(backtest.burn_cost.amount_cents, "en")}; largest ${formatMoney(
      backtest.max_payout.amount_cents,
      "en",
    )}; trigger 105.0 mm, exit 70 mm.`;
    expect(figures(linkFigures(text, rows, [], "en"))).toEqual([
      expect.objectContaining({ tab: "history", key: "burn_cost" }),
      expect.objectContaining({ tab: "history", key: "max_payout" }),
      expect.objectContaining({ tab: "history", key: "trigger" }),
      expect.objectContaining({ tab: "history", key: "exit" }),
    ]);
  });

  it("matches the notation of the other language", () => {
    const text = `O prêmio é de ${formatMoney(PREMIUM_CENTS, "pt-BR")}, com perda esperada de ${formatMoney(
      pricedCover().simulation.expected_loss.amount_cents,
      "pt-BR",
    )}.`;
    expect(figures(linkFigures(text, rowsAfter("pt-BR", 2), [], "pt-BR"))).toEqual([
      expect.objectContaining({ tab: "quote", key: "premium" }),
      expect.objectContaining({ tab: "quote", key: "expected_loss" }),
    ]);
  });

  it("links the quote identifier to the Quote tab", () => {
    const segments = linkFigures(`Quote ${QUOTE_ID} is a draft.`, rowsAfter("en", 2), [], "en");
    expect(segments).toEqual([
      { kind: "text", text: "Quote " },
      { kind: "figure", text: QUOTE_ID, tab: "quote", key: "quote_id" },
      { kind: "text", text: " is a draft." },
    ]);
  });

  it("sends an unmatched figure to the tab of the most recent tool, without a field", () => {
    const text = "About 12.5% of the limit, or R$ 1,234.56.";
    expect(figures(linkFigures(text, rowsAfter("en", 1), [], "en"))).toEqual([
      { kind: "figure", text: "12.5%", tab: "history", key: null },
      { kind: "figure", text: "R$ 1,234.56", tab: "history", key: null },
    ]);
    expect(figures(linkFigures(text, rowsAfter("en", 4), [], "en"))).toEqual([
      expect.objectContaining({ tab: "approvals", key: null }),
      expect.objectContaining({ tab: "approvals", key: null }),
    ]);
  });

  it("leaves a figure as text when no tool has run", () => {
    expect(linkFigures("Around 12.5% of seasons.", [], [], "en")).toEqual([
      { kind: "text", text: "Around 12.5% of seasons." },
    ]);
  });

  it("marks a flagged value and never links it, even when a field has the same text", () => {
    const premium = formatMoney(PREMIUM_CENTS, "en");
    const segments = linkFigures(`Premium ${premium}.`, rowsAfter("en", 2), [premium], "en");
    expect(figures(segments)).toEqual([{ kind: "flagged", text: premium }]);
  });

  it("does not read a longer amount as a shorter one", () => {
    // R$ 300,000 is the limit; R$ 300,000.50 is another value.
    const segments = linkFigures("It costs R$ 300,000.50.", rowsAfter("en", 2), [], "en");
    expect(figures(segments)).toEqual([
      { kind: "figure", text: "R$ 300,000.50", tab: "quote", key: null },
    ]);
  });

  it("returns the text unchanged when it holds no figure", () => {
    expect(linkFigures("No numbers here.", rowsAfter("en", 2), [], "en")).toEqual([
      { kind: "text", text: "No numbers here." },
    ]);
  });
});
