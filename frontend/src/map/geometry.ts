import type { components } from "../api/schema";
import type { LatLngBoundsTuple } from "./basemaps";

type CellGrid = components["schemas"]["CellGrid"];

/** The part of a grid that says where its cells are. Row 0 is the northern edge. */
export type GridFrame = Pick<CellGrid, "nx" | "ny" | "north" | "west" | "step_deg">;

export interface CellRef {
  row: number;
  col: number;
}

export interface LatLon {
  lat: number;
  lon: number;
}

/** The whole cube: south-west, then north-east. */
export function gridBounds(grid: GridFrame): LatLngBoundsTuple {
  return [
    [grid.north - grid.ny * grid.step_deg, grid.west],
    [grid.north, grid.west + grid.nx * grid.step_deg],
  ];
}

/** The cell a point falls in, rows counted from north to south; `null` outside the grid. */
export function cellAt(grid: GridFrame, lat: number, lon: number): CellRef | null {
  const row = Math.floor((grid.north - lat) / grid.step_deg);
  const col = Math.floor((lon - grid.west) / grid.step_deg);
  if (row < 0 || col < 0 || row >= grid.ny || col >= grid.nx) return null;
  return { row, col };
}

export function cellBounds(grid: GridFrame, row: number, col: number): LatLngBoundsTuple {
  const north = grid.north - row * grid.step_deg;
  const west = grid.west + col * grid.step_deg;
  return [
    [north - grid.step_deg, west],
    [north, west + grid.step_deg],
  ];
}

export function cellCentre(grid: GridFrame, row: number, col: number): LatLon {
  return {
    lat: grid.north - (row + 0.5) * grid.step_deg,
    lon: grid.west + (col + 0.5) * grid.step_deg,
  };
}

/** The cells that touch a cell, by side or by corner: eight inside, five on an edge, three at a corner. */
export function neighbours(grid: Pick<CellGrid, "nx" | "ny">, row: number, col: number): CellRef[] {
  const cells: CellRef[] = [];
  for (let dRow = -1; dRow <= 1; dRow += 1) {
    for (let dCol = -1; dCol <= 1; dCol += 1) {
      if (dRow === 0 && dCol === 0) continue;
      const next = { row: row + dRow, col: col + dCol };
      if (next.row < 0 || next.col < 0 || next.row >= grid.ny || next.col >= grid.nx) continue;
      cells.push(next);
    }
  }
  return cells;
}

/** The value the API returned for a cell; `null` when it returned none. */
export function valueAt(
  grid: Pick<CellGrid, "nx" | "ny" | "values">,
  row: number,
  col: number,
): number | null {
  if (row < 0 || col < 0 || row >= grid.ny || col >= grid.nx) return null;
  return grid.values[row * grid.nx + col] ?? null;
}

export interface ValueRange {
  min: number;
  max: number;
}

/**
 * The lowest and highest value among a cell's neighbours. One of the two display derivations the
 * specification allows: a minimum and a maximum over cells the API already returned.
 */
export function neighbourRange(
  grid: Pick<CellGrid, "nx" | "ny" | "values">,
  row: number,
  col: number,
): ValueRange | null {
  let range: ValueRange | null = null;
  for (const cell of neighbours(grid, row, col)) {
    const value = valueAt(grid, cell.row, cell.col);
    if (value === null) continue;
    range =
      range === null
        ? { min: value, max: value }
        : { min: Math.min(range.min, value), max: Math.max(range.max, value) };
  }
  return range;
}

const EARTH_RADIUS_KM = 6371.0088;
const RADIANS = Math.PI / 180;

/**
 * The great-circle distance between two points (haversine). The other allowed display derivation:
 * the geometric length of the measured leg on the map.
 */
export function distanceKm(a: LatLon, b: LatLon): number {
  const dLat = (b.lat - a.lat) * RADIANS;
  const dLon = (b.lon - a.lon) * RADIANS;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a.lat * RADIANS) * Math.cos(b.lat * RADIANS) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** The step of the ERA5 family grids the point path reads, in degrees. */
export const POINT_CELL_STEP = 0.1;

/**
 * The grid cell around a point that lies outside the showcase regions: the 0.1° cell whose centre
 * is the nearest grid node. Shown as an outline only; it carries no value.
 */
export function pointCell(point: LatLon, step = POINT_CELL_STEP): LatLngBoundsTuple {
  const lat = Math.round(point.lat / step) * step;
  const lon = Math.round(point.lon / step) * step;
  return [
    [lat - step / 2, lon - step / 2],
    [lat + step / 2, lon + step / 2],
  ];
}
