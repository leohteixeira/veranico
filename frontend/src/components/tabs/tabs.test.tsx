import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../../i18n";
import { formatFraction, formatMoney, formatRate } from "../../i18n/format";
import { cellAt, neighbourRange, valueAt } from "../../map/geometry";
import type { TabId } from "../../state/view";
import {
  INSURED_COL,
  INSURED_ROW,
  POINT,
  REGIONS,
  backtestResult,
  cellGrid,
  pricedCover,
} from "../../test/fixtures/bodies";
import { HistoryTab } from "./history/HistoryTab";
import { readBacktest, readPricedBacktest } from "./history/backtest";
import { Legend } from "./risk/Legend";
import { RiskTab } from "./risk/RiskTab";
import { TabsCard } from "./TabsCard";

function plain(text: string): string {
  return text.replaceAll(" ", " ");
}

function inEnglish(children: ReactNode) {
  return render(<I18nProvider locale="en">{children}</I18nProvider>);
}

function Tabs({ onTab }: { onTab?: (tab: TabId) => void }) {
  const [tab, setTab] = useState<TabId>("risk");
  return (
    <TabsCard
      tab={tab}
      onTab={(next) => {
        setTab(next);
        onTab?.(next);
      }}
      badges={{ approvals: 1 }}
      panels={{
        risk: <p>risk panel</p>,
        history: <p>history panel</p>,
        quote: <p>quote panel</p>,
        approvals: <p>approvals panel</p>,
      }}
    />
  );
}

const RISK = { theme: "light", basemap: "relief", season: null } as const;

describe("tabs card [R-12.1-4]", () => {
  it("tabs_follow_the_aria_tab_pattern_with_arrow_keys [R-12.1-4]", () => {
    inEnglish(<Tabs />);
    const list = screen.getByRole("tablist", { name: "Details" });
    const tabs = within(list).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Risk",
      "History",
      "Quote",
      "Approvals1 1 pending",
    ]);
    const selected = () => tabs.map((tab) => tab.getAttribute("aria-selected"));
    const stops = () => tabs.map((tab) => tab.tabIndex);
    expect(selected()).toEqual(["true", "false", "false", "false"]);
    // One tab stop: the selected tab.
    expect(stops()).toEqual([0, -1, -1, -1]);

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("aria-labelledby", tabs[0]?.id);
    expect(tabs[0]).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveTextContent("risk panel");

    tabs[0]?.focus();
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(selected()).toEqual(["false", "true", "false", "false"]);
    expect(stops()).toEqual([-1, 0, -1, -1]);
    expect(tabs[1]).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("history panel");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", tabs[1]?.id);

    fireEvent.keyDown(list, { key: "End" });
    expect(tabs[3]).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("approvals panel");
    // The arrows wrap around.
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(tabs[0]).toHaveFocus();
    fireEvent.keyDown(list, { key: "ArrowLeft" });
    expect(tabs[3]).toHaveFocus();
    fireEvent.keyDown(list, { key: "Home" });
    expect(tabs[0]).toHaveFocus();
    expect(selected()).toEqual(["true", "false", "false", "false"]);

    const quote = tabs[2];
    if (quote === undefined) throw new Error("no Quote tab");
    fireEvent.click(quote);
    expect(screen.getByRole("tabpanel")).toHaveTextContent("quote panel");
  });
});

