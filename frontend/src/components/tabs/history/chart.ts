import { useEffect, useRef, useState, type RefObject } from "react";

import type { components } from "../../../api/schema";

export type SeasonResult = components["schemas"]["SeasonResult"];

/** Shared by the two panels so their plots line up on the same time axis. */
export const Y_AXIS_WIDTH = 62;
export const CHART_MARGIN = { top: 8, right: 4, bottom: 0, left: 0 } as const;
/** Links the hover of the two panels (Recharts `syncId`). */
export const SYNC_ID = "history-seasons";
const DEFAULT_WIDTH = 312;

/** The width of a chart's frame; a fixed default where it cannot be measured (tests). */
export function useChartWidth(): [RefObject<HTMLDivElement | null>, number] {
  const frame = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  useEffect(() => {
    const element = frame.current;
    if (element === null || typeof ResizeObserver !== "function") return;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.floor(entry?.contentRect.width ?? 0);
      if (next > 0) setWidth(next);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);
  return [frame, width];
}

/**
 * The season of the column under a pointer position, so the whole height of a column selects its
 * season, not only its bar. Both panels lay their columns out the same way: equal slots across the
 * plot, which starts after the value axis.
 */
export function seasonAtX(
  seasons: readonly SeasonResult[],
  frame: HTMLElement,
  clientX: number,
): number | null {
  const box = frame.getBoundingClientRect();
  const left = Y_AXIS_WIDTH + CHART_MARGIN.left;
  const plot = box.width - left - CHART_MARGIN.right;
  const x = clientX - box.left - left;
  if (plot <= 0 || x < 0 || x >= plot || seasons.length === 0) return null;
  return seasons[Math.floor((x / plot) * seasons.length)]?.season ?? null;
}

/** The seasons that get a label on the time axis: the decades. */
export function decadeTicks(seasons: readonly SeasonResult[]): number[] {
  return seasons.map((item) => item.season).filter((season) => season % 10 === 0);
}

/** A season pays when the API says so: a payout above zero. */
export function pays(season: SeasonResult): boolean {
  return season.payout !== null && season.payout.amount_cents > 0;
}

export function barFill(season: SeasonResult): string {
  return pays(season) ? "var(--pay)" : "var(--bar)";
}

/** Full strength for every bar, or for the selected one only when a season is selected. */
export function barOpacity(season: SeasonResult, selected: number | null): number {
  return selected === null || selected === season.season ? 1 : 0.45;
}
