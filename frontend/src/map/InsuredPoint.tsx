import { CircleMarker, Rectangle, Tooltip } from "react-leaflet";

import type { MapPaint } from "../design/theme";
import type { LatLngBoundsTuple } from "./basemaps";
import type { LatLon } from "./geometry";

interface InsuredPointProps {
  point: LatLon;
  /** The grid cell the point is priced on, outlined; `null` when it is not known. */
  cell: LatLngBoundsTuple | null;
  /** The word on the marker ("Farm"). */
  label: string;
  paint: MapPaint;
}

/**
 * The insured point: a ring with a dot and its label, and the outline of the grid cell the cover
 * is priced on. Each stroke sits on a halo so it reads over any basemap and any risk colour.
 */
export function InsuredPoint({ point, cell, label, paint }: InsuredPointProps) {
  const centre: [number, number] = [point.lat, point.lon];
  return (
    <>
      {cell !== null && (
        <>
          <Rectangle
            bounds={cell}
            interactive={false}
            pathOptions={{ color: paint.halo, weight: 5, fill: false, lineJoin: "miter" }}
          />
          <Rectangle
            bounds={cell}
            interactive={false}
            className="map-insured-cell"
            pathOptions={{ color: paint.marker, weight: 2, fill: false, lineJoin: "miter" }}
          />
        </>
      )}
      <CircleMarker
        center={centre}
        radius={11.5}
        interactive={false}
        pathOptions={{ stroke: false, fillColor: paint.halo, fillOpacity: 1 }}
      />
      <CircleMarker
        center={centre}
        radius={9}
        interactive={false}
        className="map-insured-point"
        pathOptions={{ color: paint.marker, weight: 2.5, fill: false }}
      >
        <Tooltip permanent direction="right" offset={[12, -12]} className="map-farm-label">
          {label}
        </Tooltip>
      </CircleMarker>
      <CircleMarker
        center={centre}
        radius={3}
        interactive={false}
        pathOptions={{ stroke: false, fillColor: paint.marker, fillOpacity: 1 }}
      />
    </>
  );
}