describe("risk tab [R-12.3-1]", () => {
  it("risk_shows_cell_value_neighbour_range_and_reading [R-12.3-1]", () => {
    const grid = cellGrid();
    expect(cellAt(grid, POINT.lat, POINT.lon)).toEqual({ row: INSURED_ROW, col: INSURED_COL });
    const value = valueAt(grid, INSURED_ROW, INSURED_COL);
    const range = neighbourRange(grid, INSURED_ROW, INSURED_COL);
    if (value === null || range === null) throw new Error("the fixture has no insured cell");
    const rate = formatFraction(value, "en");
    const min = formatFraction(range.min, "en");
    const max = formatFraction(range.max, "en");

    inEnglish(<RiskTab grid={grid} point={POINT} {...RISK} />);
    const cell = document.querySelector('[data-field="cell"]');
    expect(cell).toHaveTextContent(`Insured cell${rate}`);
    expect(document.querySelector('[data-field="neighbours"]')).toHaveTextContent(
      `Neighbouring cells${min} to ${max}`,
    );
    expect(
      screen.getByText(
        `At the insured cell this cover would have paid in ${rate} of the ${grid.seasons.length} seasons. Its neighbours range from ${min} to ${max}.`,
      ),
    ).toBeVisible();
  });

  it("season_reading_uses_cells_paying [R-12.2-4]", () => {
    const grid = cellGrid(REGIONS[0], { metric: "season_anomaly", season: 1987 });
    const value = valueAt(grid, INSURED_ROW, INSURED_COL);
    if (value === null || grid.cells_paying === null) throw new Error("no season fixture");
    inEnglish(<RiskTab grid={grid} point={POINT} {...RISK} season={1987} />);
    const anomaly = formatFraction(value, "en", { signed: true });
    expect(
      screen.getByText(
        `In 1987 the index at the insured cell was ${anomaly} against its median. ${grid.cells_paying} of the ${grid.values.length} cells of the region would have paid.`,
      ),
    ).toBeVisible();
  });

  it("legend_labels_come_from_the_breaks [R-12.3-1]", () => {
    const { rerender } = inEnglish(
      <Legend
        metric="trigger_frequency"
        breaks={[0, 0.1, 0.2, 0.3, 0.4, 0.5]}
        theme="light"
        basemap="relief"
      />,
    );
    const labels = () => screen.getAllByRole("listitem").map((item) => item.textContent);
    // Six edges are five classes: one swatch each, labelled with its two edges.
    expect(labels()).toEqual(["0% to 10%", "10% to 20%", "20% to 30%", "30% to 40%", "40% to 50%"]);
    expect(screen.getByText("Share of seasons that pay")).toBeVisible();

    rerender(
      <I18nProvider locale="en">
        <Legend
          metric="season_anomaly"
          breaks={[-0.6, -0.4, -0.2, 0, 0.2, 0.4, 0.6]}
          theme="dark"
          basemap="satellite"
        />
      </I18nProvider>,
    );
    expect(labels()).toEqual([
      "-60% to -40%",
      "-40% to -20%",
      "-20% to 0%",
      "0% to +20%",
      "+20% to +40%",
      "+40% to +60%",
    ]);

    // Every cell equal: one class, one value. No value at all: no legend.
    rerender(
      <I18nProvider locale="en">
        <Legend metric="trigger_frequency" breaks={[0.25, 0.25]} theme="light" basemap="relief" />
      </I18nProvider>,
    );
    expect(labels()).toEqual(["25%"]);
    rerender(
      <I18nProvider locale="en">
        <Legend metric="trigger_frequency" breaks={[]} theme="light" basemap="relief" />
      </I18nProvider>,
    );
    expect(screen.queryAllByRole("listitem")).toEqual([]);
  });

  it("legend_keeps_close_edges_apart_with_one_more_decimal [R-12.3-1]", () => {
    inEnglish(
      <Legend
        metric="trigger_frequency"
        breaks={[0.131, 0.134, 0.139]}
        theme="light"
        basemap="relief"
      />,
    );
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "13.1% to 13.4%",
      "13.4% to 13.9%",
    ]);
  });

  it("neighbourhood_marks_the_insured_cell [R-12.3-1]", () => {
    const grid = cellGrid();
    inEnglish(<RiskTab grid={grid} point={POINT} {...RISK} />);
    const table = screen.getByRole("table", {
      name: "The insured cell and its neighbours, north at the top",
    });
    const cells = within(table).getAllByRole("cell");
    expect(cells).toHaveLength(9);
    const insured = cells.filter((cell) => cell.getAttribute("data-insured") === "true");
    expect(insured).toHaveLength(1);
    // The centre of the three by three, named in words as well as framed.
    expect(insured[0]).toBe(cells[4]);
    const value = valueAt(grid, INSURED_ROW, INSURED_COL) ?? 0;
    expect(insured[0]).toHaveTextContent(`${formatFraction(value, "en")} (insured cell)`);
    // North at the top: the first row is the row above the insured cell.
    const north = valueAt(grid, INSURED_ROW - 1, INSURED_COL) ?? 0;
    expect(cells[1]).toHaveTextContent(formatFraction(north, "en"));
  });

  it("neighbourhood_at_the_edge_names_what_is_outside_the_grid", () => {
    const grid = cellGrid();
    const corner = { lat: grid.north - 0.01, lon: grid.west + 0.01 };
    inEnglish(<RiskTab grid={grid} point={corner} {...RISK} />);
    const outside = screen.getAllByText("outside the grid");
    expect(outside).toHaveLength(5);
  });

  it("synthetic_region_is_labelled", () => {
    inEnglish(<RiskTab grid={cellGrid()} point={POINT} {...RISK} synthetic />);
    expect(document.querySelector('[data-note="synthetic"]')).toHaveTextContent(
      "Synthetic weather data",
    );
  });
});

