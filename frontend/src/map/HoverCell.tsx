import { Polyline, Rectangle, Tooltip } from "react-leaflet";

import type { MapPaint } from "../design/theme";
import type { LatLngBoundsTuple } from "./basemaps";
import type { LatLon } from "./geometry";

interface HoverCellProps {
  /** The outline of the cell under the pointer. */
  bounds: LatLngBoundsTuple;
  /** The centre of that cell: where the measured leg ends. */
  centre: LatLon;
  /** The insured point the leg starts from; without one there is no leg. */
  from: LatLon | null;
  /** The coordinates of the cell centre, formatted. */
  title: string;
  /** What the cell's value says, formatted from the API's value. */
  value: string;
  /** The length of the leg, formatted, when there is a leg. */
  distance: string | null;
  /** The sentence that carries the distance in the cell's card ("12.4 km from the farm"). */
  distanceLine: string | null;
  paint: MapPaint;
}

/**
 * The cell under the pointer: its outline, a card with its value, and a dashed leg measured from
 * the insured point with its length at the middle.
 */
export function HoverCell({
  bounds,
  centre,
  from,
  title,
  value,
  distance,
  distanceLine,
  paint,
}: HoverCellProps) {
  const leg: [number, number][] | null =
    from === null
      ? null
      : [
          [from.lat, from.lon],
          [centre.lat, centre.lon],
        ];
  return (
    <>
      {leg !== null && (
        <>
          <Polyline
            positions={leg}
            interactive={false}
            pathOptions={{ color: paint.halo, weight: 4.5, lineCap: "round" }}
          />
          <Polyline
            positions={leg}
            interactive={false}
            className="map-leg"
            pathOptions={{ color: paint.marker, weight: 1.8, dashArray: "6 5", lineCap: "butt" }}
          >
            {distance !== null && (
              <Tooltip permanent direction="center" className="map-leg-label">
                {distance}
              </Tooltip>
            )}
          </Polyline>
        </>
      )}
      <Rectangle
        bounds={bounds}
        interactive={false}
        pathOptions={{ color: paint.halo, weight: 4, fill: false, lineJoin: "miter" }}
      />
      <Rectangle
        bounds={bounds}
        interactive={false}
        className="map-hover-cell"
        pathOptions={{ color: paint.label, weight: 1.6, fill: false, lineJoin: "miter" }}
      >
        <Tooltip permanent direction="top" offset={[0, -10]} className="map-tip">
          <strong className="map-tip__title">{title}</strong>
          <span className="map-tip__line">{value}</span>
          {distanceLine !== null && <span className="map-tip__line">{distanceLine}</span>}
        </Tooltip>
      </Rectangle>
    </>
  );
}
