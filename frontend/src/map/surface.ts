import type { components } from "../api/schema";
import type { Rgba } from "../design/theme";
import { colourAt } from "./ramps";

type CellGrid = components["schemas"]["CellGrid"];

/** What a canvas `ImageData` holds, without needing a canvas to build it. */
export interface Raster {
  width: number;
  height: number;
  /** Red, green, blue, alpha per pixel, row by row from the north-west corner. */
  data: Uint8ClampedArray;
}

export interface RasterSize {
  width: number;
  height: number;
}

/** Raster pixels per grid cell: 96 by 96 for a 20 by 20 cube, as in the approved preview. */
const PIXELS_PER_CELL = 4.8;

/** Pixels over which the surface fades out at the border of the cube. */
export const FEATHER = 4;

export function rasterSize(grid: Pick<CellGrid, "nx" | "ny">): RasterSize {
  return {
    width: Math.max(1, Math.round(grid.nx * PIXELS_PER_CELL)),
    height: Math.max(1, Math.round(grid.ny * PIXELS_PER_CELL)),
  };
}

/**
 * The continuous surface: a small raster filled by bilinear interpolation between cell centres,
 * clamped at the edges, fading to transparent over the last pixels of the border. The canvas
 * stretches it over the cube with smoothing. This is a way of drawing the API's values: every
 * cell centre keeps the colour of its own value.
 *
 * A cell without a value is transparent, and it takes no part in the blend of its neighbours.
 */
export function renderSurface(
  grid: Pick<CellGrid, "nx" | "ny" | "values" | "breaks">,
  ramp: readonly Rgba[],
  size: RasterSize = rasterSize(grid),
): Raster {
  const { nx, ny, values, breaks } = grid;
  const { width, height } = size;
  const data = new Uint8ClampedArray(width * height * 4);
  const valueAt = (row: number, col: number) => values[row * nx + col] ?? null;

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      // The pixel centre in grid units, where a cell centre is a whole number.
      const gx = Math.max(0, Math.min(nx - 1, ((x + 0.5) / width) * nx - 0.5));
      const gy = Math.max(0, Math.min(ny - 1, ((y + 0.5) / height) * ny - 0.5));
      // The cell this pixel lies in decides whether anything is drawn.
      const ownCol = Math.min(nx - 1, Math.floor(((x + 0.5) / width) * nx));
      const ownRow = Math.min(ny - 1, Math.floor(((y + 0.5) / height) * ny));
      if (valueAt(ownRow, ownCol) === null) continue;

      const col0 = Math.floor(gx);
      const row0 = Math.floor(gy);
      const col1 = Math.min(nx - 1, col0 + 1);
      const row1 = Math.min(ny - 1, row0 + 1);
      const fx = gx - col0;
      const fy = gy - row0;
      const corners: [number | null, number][] = [
        [valueAt(row0, col0), (1 - fx) * (1 - fy)],
        [valueAt(row0, col1), fx * (1 - fy)],
        [valueAt(row1, col0), (1 - fx) * fy],
        [valueAt(row1, col1), fx * fy],
      ];
      let sum = 0;
      let weight = 0;
      for (const [value, share] of corners) {
        if (value === null) continue;
        sum += value * share;
        weight += share;
      }
      // Only corners without a value carry weight here: fall back to the pixel's own cell.
      const value = weight > 0 ? sum / weight : (valueAt(ownRow, ownCol) ?? 0);

      const [red, green, blue, alpha] = colourAt(value, breaks, ramp);
      const edge = Math.min(x, y, width - 1 - x, height - 1 - y);
      const feather = edge >= FEATHER - 1 ? 1 : (edge + 1) / FEATHER;
      const offset = (y * width + x) * 4;
      data[offset] = red;
      data[offset + 1] = green;
      data[offset + 2] = blue;
      data[offset + 3] = alpha * 255 * feather;
    }
  }
  return { width, height, data };
}
