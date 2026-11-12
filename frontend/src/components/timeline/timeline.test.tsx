import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ApiClientProvider, createApiClient } from "../../api/client";
import { loadConfig } from "../../config";
import { useCells } from "../../hooks/useCells";
import { backtestSeasons, useTimelineSeries } from "../../hooks/useTimelineSeries";
import { I18nProvider, translate } from "../../i18n";
import { formatMoney } from "../../i18n/format";
import { createMockState, handle } from "../../test/mocks/handlers";
import { ViewProvider, initialView, useView, type ViewState } from "../../state/view";
import {
  FIRST_SEASON,
  INDEX,
  LAST_SEASON,
  LIMIT_CENTS,
  POINT,
  POINT_LABEL,
  SEASONS,
  SUGGESTED_SEASON,
  backtestResult,
  seasonSeries,
} from "../../test/fixtures/bodies";
import { SeasonTimeline } from "./SeasonTimeline";
import { pays } from "./TimelineBars";

const BASEMAP = loadConfig({}).basemaps.relief;
const PLACE_LABELS = loadConfig({}).placeLabels.light;
const SERIES = seasonSeries();
const PAYING = SERIES.seasons.filter((season) => (season.payout?.amount_cents ?? 0) > 0);
/** The width the bars are drawn at when nothing measures the card (as in jsdom). */
const WIDTH = 640;
const SLOT = WIDTH / SEASONS.length;

function xOf(season: number): number {
  return (SEASONS.indexOf(season) + 0.5) * SLOT;
}

function bars(container: HTMLElement): SVGSVGElement {
  const svg = container.querySelector<SVGSVGElement>(".timeline-bars svg");
  if (svg === null) throw new Error("the bars were not rendered");
  return svg;
}

interface CardOptions {
  seasons?: typeof SERIES.seasons | null;
  selected?: number | null;
  suggested?: number | null;
  status?: "ready" | "loading" | "failed";
  onSelect?: (season: number | null) => void;
  onRetry?: () => void;
}

function card({
  seasons = SERIES.seasons,
  selected = null,
  suggested = SUGGESTED_SEASON,
  status = "ready",
  onSelect = () => undefined,
  onRetry,
}: CardOptions = {}) {
  return (
    <I18nProvider locale="en">
      <SeasonTimeline
        seasons={seasons}
        index={INDEX}
        selected={selected}
        suggested={suggested}
        onSelect={onSelect}
        status={status}
        basemap={BASEMAP}
        placeLabels={PLACE_LABELS}
        {...(onRetry === undefined ? {} : { onRetry })}
      />
    </I18nProvider>
  );
}

