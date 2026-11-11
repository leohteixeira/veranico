import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type RefObject,
} from "react";

import type { components } from "./api/schema";
import { ConversationCard } from "./components/conversation/ConversationCard";
import { useConversationCard } from "./components/conversation/useConversationCard";
import { ApprovalsTab, pendingCount } from "./components/tabs/approvals/ApprovalsTab";
import { readBacktest, readPricedBacktest } from "./components/tabs/history/backtest";
import { HistoryTab } from "./components/tabs/history/HistoryTab";
import { QuoteTab } from "./components/tabs/quote/QuoteTab";
import { readRecordedQuote } from "./components/tabs/quote/recorded";
import { RiskTab } from "./components/tabs/risk/RiskTab";
import { TabsCard } from "./components/tabs/TabsCard";
import { SeasonTimeline } from "./components/timeline/SeasonTimeline";
import { TopBar } from "./components/topbar/TopBar";
import { config } from "./config";
import { useTheme } from "./design/theme";
import { useApprovals } from "./hooks/useApprovals";
import { useCells } from "./hooks/useCells";
import { useQuote } from "./hooks/useQuote";
import { useRegions } from "./hooks/useRegions";
import { useTimelineSeries } from "./hooks/useTimelineSeries";
import { I18nProvider } from "./i18n";
import { NO_INSETS, activeBasemap, type Insets } from "./map/basemaps";
import type { LatLon } from "./map/geometry";
import { MapStage } from "./map/MapStage";
import { PointPicker, PointView } from "./map/PointView";
import { RiskLayerView, isSynthetic } from "./map/RiskLayerView";
import { regionSelected, sameIndex, sessionLink } from "./state/link";
import { latestResult, type SessionState } from "./state/session";
import { ViewProvider, useView, type TabId } from "./state/view";

import "./app.css";

type Schemas = components["schemas"];
type Region = Schemas["Region"];

/** Below this width the pieces stack and no card covers the map (see `app.css`). */
export const STACKED_QUERY = "(max-width: 1100px)";