describe("history tab [R-12.3-2]", () => {
  const backtest = backtestResult();

  function renderHistory(overrides: Partial<Parameters<typeof HistoryTab>[0]> = {}) {
    const onSelectSeason = vi.fn();
    inEnglish(
      <HistoryTab
        backtest={backtest}
        season={null}
        onSelectSeason={onSelectSeason}
        {...overrides}
      />,
    );
    return { onSelectSeason };
  }

  function chart(name: "index" | "payout"): HTMLElement {
    const element = document.querySelector(`[data-chart="${name}"]`);
    if (!(element instanceof HTMLElement)) throw new Error(`no ${name} chart`);
    return element;
  }

  it("history_has_two_panels_and_no_second_value_axis [R-12.3-2]", () => {
    renderHistory();
    expect(screen.getByText("Rainfall in the window, per season")).toBeVisible();
    expect(screen.getByText("Payout per season")).toBeVisible();
    for (const name of ["index", "payout"] as const) {
      expect(chart(name).querySelectorAll("svg.recharts-surface")).toHaveLength(1);
      // One value axis per panel: two measures never share a panel.
      expect(chart(name).querySelectorAll(".recharts-yAxis")).toHaveLength(1);
      expect(chart(name).querySelectorAll(".recharts-xAxis")).toHaveLength(1);
      expect(chart(name).querySelectorAll(".recharts-bar")).toHaveLength(1);
    }
    // The same time axis: both panels draw one column per season.
    expect(chart("index").querySelectorAll(".recharts-bar-rectangle")).toHaveLength(
      backtest.seasons.length,
    );
  });

  it("trigger_and_exit_lines_are_labelled [R-12.3-2]", () => {
    renderHistory();
    const lines = chart("index").querySelectorAll(".recharts-reference-line");
    expect(lines).toHaveLength(2);
    // Each line is named, with its value, in the key of the panel: a label inside a plot this
    // dense would sit on the bars.
    const panel = chart("index").closest("figure");
    if (panel === null) throw new Error("the index chart is not in a figure");
    expect(panel.querySelector('[data-line="trigger"]')).toHaveTextContent("Trigger 105.0 mm");
    expect(panel.querySelector('[data-line="exit"]')).toHaveTextContent("Exit 70.0 mm");
    expect(chart("payout").querySelectorAll(".recharts-reference-line")).toHaveLength(0);
  });

  it("selecting_a_bar_moves_the_timeline [R-12.2-4]", () => {
    const { onSelectSeason } = renderHistory();
    const bars = chart("index").querySelectorAll(".recharts-bar-rectangle path");
    const bar = bars[12];
    if (bar === undefined) throw new Error("no bar");
    fireEvent.click(bar);
    expect(onSelectSeason).toHaveBeenLastCalledWith(backtest.seasons[12]?.season);
  });

  it("arrow_keys_move_the_selected_season [R-12.2-4]", () => {
    const { onSelectSeason } = renderHistory({ season: backtest.seasons[10]?.season ?? null });
    const range = screen.getByRole("slider", { name: "Season" });
    expect(range).toHaveValue("10");
    const selected = backtest.seasons[10];
    if (selected === undefined) throw new Error("no season");
    expect(range.getAttribute("aria-valuetext")).toContain(String(selected.season));
    // An arrow key moves a range input by one step.
    fireEvent.change(range, { target: { value: "11" } });
    expect(onSelectSeason).toHaveBeenLastCalledWith(backtest.seasons[11]?.season);

    fireEvent.click(screen.getByRole("button", { name: "All seasons" }));
    expect(onSelectSeason).toHaveBeenLastCalledWith(null);
  });

  it("trend_warning_only_when_significant [R-12.3-2]", () => {
    // The recorded index has no significant trend; the fixture swaps in an authored one.
    renderHistory({ backtest: backtestResult(true) });
    expect(document.querySelector('[data-warning="warning.trend_significant"]')).toHaveTextContent(
      "The index has a significant falling trend of -6.1 per decade. History may misstate current risk.",
    );
  });

  it("no_trend_warning_when_the_trend_is_not_significant [R-12.3-2]", () => {
    renderHistory({ backtest: backtestResult(false) });
    expect(document.querySelector("[data-warning]")).toBeNull();
    // A stray warning for a trend the API calls not significant is not shown either.
    const stray = {
      ...backtestResult(false),
      warnings: [{ code: "warning.trend_significant", params: {} }],
    };
    render(
      <I18nProvider locale="en">
        <HistoryTab backtest={stray} season={null} onSelectSeason={vi.fn()} />
      </I18nProvider>,
    );
    expect(document.querySelector("[data-warning]")).toBeNull();
  });

  it("aggregates_render_api_values_unchanged [R-12.3-2]", () => {
    renderHistory({ highlight: "burn_cost" });
    const field = (name: string) => document.querySelector(`.aggregates [data-field="${name}"]`);
    expect(field("seasons_used")).toHaveTextContent(`Seasons used${backtest.seasons_used}`);
    expect(field("trigger_frequency")).toHaveTextContent(
      `Trigger frequency${formatRate(backtest.trigger_frequency, "en")}`,
    );
    expect(plain(field("burn_cost")?.textContent ?? "")).toBe(
      `Burn cost (average payout)${plain(formatMoney(backtest.burn_cost.amount_cents, "en"))}`,
    );
    expect(plain(field("max_payout")?.textContent ?? "")).toBe(
      `Largest payout${plain(formatMoney(backtest.max_payout.amount_cents, "en"))} in ${backtest.max_payout_season}`,
    );
    // The field a figure link asked for is highlighted, and only that one.
    expect(field("burn_cost")).toHaveAttribute("data-highlight", "true");
    expect(field("max_payout")).not.toHaveAttribute("data-highlight");
  });

  it("table_view_lists_every_season [R-12.3-2]", () => {
    const { onSelectSeason } = renderHistory();
    const toggle = screen.getByRole("button", { name: "Show every season as a table" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide the table" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    const table = screen.getByRole("table", { name: "Every season" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(backtest.seasons.length);
    const paying = backtest.seasons.find((season) => (season.payout?.amount_cents ?? 0) > 0);
    if (paying?.payout === null || paying === undefined) throw new Error("no paying season");
    const row = table.querySelector(`[data-season="${paying.season}"]`);
    expect(plain(row?.textContent ?? "")).toContain(
      plain(formatMoney(paying.payout?.amount_cents ?? 0, "en")),
    );
    fireEvent.click(within(table).getByRole("button", { name: String(paying.season) }));
    expect(onSelectSeason).toHaveBeenLastCalledWith(paying.season);
  });

  it("empty_history_before_any_backtest [R-12.3-2]", () => {
    renderHistory({ backtest: null });
    expect(screen.getByText(/^No backtest yet\./)).toBeVisible();
    expect(document.querySelector("[data-chart]")).toBeNull();
  });

  it("before_a_backtest_the_example_cover_seasons_are_shown_as_the_example [R-12.3-2]", () => {
    // The series the timeline draws (`GET /weather/seasons` for the active cover).
    const example = {
      seasons: backtest.seasons,
      index: backtest.cover.index,
      limit: backtest.cover.limit,
    };
    renderHistory({ backtest: null, example });
    expect(document.querySelector('[data-note="example"]')).toHaveTextContent(
      /^The example cover of this region/,
    );
    expect(chart("index")).toBeVisible();
    expect(chart("payout")).toBeVisible();
    expect(screen.queryByText(/^No backtest yet\./)).toBeNull();
    // Aggregates and the trend come only from a backtest.
    expect(screen.queryByLabelText("Aggregates")).toBeNull();
    expect(document.querySelector("[data-warning]")).toBeNull();
  });

  it("an_example_without_a_limit_draws_no_payout_panel [R-12.3-2]", () => {
    renderHistory({
      backtest: null,
      example: { seasons: backtest.seasons, index: backtest.cover.index, limit: null },
    });
    expect(chart("index")).toBeVisible();
    expect(document.querySelector('[data-chart="payout"]')).toBeNull();
  });

  it("loading_and_failed_states_per_tab [R-12.4-12]", () => {
    const onRetry = vi.fn();
    const { unmount } = inEnglish(
      <HistoryTab
        backtest={null}
        season={null}
        onSelectSeason={vi.fn()}
        status="failed"
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("This did not load.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
    unmount();

    const history = inEnglish(
      <HistoryTab backtest={null} season={null} onSelectSeason={vi.fn()} status="loading" />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    history.unmount();

    const risk = inEnglish(<RiskTab grid={null} point={POINT} {...RISK} status="loading" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    risk.unmount();

    const failed = inEnglish(
      <RiskTab grid={null} point={POINT} {...RISK} status="failed" onRetry={onRetry} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("This did not load.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(2);
    failed.unmount();

    inEnglish(<RiskTab grid={null} point={null} {...RISK} />);
    expect(screen.getByText("Choose a region to see its risk surface.")).toBeVisible();
  });

  it("reads_a_backtest_from_tool_results_and_refuses_other_objects [R-12.3-2]", () => {
    expect(readBacktest({ ...backtest })).toEqual(backtest);
    expect(readPricedBacktest({ quote_id: "Q-1", priced: pricedCover() })).toEqual(
      pricedCover().backtest,
    );
    expect(readBacktest(null)).toBeNull();
    expect(readBacktest({ seasons: backtest.seasons })).toBeNull();
    expect(readBacktest({ ...backtest, burn_cost: "a lot" })).toBeNull();
    expect(readPricedBacktest({ quote_id: "Q-1" })).toBeNull();
  });
});
