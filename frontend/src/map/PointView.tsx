import { useEffect } from "react";
import { useMap, useMapEvents } from "react-leaflet";

import type { LatLon } from "./geometry";

/** Close enough to read one grid cell and its surroundings. */
const POINT_ZOOM = 9;

interface PointViewProps {
  /** The point to bring into view; nothing moves while it is `null`. */
  point: LatLon | null;
}

/**
 * Centres the map on a point that no showcase region contains. A point inside a region needs no
 * help: the stage already fits that region's cube.
 */
export function PointView({ point }: PointViewProps) {
  const map = useMap();
  const lat = point?.lat ?? null;
  const lon = point?.lon ?? null;
  useEffect(() => {
    if (lat === null || lon === null) return;
    map.setView([lat, lon], Math.min(POINT_ZOOM, map.getMaxZoom()), { animate: false });
  }, [map, lat, lon]);
  return null;
}

interface PointPickerProps {
  onPick: (point: LatLon) => void;
}

/** Reports the place the visitor clicked or tapped, to four decimals (about eleven metres). */
export function PointPicker({ onPick }: PointPickerProps) {
  useMapEvents({
    click: (event) => {
      onPick({
        lat: Math.round(event.latlng.lat * 1e4) / 1e4,
        lon: Math.round(event.latlng.lng * 1e4) / 1e4,
      });
    },
  });
  return null;
}
