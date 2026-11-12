import type { components } from "../../../api/schema";
import type { BasemapId } from "../../../config";
import { MAP_PAINT, type Theme } from "../../../design/theme";
import { translate, useI18n } from "../../../i18n";
import { valueAt, type CellRef } from "../../../map/geometry";
import { classColour, rampFor, rgbaCss } from "../../../map/ramps";
import { cellValueText } from "./cellText";

type CellGrid = components["schemas"]["CellGrid"];

interface NeighbourhoodProps {
  grid: CellGrid;
  /** The insured cell: the centre of the three by three. */
  cell: CellRef;
  theme: Theme;
  basemap: BasemapId;
}

const OFFSETS = [-1, 0, 1] as const;

/**
 * The insured cell and its eight neighbours as the API returned them, north at the top: each cell
 * with the colour of its class and its value in words. The centre is marked by a frame and a name.
 */
export function Neighbourhood({ grid, cell, theme, basemap }: NeighbourhoodProps) {
  const { locale } = useI18n();
  const paint = MAP_PAINT[theme];
  const ramp = rampFor(grid.metric, paint, grid.breaks);

  return (
    <table className="hood" aria-label={translate(locale, "risk.neighbourhood")}>
      <tbody>
        {OFFSETS.map((dRow) => (
          <tr key={dRow}>
            {OFFSETS.map((dCol) => {
              const row = cell.row + dRow;
              const col = cell.col + dCol;
              const inside = row >= 0 && col >= 0 && row < grid.ny && col < grid.nx;
              const insured = dRow === 0 && dCol === 0;
              const value = inside ? valueAt(grid, row, col) : null;
              return (
                <td
                  key={dCol}
                  className="hood__cell"
                  data-insured={insured ? "true" : undefined}
                  data-inside={inside ? "true" : "false"}
                  style={
                    value === null
                      ? undefined
                      : {
                          background: `linear-gradient(${rgbaCss(classColour(value, grid.breaks, ramp))}, ${rgbaCss(classColour(value, grid.breaks, ramp))}), ${paint.swatchBase[basemap]}`,
                        }
                  }
                >
                  <span className="hood__value num">
                    {!inside
                      ? translate(locale, "risk.neighbourhood.outside")
                      : value === null
                        ? translate(locale, "risk.cell.no_value")
                        : cellValueText(value, grid.metric, locale)}
                  </span>
                  {insured && (
                    <span className="sr-only">
                      {" "}
                      ({translate(locale, "risk.neighbourhood.insured")})
                    </span>
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
