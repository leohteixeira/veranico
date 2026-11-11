import {
  createContext,
  createElement,
  useContext,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";

import type { components } from "../api/schema";
import type { BasemapId } from "../config";

type Schemas = components["schemas"];

export type Metric = Schemas["CellGrid"]["metric"];
export type RenderMode = "surface" | "cells";
export type TabId = "risk" | "history" | "quote" | "approvals";

export interface InsuredPoint {
  lat: number;
  lon: number;
  label: string | null;
}

/** What the screen is showing. One store serves the map, the timeline, the tabs and the top row. */
export interface ViewState {
  /** The active showcase region, or `null` while regions load or the point is outside them. */
  regionId: string | null;
  point: InsuredPoint | null;
  /** The index definition the risk layer and the timeline are drawn for. */
  index: Schemas["IndexDefinition"] | null;
  /** The limit payouts are shown for, in centavos, as the API or the example gave it. */
  limitCents: number | null;
  /** The quote whose index definition is pinned to the region, once one is priced. */
  quoteId: string | null;
  metric: Metric;
  /** The selected season; `null` shows all seasons. Shared by timeline, map and History chart. */
  season: number | null;
  render: RenderMode;
  /** An explicit basemap choice; `null` follows the theme. */
  basemap: BasemapId | null;
  tab: TabId;
  /** The field a figure link asked a tab to highlight. */
  highlight: string | null;
}

export type ViewAction =
  | {
      type: "region_selected";
      regionId: string;
      point: InsuredPoint | null;
      index: Schemas["IndexDefinition"] | null;
      limitCents: number | null;
    }
  | { type: "point_set"; point: InsuredPoint; regionId: string | null }
  | { type: "index_set"; index: Schemas["IndexDefinition"]; limitCents: number | null }
  | { type: "quote_pinned"; quoteId: string; index: Schemas["IndexDefinition"]; limitCents: number }
  | { type: "season_selected"; season: number | null }
  | { type: "render_set"; render: RenderMode }
  | { type: "basemap_set"; basemap: BasemapId }
  | { type: "tab_opened"; tab: TabId; highlight?: string | null };

export const initialView: ViewState = {
  regionId: null,
  point: null,
  index: null,
  limitCents: null,
  quoteId: null,
  metric: "trigger_frequency",
  season: null,
  render: "surface",
  basemap: null,
  tab: "risk",
  highlight: null,
};

export function viewReducer(state: ViewState, action: ViewAction): ViewState {
  switch (action.type) {
    case "region_selected":
      // Another region starts from its own example: no quote, no season.
      return {
        ...state,
        regionId: action.regionId,
        point: action.point,
        index: action.index,
        limitCents: action.limitCents,
        quoteId: null,
        metric: "trigger_frequency",
        season: null,
      };
    case "point_set":
      return { ...state, point: action.point, regionId: action.regionId };
    case "index_set":
      // A new index definition has its own seasons: leave the season view.
      return {
        ...state,
        index: action.index,
        limitCents: action.limitCents,
        metric: "trigger_frequency",
        season: null,
      };
    case "quote_pinned":
      return {
        ...state,
        quoteId: action.quoteId,
        index: action.index,
        limitCents: action.limitCents,
      };
    case "season_selected":
      // Selecting a season is entering the season view; clearing it returns to all seasons.
      return {
        ...state,
        season: action.season,
        metric: action.season === null ? "trigger_frequency" : "season_anomaly",
      };
    case "render_set":
      return { ...state, render: action.render };
    case "basemap_set":
      return { ...state, basemap: action.basemap };
    case "tab_opened":
      return { ...state, tab: action.tab, highlight: action.highlight ?? null };
  }
}

interface ViewStore {
  view: ViewState;
  dispatch: Dispatch<ViewAction>;
}

const ViewContext = createContext<ViewStore | null>(null);

interface ViewProviderProps {
  initial?: ViewState;
  children: ReactNode;
}

export function ViewProvider({ initial = initialView, children }: ViewProviderProps) {
  const [view, dispatch] = useReducer(viewReducer, initial);
  return createElement(ViewContext.Provider, { value: { view, dispatch } }, children);
}

export function useView(): ViewStore {
  const store = useContext(ViewContext);
  if (store === null) throw new Error("useView needs a ViewProvider above it");
  return store;
}
