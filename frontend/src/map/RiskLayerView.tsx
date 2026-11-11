import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMap, useMapEvents } from "react-leaflet";

import type { components } from "../api/schema";
import type { BasemapId } from "../config";
import { MAP_PAINT, type Theme } from "../design/theme";
import { useI18n, type Locale } from "../i18n";
import { formatFraction, formatKm, formatNumber } from "../i18n/format";
import { HoverCell } from "./HoverCell";
import { InsuredPoint } from "./InsuredPoint";
import { RiskLayer, type RenderMode } from "./RiskLayer";
import {
  cellAt,
  cellBounds,
  cellCentre,
  distanceKm,
  pointCell,
  valueAt,
  type CellRef,
  type LatLon,
} from "./geometry";

type Schemas = components["schemas"];
type CellGrid = Schemas["CellGrid"];
/**
 * `DatasetRef.source` of the contracts. It reaches the interface inside a tool result, which the
 * OpenAPI document types as a free object, so it is a string here and only `synthetic` is read.
 */
type DatasetSource = string;

/** The pane of the risk canvas: over the tiles, under the vector layers. */
export const RISK_PANE = "risk";

/**
 * Whether the weather on screen is synthetic. The label comes from the API and from nowhere else:
 * a region says so itself, and a dataset the agent reports says so in its source.
 */
export function isSynthetic(
  region: Pick<Schemas["Region"], "synthetic"> | null,
  datasetSource: DatasetSource | null,
): boolean {
  return region?.synthetic === true || datasetSource === "synthetic";
}

type Translate = ReturnType<typeof useI18n>["t"];

/** A cell centre as text: two decimals, with the hemisphere. */
function coordinates(point: LatLon, locale: Locale, t: Translate): string {
  const degrees = (value: number) =>
    formatNumber(Math.abs(value), locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const lat = `${degrees(point.lat)}° ${t(point.lat < 0 ? "compass.south" : "compass.north")}`;
  const lon = `${degrees(point.lon)}° ${t(point.lon < 0 ? "compass.west" : "compass.east")}`;
  return `${lat}, ${lon}`;
}

function sameCell(a: CellRef | null, b: CellRef | null): boolean {
  return a !== null && b !== null && a.row === b.row && a.col === b.col;
}

interface RiskLayerViewProps {
  /** The per-cell metric of the region in view; `null` while it loads or when there is none. */
  grid: CellGrid | null;
  /** The showcase region in view; `null` when the insured point lies outside all of them. */
  region: Schemas["Region"] | null;
  point: LatLon | null;
  render: RenderMode;
  theme: Theme;
  basemap: BasemapId;
  /** The source of the dataset the agent reported, when there is one. */
  datasetSource?: DatasetSource | null;
  /** Told which cell is under the pointer or was tapped, and when there is none. */
  onActiveCell?: (cell: CellRef | null) => void;
}

/**
 * The risk on the map: the canvas layer, the insured point with its cell, the cell under the
 * pointer with its measured leg, and the notes that qualify what is drawn. A tap selects a cell
 * the way a pointer hovers it, and the selection stays until another tap.
 */
export function RiskLayerView({
  grid,
  region,
  point,
  render,
  theme,
  basemap,
  datasetSource = null,
  onActiveCell,
}: RiskLayerViewProps) {
  const map = useMap();
  const { t, locale } = useI18n();
  const paint = MAP_PAINT[theme];
  const layer = useRef<RiskLayer | null>(null);
  const [hovered, setHovered] = useState<CellRef | null>(null);
  const [selected, setSelected] = useState<CellRef | null>(null);

  // One canvas layer for the life of the map; later renders only hand it the new state.
  useEffect(() => {
    const pane = map.getPane(RISK_PANE) ?? map.createPane(RISK_PANE);
    pane.style.zIndex = "350";
    pane.style.pointerEvents = "none";
    // Created empty: the effect below runs next and gives it the state to draw.
    const created = new RiskLayer(
      { grid: null, render: "surface", paint: MAP_PAINT.light, basemap: "relief" },
      { pane: RISK_PANE },
    );
    created.addTo(map);
    layer.current = created;
    return () => {
      created.remove();
      layer.current = null;
    };
  }, [map]);

  useEffect(() => {
    layer.current?.setState({ grid, render, paint, basemap });
  }, [grid, render, paint, basemap]);

  useMapEvents({
    mousemove: (event) => {
      const next = grid === null ? null : cellAt(grid, event.latlng.lat, event.latlng.lng);
      setHovered((previous) => (sameCell(previous, next) ? previous : next));
    },
    mouseout: () => {
      setHovered(null);
    },
    click: (event) => {
      const next = grid === null ? null : cellAt(grid, event.latlng.lat, event.latlng.lng);
      setSelected((previous) => (sameCell(previous, next) ? null : next));
    },
  });

  // A cell of another grid shape means nothing: keep only what the current grid contains.
  const within = (cell: CellRef | null) =>
    cell !== null && grid !== null && cell.row < grid.ny && cell.col < grid.nx ? cell : null;
  const active = within(hovered) ?? within(selected);
  const activeRow = active?.row ?? null;
  const activeCol = active?.col ?? null;

  useEffect(() => {
    onActiveCell?.(
      activeRow === null || activeCol === null ? null : { row: activeRow, col: activeCol },
    );
  }, [activeRow, activeCol, onActiveCell]);

  const insured = grid !== null && point !== null ? cellAt(grid, point.lat, point.lon) : null;
  const outsideShowcase = point !== null && region === null;
  const insuredBounds = useMemo(() => {
    if (point === null) return null;
    if (grid !== null && insured !== null) return cellBounds(grid, insured.row, insured.col);
    return outsideShowcase ? pointCell(point) : null;
  }, [grid, insured, outsideShowcase, point]);

  let hover = null;
  if (grid !== null && active !== null && !sameCell(active, insured)) {
    const centre = cellCentre(grid, active.row, active.col);
    const value = valueAt(grid, active.row, active.col);
    const distance = point === null ? null : formatKm(distanceKm(point, centre), locale);
    hover = (
      <HoverCell
        bounds={cellBounds(grid, active.row, active.col)}
        centre={centre}
        from={point}
        title={coordinates(centre, locale, t)}
        value={
          value === null
            ? t("map.cell.no_value")
            : grid.metric === "trigger_frequency"
              ? t("map.cell.frequency", { rate: formatFraction(value, locale) })
              : t("map.cell.anomaly", { anomaly: formatFraction(value, locale, { signed: true }) })
        }
        distance={distance}
        distanceLine={distance === null ? null : t("map.cell.distance", { distance })}
        paint={paint}
      />
    );
  }

  const synthetic = isSynthetic(region, datasetSource);
  const notes = (
    <div className="map-notes">
      {synthetic && <p className="map-notes__synthetic">{t("map.synthetic")}</p>}
      {grid !== null && (
        <p>
          {t("map.cube", {
            count: grid.nx * grid.ny,
            step: formatNumber(grid.step_deg, locale, { maximumFractionDigits: 2 }),
          })}
        </p>
      )}
      {grid !== null && render === "surface" && <p>{t("map.smoothing")}</p>}
      {outsideShowcase && <p>{t("map.outside_showcase")}</p>}
    </div>
  );

  return (
    <>
      {point !== null && (
        <InsuredPoint point={point} cell={insuredBounds} label={t("map.farm")} paint={paint} />
      )}
      {hover}
      {createPortal(notes, map.getContainer())}
    </>
  );
}
