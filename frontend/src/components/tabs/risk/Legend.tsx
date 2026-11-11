import type { components } from "../../../api/schema";
import type { BasemapId } from "../../../config";
import { MAP_PAINT, type Theme } from "../../../design/theme";
import { translate, useI18n } from "../../../i18n";
import { classCount, rampFor, rgbaCss } from "../../../map/ramps";
import { cellValueText } from "./cellText";

type CellGrid = components["schemas"]["CellGrid"];

interface LegendProps {
  metric: CellGrid["metric"];
  /** `CellGrid.breaks`: the class edges, `n + 1` for `n` classes. */
  breaks: readonly number[];
  theme: Theme;
  basemap: BasemapId;
}

/**
 * The legend of the risk layer: one swatch per class of the API, labelled with the two edges of
 * the class. Nothing is classified here; the edges are `CellGrid.breaks` as they came.
 */
export function Legend({ metric, breaks, theme, basemap }: LegendProps) {
  const { locale } = useI18n();
  const paint = MAP_PAINT[theme];
  const ramp = rampFor(metric, paint, breaks);
  const classes = classCount(breaks);
  if (classes === 0) return null;

  // One more decimal when two edges would otherwise read the same.
  const whole = breaks.map((edge) => cellValueText(edge, metric, locale));
  const digits = new Set(whole).size < new Set(breaks).size ? 1 : 0;
  const edge = (at: number) => cellValueText(breaks[at] ?? 0, metric, locale, digits);

  return (
    <div className="legend" data-metric={metric}>
      <p className="legend__title">
        {translate(
          locale,
          metric === "trigger_frequency" ? "risk.legend.frequency" : "risk.legend.anomaly",
        )}
      </p>
      <ol className="legend__classes">
        {ramp.map((colour, at) => (
          <li key={at} className="legend__class">
            <span
              className="legend__swatch"
              aria-hidden="true"
              style={{
                background: `linear-gradient(${rgbaCss(colour)}, ${rgbaCss(colour)}), ${paint.swatchBase[basemap]}`,
              }}
            />
            <span className="legend__label num">
              {breaks[at] === breaks[at + 1]
                ? edge(at)
                : translate(locale, "risk.legend.class", { low: edge(at), high: edge(at + 1) })}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