describe("season timeline [R-12.1-5] [R-16.7-1]", () => {
  it("one_bar_per_season", () => {
    const { container } = render(card());

    expect(container.querySelectorAll(".timeline-bars__bar")).toHaveLength(SEASONS.length);
    expect(SEASONS).toHaveLength(LAST_SEASON - FIRST_SEASON + 1);
    // Decade labels, the dashed trigger line, and no cursor while all seasons are shown.
    const decades = [...container.querySelectorAll(".timeline-bars__decade")].map(
      (label) => label.textContent,
    );
    expect(decades).toEqual(["1950", "1960", "1970", "1980", "1990", "2000", "2010", "2020"]);
    expect(container.querySelectorAll(".timeline-bars__trigger")).toHaveLength(1);
    expect(container.querySelector(".timeline-bars__cursor")).toBeNull();
    expect(screen.getByText(`${FIRST_SEASON}–${LAST_SEASON}`)).toBeInTheDocument();
    expect(screen.getByText("Trigger 105.0 mm")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Seasons" })).toBeInTheDocument();
  });

  it("payout_seasons_are_marked_from_api_payouts_only", () => {
    const { container } = render(card());
    expect(PAYING.length).toBeGreaterThan(0);
    expect(PAYING.length).toBeLessThan(SEASONS.length);

    const marked = [...container.querySelectorAll("g[data-season]")]
      .filter((group) => group.querySelector(".timeline-bars__bar--pay") !== null)
      .map((group) => Number(group.getAttribute("data-season")));

    expect(marked).toEqual(PAYING.map((season) => season.season));
    // Not colour alone: each payout season also has a mark under the baseline.
    expect(container.querySelectorAll(".timeline-bars__mark")).toHaveLength(PAYING.length);
    expect(screen.getByText(translate("en", "timeline.legend_payout"))).toBeInTheDocument();

    // The marks follow the API's payouts, not the position of a value against the trigger.
    const contradicting = SERIES.seasons.map((season) => ({
      ...season,
      index_value: 10,
      payout: { amount_cents: 0, currency: "BRL" as const },
    }));
    const none = render(card({ seasons: contradicting }));
    expect(none.container.querySelector(".timeline-bars__bar--pay")).toBeNull();
    expect(none.container.querySelector(".timeline-bars__mark")).toBeNull();
  });

  it("no_payout_marks_when_payouts_are_null", () => {
    const withoutLimit = seasonSeries(INDEX, null).seasons;
    expect(withoutLimit.every((season) => season.payout === null)).toBe(true);
    expect(withoutLimit.some(pays)).toBe(false);

    const { container } = render(card({ seasons: withoutLimit }));

    expect(container.querySelectorAll(".timeline-bars__bar")).toHaveLength(SEASONS.length);
    expect(container.querySelector(".timeline-bars__bar--pay")).toBeNull();
    expect(container.querySelector(".timeline-bars__mark")).toBeNull();
    expect(screen.queryByText(translate("en", "timeline.legend_payout"))).toBeNull();
  });

  it("range_input_moves_the_season_with_the_keyboard", () => {
    const onSelect = vi.fn();
    const { container, rerender } = render(card({ onSelect }));
    const range = screen.getByRole("slider", { name: "Season" });
    expect(range).toHaveAttribute("aria-valuetext", "All seasons");

    // What an arrow key does to a range input: one step, reported as a change.
    fireEvent.change(range, { target: { value: String(SEASONS.indexOf(1987)) } });
    expect(onSelect).toHaveBeenLastCalledWith(1987);

    rerender(card({ onSelect, selected: 1987 }));
    fireEvent.change(range, { target: { value: String(SEASONS.indexOf(1987) + 1) } });
    expect(onSelect).toHaveBeenLastCalledWith(1988);

    // The slider says the season and its figures, as the API gave them.
    const season = SERIES.seasons[SEASONS.indexOf(1987)];
    const value = `${(season?.index_value ?? NaN).toFixed(1)} mm`;
    expect(range.getAttribute("aria-valuetext")).toContain(`1987: ${value}`);
    expect(container.querySelector(".timeline__readout")).toHaveTextContent(
      range.getAttribute("aria-valuetext") ?? "",
    );
  });

  it("shows the selected season with a cursor and dims the others", () => {
    const { container } = render(card({ selected: PAYING[0]?.season ?? null }));
    const first = PAYING[0];
    if (first === undefined) throw new Error("the fixture has no payout season");

    expect(container.querySelectorAll(".timeline-bars__cursor")).toHaveLength(1);
    const full = [...container.querySelectorAll(".timeline-bars__bar")].filter(
      (bar) => bar.getAttribute("opacity") === "1",
    );
    expect(full).toHaveLength(1);
    const payout = formatMoney(first.payout?.amount_cents ?? 0, "en");
    expect(container.querySelector(".timeline__readout")?.textContent).toContain(
      `payout ${payout}`,
    );
    expect(container.querySelector(".timeline__readout")?.textContent).toContain("payout R$ ");
  });

  it("shows loading and failed states, with a way to try again", () => {
    const onRetry = vi.fn();
    const { rerender } = render(card({ seasons: null, status: "loading" }));
    expect(screen.getByRole("status")).toHaveTextContent(translate("en", "timeline.loading"));
    // The attribution stays next to the map whatever the state of the series.
    expect(screen.getByText(translate("en", "app.disclaimer"))).toBeInTheDocument();

    rerender(card({ seasons: null, status: "failed", onRetry }));
    expect(screen.getByRole("alert")).toHaveTextContent(translate("en", "timeline.failed"));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("reads the seasons of a backtest result only when they have the contract's shape", () => {
    expect(backtestSeasons({ ...backtestResult() })).toEqual(backtestResult().seasons);
    expect(backtestSeasons(null)).toBeNull();
    expect(backtestSeasons({ seasons: [] })).toBeNull();
    expect(
      backtestSeasons({ seasons: [{ season: "1987", index_value: 1, payout: null }] }),
    ).toBeNull();
  });
});

/** The timeline wired to the view store and the hooks, as the shell will wire it. */
function Screen() {
  const { view, dispatch } = useView();
  const series = useTimelineSeries({
    backtest: null,
    point: view.point,
    index: view.index,
    limitCents: view.limitCents,
  });
  const frequency = useCells(
    view.regionId,
    view.index === null ? null : { metric: "trigger_frequency", index: view.index, season: null },
  );
  const cells = useCells(
    view.regionId,
    view.index === null ? null : { metric: view.metric, index: view.index, season: view.season },
  );
  return (
    <>
      <SeasonTimeline
        seasons={series.seasons}
        index={view.index}
        selected={view.season}
        suggested={frequency.data?.suggested_season ?? null}
        onSelect={(season) => {
          dispatch({ type: "season_selected", season });
        }}
        status={series.status}
        basemap={BASEMAP}
        placeLabels={PLACE_LABELS}
      />
      <output data-testid="map">
        {cells.data === undefined
          ? "none"
          : `${cells.data.metric}${cells.isPlaceholderData ? " (previous)" : ""}`}
      </output>
      <History />
    </>
  );
}

/** Stands for the History chart: another reader of the one selected season. */
function History() {
  const { view } = useView();
  return <output data-testid="history">{view.season ?? "all"}</output>;
}

const VIEW: ViewState = {
  ...initialView,
  regionId: "sul-de-minas",
  point: { ...POINT, label: POINT_LABEL },
  index: INDEX,
  limitCents: LIMIT_CENTS,
};

function setUp() {
  const state = createMockState();
  const calls: URL[] = [];
  const gate: { hold: boolean; release: () => void } = { hold: false, release: () => undefined };
  const client = createApiClient({
    baseUrl: "http://veranico.test",
    fetch: async (request) => {
      const url = new URL(request.url);
      calls.push(url);
      if (gate.hold && url.searchParams.has("season")) {
        await new Promise<void>((resolve) => {
          gate.release = resolve;
        });
      }
      return handle(request, state);
    },
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ApiClientProvider client={client}>
        <I18nProvider locale="en">
          <ViewProvider initial={VIEW}>{children}</ViewProvider>
        </I18nProvider>
      </ApiClientProvider>
    </QueryClientProvider>
  );
  const cellRequests = () => calls.filter((url) => url.pathname.endsWith("/cells"));
  return { ...render(<Screen />, { wrapper }), calls, cellRequests, gate };
}

async function ready(container: HTMLElement): Promise<void> {
  await waitFor(() => {
    expect(container.querySelectorAll(".timeline-bars__bar")).toHaveLength(SEASONS.length);
    expect(screen.getByTestId("map")).toHaveTextContent("trigger_frequency");
  });
}

describe("season view [R-12.2-4] [R-16.7-1]", () => {
  it("drag_selects_seasons_and_recolours_by_anomaly", async () => {
    const { container, calls, cellRequests } = setUp();
    await ready(container);
    // Without a backtest the series comes from the API, with the limit, so payouts are the API's.
    const seasons = calls.find((url) => url.pathname.endsWith("/weather/seasons"));
    expect(seasons?.searchParams.get("limit_cents")).toBe(String(LIMIT_CENTS));

    fireEvent.pointerDown(bars(container), { clientX: xOf(1975), pointerId: 1 });
    await waitFor(() => {
      expect(screen.getByTestId("map")).toHaveTextContent(/^season_anomaly$/);
    });
    expect(screen.getByTestId("history")).toHaveTextContent("1975");

    fireEvent.pointerMove(bars(container), { clientX: xOf(1976), pointerId: 1 });
    fireEvent.pointerMove(bars(container), { clientX: xOf(1978), pointerId: 1 });
    fireEvent.pointerUp(bars(container), { pointerId: 1 });
    await waitFor(() => {
      expect(screen.getByTestId("history")).toHaveTextContent("1978");
    });
    // Moving without a button down selects nothing.
    fireEvent.pointerMove(bars(container), { clientX: xOf(1990), pointerId: 1 });
    expect(screen.getByTestId("history")).toHaveTextContent("1978");

    const requested = cellRequests()
      .filter((url) => url.searchParams.get("metric") === "season_anomaly")
      .map((url) => url.searchParams.get("season"));
    expect(requested).toEqual(["1975", "1976", "1978"]);
  });

  it("season_view_opens_on_the_suggested_season", async () => {
    const { container } = setUp();
    await ready(container);

    fireEvent.click(screen.getByRole("button", { name: "Show one season" }));

    expect(screen.getByTestId("history")).toHaveTextContent(String(SUGGESTED_SEASON));
    await waitFor(() => {
      expect(screen.getByTestId("map")).toHaveTextContent(/^season_anomaly$/);
    });
    expect(screen.getByRole("slider", { name: "Season" })).toHaveValue(
      String(SEASONS.indexOf(SUGGESTED_SEASON)),
    );
  });

  it("without a suggestion the season view opens on the latest season", () => {
    const onSelect = vi.fn();
    render(card({ suggested: null, onSelect }));

    fireEvent.click(screen.getByRole("button", { name: "Show one season" }));

    expect(onSelect).toHaveBeenCalledWith(LAST_SEASON);
  });

  it("all_seasons_returns_to_trigger_frequency", async () => {
    const { container, cellRequests } = setUp();
    await ready(container);
    fireEvent.pointerDown(bars(container), { clientX: xOf(1987), pointerId: 1 });
    await waitFor(() => {
      expect(screen.getByTestId("map")).toHaveTextContent(/^season_anomaly$/);
    });
    const before = cellRequests().length;

    fireEvent.click(screen.getByRole("button", { name: "All seasons" }));

    await waitFor(() => {
      expect(screen.getByTestId("map")).toHaveTextContent(/^trigger_frequency$/);
    });
    expect(screen.getByTestId("history")).toHaveTextContent("all");
    expect(container.querySelector(".timeline-bars__cursor")).toBeNull();
    // The frequency grid was already loaded: going back asks the API for nothing.
    expect(cellRequests()).toHaveLength(before);
  });

  it("selected_season_is_shared_with_the_history_chart", async () => {
    const { container } = setUp();
    await ready(container);
    expect(screen.getByTestId("history")).toHaveTextContent("all");

    fireEvent.change(screen.getByRole("slider", { name: "Season" }), {
      target: { value: String(SEASONS.indexOf(2001)) },
    });

    // One selected season in the view store: the timeline's cursor and the other reader agree.
    expect(screen.getByTestId("history")).toHaveTextContent("2001");
    expect(container.querySelectorAll(".timeline-bars__cursor")).toHaveLength(1);
    expect(container.querySelector(".timeline__readout")?.textContent).toContain("2001:");
  });

  it("previous_grid_stays_while_the_next_season_loads", async () => {
    const { container, gate } = setUp();
    await ready(container);

    gate.hold = true;
    fireEvent.pointerDown(bars(container), { clientX: xOf(1987), pointerId: 1 });

    // The season is selected at once; the map keeps the grid it had until the new one arrives.
    expect(screen.getByTestId("history")).toHaveTextContent("1987");
    await waitFor(() => {
      expect(screen.getByTestId("map")).toHaveTextContent("trigger_frequency (previous)");
    });

    gate.hold = false;
    gate.release();
    await waitFor(() => {
      expect(screen.getByTestId("map")).toHaveTextContent(/^season_anomaly$/);
    });
  });
});
