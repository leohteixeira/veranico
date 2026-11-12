import { useEffect, useRef, useState, type PointerEvent } from "react";

import type { components } from "../../api/schema";
import "./timeline.css";

type SeasonResult = components["schemas"]["SeasonResult"];

/** Heights in pixels, as in the approved preview: the plot, then the band of decade labels. */
const PLOT_HEIGHT = 46;
const LABEL_BAND = 15;
const DEFAULT_WIDTH = 640;

/** A season pays when the API says so: a payout above zero. No payout from the API, no mark. */
export function pays(season: SeasonResult): boolean {
  return season.payout !== null && season.payout.amount_cents > 0;
}

interface TimelineBarsProps {
  seasons: readonly SeasonResult[];
  /** The trigger of the index, in the unit of the index values: drawn as a dashed line. */
  trigger: number;
  /** The selected season; `null` shows all seasons at full strength. */
  selected: number | null;
  /** Called while the pointer drags over the bars. */
  onSelect: (season: number) => void;
  /** What a bar says on hover, formatted by the caller. */
  describe: (season: SeasonResult) => string;
}

/**
 * One bar per season of the insured point. Payout seasons take the payout colour and a mark under
 * the baseline, so the difference does not rest on colour alone. Bar heights are a drawing of the
 * API's index values; nothing here computes a figure.
 */
export function TimelineBars({
  seasons,
  trigger,
  selected,
  onSelect,
  describe,
}: TimelineBarsProps) {
  const frame = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const dragging = useRef(false);

  useEffect(() => {
    const element = frame.current;
    if (element === null || typeof ResizeObserver !== "function") return;
    const observer = new ResizeObserver(([entry]) => {
      const next = entry?.contentRect.width ?? 0;
      if (next > 0) setWidth(next);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  const count = seasons.length;
  if (count === 0) return <div ref={frame} className="timeline-bars" />;

  const slot = width / count;
  const barWidth = Math.max(1.5, Math.min(12, slot - 1.5));
  const top = Math.max(trigger, ...seasons.map((season) => season.index_value));
  const y = (value: number) =>
    top <= 0 ? PLOT_HEIGHT : PLOT_HEIGHT - (value / top) * (PLOT_HEIGHT - 6);
  const every = width < 420 ? 20 : 10;
  const selectedAt = selected === null ? -1 : seasons.findIndex((item) => item.season === selected);

  const seasonAt = (event: PointerEvent<SVGSVGElement>): number | null => {
    const left = event.currentTarget.getBoundingClientRect().left;
    const at = Math.floor((event.clientX - left) / slot);
    return seasons[Math.max(0, Math.min(count - 1, at))]?.season ?? null;
  };
  const select = (event: PointerEvent<SVGSVGElement>) => {
    const season = seasonAt(event);
    if (season !== null && season !== selected) onSelect(season);
  };

  return (
    <div ref={frame} className="timeline-bars">
      <svg
        viewBox={`0 0 ${width} ${PLOT_HEIGHT + LABEL_BAND}`}
        width={width}
        height={PLOT_HEIGHT + LABEL_BAND}
        aria-hidden="true"
        onPointerDown={(event) => {
          dragging.current = true;
          if (typeof event.currentTarget.setPointerCapture === "function") {
            event.currentTarget.setPointerCapture(event.pointerId);
          }
          select(event);
        }}
        onPointerMove={(event) => {
          if (dragging.current) select(event);
        }}
        onPointerUp={() => {
          dragging.current = false;
        }}
        onPointerCancel={() => {
          dragging.current = false;
        }}
      >
        {seasons.map((season, at) => {
          const x = at * slot + (slot - barWidth) / 2;
          const barTop = y(season.index_value);
          const paying = pays(season);
          return (
            <g key={season.season} data-season={season.season}>
              <rect
                className={
                  paying ? "timeline-bars__bar timeline-bars__bar--pay" : "timeline-bars__bar"
                }
                x={x}
                y={barTop}
                width={barWidth}
                height={Math.max(0, PLOT_HEIGHT - barTop)}
                rx={Math.min(2, barWidth / 2)}
                opacity={selectedAt >= 0 && selectedAt !== at ? 0.5 : 1}
              />
              {paying && (
                <rect
                  className="timeline-bars__mark"
                  x={x}
                  y={PLOT_HEIGHT + 1.5}
                  width={barWidth}
                  height={2}
                  rx={1}
                />
              )}
              {/* The whole column answers the pointer, not only the bar. */}
              <rect
                className="timeline-bars__hit"
                x={at * slot}
                y={0}
                width={slot}
                height={PLOT_HEIGHT}
              >
                <title>{describe(season)}</title>
              </rect>
            </g>
          );
        })}
        <line
          className="timeline-bars__trigger"
          x1={0}
          x2={width}
          y1={y(trigger)}
          y2={y(trigger)}
        />
        {seasons.map((season, at) =>
          season.season % every === 0 ? (
            <text
              key={season.season}
              className="timeline-bars__decade"
              x={Math.max(13, Math.min(width - 13, at * slot + slot / 2))}
              y={PLOT_HEIGHT + 13}
              textAnchor="middle"
            >
              {season.season}
            </text>
          ) : null,
        )}
        {selectedAt >= 0 && (
          <line
            className="timeline-bars__cursor"
            x1={selectedAt * slot + slot / 2}
            x2={selectedAt * slot + slot / 2}
            y1={0}
            y2={PLOT_HEIGHT}
          />
        )}
      </svg>
    </div>
  );
}