function useMedia(query: string): boolean {
  const subscribe = useCallback(
    (notify: () => void) => {
      if (typeof window.matchMedia !== "function") return () => undefined;
      const media = window.matchMedia(query);
      media.addEventListener("change", notify);
      return () => {
        media.removeEventListener("change", notify);
      };
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => typeof window.matchMedia === "function" && window.matchMedia(query).matches,
    () => false,
  );
}

function sameInsets(a: Insets, b: Insets): boolean {
  return a.top === b.top && a.right === b.right && a.bottom === b.bottom && a.left === b.left;
}

/**
 * What the floating cards cover of the stage, measured, so the map fits a region in the area that
 * is left. Stacked, nothing covers the map.
 */
function useStageInsets(stage: RefObject<HTMLElement | null>, stacked: boolean): Insets {
  const [insets, setInsets] = useState<Insets>(NO_INSETS);
  useEffect(() => {
    const root = stage.current;
    if (root === null || stacked || typeof ResizeObserver !== "function") return;
    const part = (name: string) => root.querySelector<HTMLElement>(`.app__${name}`);
    const parts = [part("top"), part("chat"), part("tabs"), part("timeline")];
    const observer = new ResizeObserver(() => {
      const box = root.getBoundingClientRect();
      const [top, chat, tabs, timeline] = parts.map((element) => element?.getBoundingClientRect());
      const next: Insets = {
        top: top === undefined ? 0 : Math.round(top.bottom - box.top),
        left: chat === undefined ? 0 : Math.round(chat.right - box.left),
        right: tabs === undefined ? 0 : Math.round(box.right - tabs.left),
        bottom: timeline === undefined ? 0 : Math.round(box.bottom - timeline.top),
      };
      setInsets((previous) => (sameInsets(previous, next) ? previous : next));
    });
    observer.observe(root);
    for (const element of parts) if (element !== null) observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [stage, stacked]);
  return stacked ? NO_INSETS : insets;
}

/**
 * The live link: the first region opens with its example, then every tool row of the conversation
 * acts on the view once, whether it arrived live, from a recording or from a restored conversation.
 */
function useLiveLink(session: SessionState, regions: readonly Region[] | undefined): void {
  const { view, dispatch } = useView();
  const applied = useRef<ReadonlySet<string>>(new Set());
  const untouched = view.regionId === null && view.point === null;

  useEffect(() => {
    if (regions === undefined) return;
    const [first] = regions;
    if (untouched && first !== undefined) dispatch(regionSelected(first, config.exampleCovers));
    // A conversation that starts over may reuse call identifiers (a recording played twice).
    if (session.messages.length === 0) applied.current = new Set();
    const step = sessionLink(session, regions, applied.current);
    applied.current = step.applied;
    for (const action of step.actions) dispatch(action);
  }, [session, regions, untouched, dispatch]);
}

/** The backtest of the conversation or of the quote that was computed for the index in view. */
function backtestInView(
  session: SessionState,
  quote: Schemas["QuoteView"] | null,
  index: Schemas["IndexDefinition"] | null,
): Schemas["BacktestResult"] | null {
  const candidates = [
    readBacktest(latestResult(session, "backtest_index")),
    readPricedBacktest(latestResult(session, "price_cover")),
    quote?.priced.backtest ?? null,
  ];
  return (
    candidates.find(
      (candidate) =>
        candidate !== null && candidate !== undefined && sameIndex(candidate.cover.index, index),
    ) ?? null
  );
}

/** The application: the map as the stage, with the top row, the conversation, the tabs and the
 * season timeline on it. Below 1100 pixels the same pieces stack in document order. */
export function Shell() {
  const { theme, setTheme } = useTheme();
  const { view, dispatch } = useView();
  const regions = useRegions();
  const { session, card } = useConversationCard();
  useLiveLink(session, regions.data);

  const stage = useRef<HTMLElement | null>(null);
  const stacked = useMedia(STACKED_QUERY);
  const insets = useStageInsets(stage, stacked);

  const [mapPoint, setMapPoint] = useState<LatLon | null>(null);
  const clearMapPoint = useCallback(() => {
    setMapPoint(null);
  }, []);

  // A quote opened from the approval queue is shown until the conversation pins another one.
  const [opened, setOpened] = useState<{ quoteId: string; over: string | null } | null>(null);
  const openedQuoteId = opened !== null && opened.over === view.quoteId ? opened.quoteId : null;

  const region = regions.data?.find((item) => item.region_id === view.regionId) ?? null;
  const outside = view.point !== null && view.regionId === null;
  const basemap = activeBasemap(theme, view.basemap);
  const replaying = session.mode === "replay";

  const cells = useCells(
    view.regionId,
    view.index === null
      ? null
      : {
          metric: view.metric,
          index: view.index,
          season: view.metric === "season_anomaly" ? view.season : null,
        },
  );
  const cellsWanted = view.regionId !== null && view.index !== null;
  // While another region loads, the query still holds the previous one's grid: it is not this
  // region's risk, so it is not drawn. Within a region the previous grid stays (season changes).
  const grid = cells.data?.region_id === view.regionId ? cells.data : null;

  const quoteId = openedQuoteId ?? view.quoteId;
  // A recorded quote does not exist in the workspace: it is read from the recording instead.
  const quote = useQuote(replaying && openedQuoteId === null ? null : quoteId);
  const recorded =
    replaying && openedQuoteId === null
      ? readRecordedQuote(latestResult(session, "price_cover"))
      : null;

  const backtest = backtestInView(session, quote.data ?? null, view.index);
  const timeline = useTimelineSeries({
    backtest,
    // Outside the showcase regions there is no cube to read seasons from.
    point: outside ? null : view.point,
    index: view.index,
    limitCents: view.limitCents,
  });

  const approvals = useApprovals();
  // The conversation only knows that an approval was asked for; the queue knows when a person has
  // decided it, and from then on the conversation stops saying that one waits.
  const waiting = session.pendingApproval;
  const decided =
    waiting !== null &&
    (approvals.data ?? []).some(
      (approval) => approval.approval_id === waiting.approval_id && approval.status !== "pending",
    );
  const source = latestResult(session, "get_weather_history")?.source;
  const datasetSource = typeof source === "string" ? source : null;

  const selectSeason = useCallback(
    (season: number | null) => {
      dispatch({ type: "season_selected", season });
    },
    [dispatch],
  );

  const selectRegion = (regionId: string) => {
    const next = regions.data?.find((item) => item.region_id === regionId);
    if (next !== undefined) dispatch(regionSelected(next, config.exampleCovers));
  };

  const startOver = () => {
    card.onReset();
    setMapPoint(null);
    setOpened(null);
    const home = region ?? regions.data?.[0];
    if (home !== undefined) dispatch(regionSelected(home, config.exampleCovers));
    dispatch({ type: "tab_opened", tab: "risk" });
  };

  const openTab = (tab: TabId) => {
    dispatch({ type: "tab_opened", tab });
  };

  const panels = {
    risk: (
      <RiskTab
        grid={grid}
        point={view.point}
        season={view.metric === "season_anomaly" ? view.season : null}
        status={cells.isError ? "failed" : cellsWanted && grid === null ? "loading" : undefined}
        onRetry={() => {
          void cells.refetch();
        }}
        theme={theme}
        basemap={basemap}
        synthetic={isSynthetic(region, datasetSource)}
      />
    ),
    history: (
      <HistoryTab
        backtest={backtest}
        season={view.season}
        onSelectSeason={selectSeason}
        highlight={view.tab === "history" ? view.highlight : null}
      />
    ),
    quote: (
      <QuoteTab
        quote={quote.data ?? null}
        recorded={recorded}
        status={
          quote.isError ? "failed" : quoteId !== null && quote.isLoading ? "loading" : undefined
        }
        onRetry={() => {
          void quote.refetch();
        }}
        highlight={view.tab === "quote" ? view.highlight : null}
      />
    ),
    approvals: (
      <ApprovalsTab
        onOpenQuote={(id) => {
          setOpened(id === view.quoteId ? null : { quoteId: id, over: view.quoteId });
          openTab("quote");
        }}
      />
    ),
  };

  return (
    <main
      ref={stage}
      className="app"
      data-layout={stacked ? "stacked" : "stage"}
      data-wide={view.tab === "risk" ? undefined : ""}
    >
      <TopBar
        className="app__top"
        regions={regions.data ?? []}
        regionId={view.regionId}
        outside={outside}
        onRegion={selectRegion}
        basemap={basemap}
        onBasemap={(next) => {
          dispatch({ type: "basemap_set", basemap: next });
        }}
        render={view.render}
        onRender={(next) => {
          dispatch({ type: "render_set", render: next });
        }}
        theme={theme}
        onTheme={setTheme}
      />
      <div className="app__map">
        <MapStage region={region} basemap={basemap} theme={theme} insets={insets}>
          <RiskLayerView
            grid={grid}
            region={region}
            point={view.point}
            render={view.render}
            theme={theme}
            basemap={basemap}
            datasetSource={datasetSource}
          />
          <PointView point={outside ? view.point : null} />
          <PointPicker onPick={setMapPoint} />
        </MapStage>
      </div>
      <SeasonTimeline
        className="app__timeline"
        seasons={timeline.seasons}
        index={view.index}
        selected={view.season}
        suggested={grid?.suggested_season ?? null}
        onSelect={selectSeason}
        status={outside || view.index === null ? "ready" : timeline.status}
        onRetry={timeline.retry}
        basemap={config.basemaps[basemap]}
      />
      <TabsCard
        className="app__tabs"
        tab={view.tab}
        onTab={openTab}
        panels={panels}
        badges={{ approvals: pendingCount(approvals.data) }}
      />
      <ConversationCard
        {...card}
        session={decided ? { ...session, pendingApproval: null } : session}
        className="app__chat"
        onReset={startOver}
        mapPoint={mapPoint}
        onClearMapPoint={clearMapPoint}
      />
    </main>
  );
}

export function App() {
  const [queryClient] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ViewProvider>
          <Shell />
        </ViewProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
