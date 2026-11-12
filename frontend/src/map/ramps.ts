import type { components } from "../api/schema";
import type { MapPaint, Rgba } from "../design/theme";

type Metric = components["schemas"]["CellGrid"]["metric"];

/**
 * `CellGrid.breaks` are the class EDGES, both ends included: `n + 1` edges for `n` classes, from
 * the lowest value of the grid to the highest (frequency) or symmetric around zero (anomaly).
 * `[v, v]` when every cell is equal; `[]` when no cell has a value. Every value lies between the
 * first edge and the last, so there is no class outside them.
 */
export function classCount(breaks: readonly number[]): number {
  return Math.max(0, breaks.length - 1);
}

/**
 * The class of a value: class `k` runs from edge `k` up to, not including, edge `k + 1`; the last
 * class also holds the last edge, so the maximum belongs to it.
 */
export function classOf(value: number, breaks: readonly number[]): number {
  const classes = classCount(breaks);
  if (classes === 0) return 0;
  let index = 0;
  while (index < classes - 1 && value >= (breaks[index + 1] ?? Infinity)) index += 1;
  return index;
}

function mix(from: Rgba, to: Rgba, share: number): Rgba {
  return [
    from[0] + (to[0] - from[0]) * share,
    from[1] + (to[1] - from[1]) * share,
    from[2] + (to[2] - from[2]) * share,
    from[3] + (to[3] - from[3]) * share,
  ];
}

/** The colour at a position along a list of stops, `0` at the first and `1` at the last. */
function along(stops: readonly Rgba[], share: number): Rgba {
  const first = stops[0];
  if (first === undefined) return [0, 0, 0, 0];
  const at = Math.max(0, Math.min(1, share)) * (stops.length - 1);
  const low = Math.floor(at);
  return mix(stops[low] ?? first, stops[Math.min(stops.length - 1, low + 1)] ?? first, at - low);
}

/** The stops of the paint resampled to one colour per class, from the first stop to the last. */
export function sampleRamp(stops: readonly Rgba[], classes: number): Rgba[] {
  if (classes <= 0) return [];
  if (classes === 1) return [along(stops, 0.5)];
  return Array.from({ length: classes }, (_, index) => along(stops, index / (classes - 1)));
}

/**
 * One colour per class of the API: sequential for the trigger frequency; diverging, dry to wet,
 * for a season's anomaly. The legend has exactly these swatches.
 */
export function rampFor(metric: Metric, paint: MapPaint, breaks: readonly number[]): Rgba[] {
  const stops = metric === "trigger_frequency" ? paint.sequential : paint.diverging;
  return sampleRamp(stops, classCount(breaks));
}

/** Where a value sits on the class scale: class `k` runs from `k` to `k + 1`. */
function position(value: number, breaks: readonly number[]): number {
  const index = classOf(value, breaks);
  const low = breaks[index];
  const high = breaks[index + 1];
  if (low === undefined || high === undefined || high === low) return index + 0.5;
  return index + Math.max(0, Math.min(1, (value - low) / (high - low)));
}

/**
 * The continuous colour of a value: the class colours sit at the middle of their classes and the
 * surface blends between them. `ramp` has one colour per class.
 */
export function colourAt(value: number, breaks: readonly number[], ramp: readonly Rgba[]): Rgba {
  const first = ramp[0];
  if (first === undefined) return [0, 0, 0, 0];
  const at = Math.max(0, Math.min(ramp.length - 1, position(value, breaks) - 0.5));
  const low = Math.floor(at);
  return mix(ramp[low] ?? first, ramp[Math.min(ramp.length - 1, low + 1)] ?? first, at - low);
}

/** The flat colour of a value's class, for the cells view and the legend. */
export function classColour(value: number, breaks: readonly number[], ramp: readonly Rgba[]): Rgba {
  return ramp[Math.min(ramp.length - 1, classOf(value, breaks))] ?? [0, 0, 0, 0];
}

export function rgbaCss(colour: Rgba): string {
  const [red, green, blue, alpha] = colour;
  return `rgba(${Math.round(red)},${Math.round(green)},${Math.round(blue)},${alpha.toFixed(3)})`;
}
