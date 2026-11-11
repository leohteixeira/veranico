import L from "leaflet";

import type { components } from "../api/schema";
import type { BasemapId } from "../config";
import type { MapPaint, Rgba } from "../design/theme";
import { classColour, rampFor, rgbaCss } from "./ramps";
import { renderSurface } from "./surface";

type CellGrid = components["schemas"]["CellGrid"];

export type RenderMode = "surface" | "cells";

export interface RiskState {
  /** The per-cell metric to draw, or `null` when there is none (nothing is drawn). */
  grid: CellGrid | null;
  render: RenderMode;
  paint: MapPaint;
  basemap: BasemapId;
}

/** Where the cube sits on the canvas, in CSS pixels. */
export interface RiskFrame {
  width: number;
  height: number;
  /** The x of each cell edge, west to east: `nx + 1` values. */
  xs: readonly number[];
  /** The y of each cell edge, north to south: `ny + 1` values. */
  ys: readonly number[];
}

/**
 * Draws the risk over the basemap: the area outside the cube dimmed, the values as a continuous
 * surface or as flat cells, the grid as hairlines (half strength over the surface) and the cube
 * border. `surface` is the small raster of `renderSurface`, already on a canvas.
 */
export function paintRisk(
  context: CanvasRenderingContext2D,
  frame: RiskFrame,
  state: RiskState & { grid: CellGrid },
  surface: CanvasImageSource | null,
): void {
  const { grid, paint, basemap, render } = state;
  const { width, height, xs, ys } = frame;
  const x0 = xs[0] ?? 0;
  const x1 = xs[xs.length - 1] ?? 0;
  const y0 = ys[0] ?? 0;
  const y1 = ys[ys.length - 1] ?? 0;

  context.fillStyle = paint.outside[basemap];
  context.beginPath();
  context.rect(0, 0, width, height);
  context.rect(x0, y0, x1 - x0, y1 - y0);
  context.fill("evenodd");

  if (render === "surface") {
    if (surface !== null) {
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = "high";
      context.drawImage(surface, x0, y0, x1 - x0, y1 - y0);
    }
  } else {
    const ramp = rampFor(grid.metric, paint, grid.breaks);
    for (let row = 0; row < grid.ny; row += 1) {
      for (let col = 0; col < grid.nx; col += 1) {
        const value = grid.values[row * grid.nx + col] ?? null;
        if (value === null) continue;
        const left = xs[col] ?? 0;
        const top = ys[row] ?? 0;
        context.fillStyle = rgbaCss(classColour(value, grid.breaks, ramp));
        // Half a pixel of overlap, so no hairline of basemap shows between two cells.
        context.fillRect(
          left,
          top,
          (xs[col + 1] ?? left) - left + 0.5,
          (ys[row + 1] ?? top) - top + 0.5,
        );
      }
    }
  }

  context.strokeStyle = paint.grid;
  context.lineWidth = 1;
  context.globalAlpha = render === "surface" ? 0.5 : 1;
  context.beginPath();
  for (let col = 1; col < grid.nx; col += 1) {
    const x = Math.round(xs[col] ?? 0) + 0.5;
    context.moveTo(x, y0);
    context.lineTo(x, y1);
  }
  for (let row = 1; row < grid.ny; row += 1) {
    const y = Math.round(ys[row] ?? 0) + 0.5;
    context.moveTo(x0, y);
    context.lineTo(x1, y);
  }
  context.stroke();

  context.globalAlpha = 1;
  context.strokeStyle = paint.cube;
  context.lineWidth = 1.2;
  context.strokeRect(x0, y0, x1 - x0, y1 - y0);
}

interface SurfaceCache {
  grid: CellGrid;
  ramp: readonly Rgba[];
  canvas: HTMLCanvasElement;
}

/**
 * The risk as one canvas layer the size of the map. It is redrawn while the map moves, so the dim
 * outside the cube always reaches the edges of the stage, and it scales with the tiles during a
 * zoom animation. The insured point and the hovered cell are ordinary vector layers above it.
 */
export class RiskLayer extends L.Layer {
  private state: RiskState;
  private canvas: HTMLCanvasElement | null = null;
  private cache: SurfaceCache | null = null;
  /** The view the canvas was last drawn for; the zoom animation scales from it. */
  private drawn: { centre: L.LatLng; zoom: number } | null = null;

  constructor(state: RiskState, options?: L.LayerOptions) {
    super();
    // `L.Layer` has no initialiser of its own: the options (the pane) are set here.
    L.Util.setOptions(this, options ?? {});
    this.state = state;
  }

  override onAdd(map: L.Map): this {
    const canvas = L.DomUtil.create("canvas", "risk-layer leaflet-zoom-animated");
    canvas.setAttribute("aria-hidden", "true");
    this.canvas = canvas;
    this.getPane()?.appendChild(canvas);
    this.redraw(map);
    return this;
  }

  override onRemove(): this {
    this.canvas?.remove();
    this.canvas = null;
    this.drawn = null;
    return this;
  }

  override getEvents(): Record<string, L.LeafletEventHandlerFn> {
    const redraw = () => {
      this.redraw();
    };
    return {
      move: redraw,
      moveend: redraw,
      zoomend: redraw,
      viewreset: redraw,
      resize: redraw,
      zoomanim: (event) => {
        this.animateZoom(event as L.ZoomAnimEvent);
      },
    };
  }

  setState(state: RiskState): void {
    this.state = state;
    this.redraw();
  }

  /** The small raster of the surface, kept until the grid or the colours change. */
  private surface(grid: CellGrid): HTMLCanvasElement | null {
    const ramp = rampFor(grid.metric, this.state.paint, grid.breaks);
    const cached = this.cache;
    if (cached !== null && cached.grid === grid && cached.ramp.join() === ramp.join()) {
      return cached.canvas;
    }
    const raster = renderSurface(grid, ramp);
    const canvas = document.createElement("canvas");
    canvas.width = raster.width;
    canvas.height = raster.height;
    const context = canvas.getContext("2d");
    if (context === null) return null;
    const image = context.createImageData(raster.width, raster.height);
    image.data.set(raster.data);
    context.putImageData(image, 0, 0);
    this.cache = { grid, ramp, canvas };
    return canvas;
  }

  redraw(map: L.Map | undefined = this._map as L.Map | undefined): void {
    const canvas = this.canvas;
    if (canvas === null || map === undefined) return;
    const size = map.getSize();
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const pixelWidth = Math.round(size.x * ratio);
    const pixelHeight = Math.round(size.y * ratio);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
      canvas.style.width = `${size.x}px`;
      canvas.style.height = `${size.y}px`;
    }
    // The canvas lives in a pane that moves with the map: pin it back to the viewport corner.
    L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]));
    this.drawn = { centre: map.getCenter(), zoom: map.getZoom() };

    const context = canvas.getContext("2d");
    if (context === null) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.globalAlpha = 1;
    context.clearRect(0, 0, size.x, size.y);

    const { grid } = this.state;
    if (grid === null) return;
    const xs: number[] = [];
    const ys: number[] = [];
    for (let col = 0; col <= grid.nx; col += 1) {
      xs.push(map.latLngToContainerPoint([grid.north, grid.west + col * grid.step_deg]).x);
    }
    for (let row = 0; row <= grid.ny; row += 1) {
      ys.push(map.latLngToContainerPoint([grid.north - row * grid.step_deg, grid.west]).y);
    }
    paintRisk(
      context,
      { width: size.x, height: size.y, xs, ys },
      { ...this.state, grid },
      this.state.render === "surface" ? this.surface(grid) : null,
    );
  }

  /** Scales the drawn canvas with the tiles while Leaflet animates a zoom, as its renderers do. */
  private animateZoom(event: L.ZoomAnimEvent): void {
    const canvas = this.canvas;
    const map = this._map as L.Map | undefined;
    const drawn = this.drawn;
    if (canvas === null || map === undefined || drawn === null) return;
    const scale = map.getZoomScale(event.zoom, drawn.zoom);
    const position = L.DomUtil.getPosition(canvas);
    const viewHalf = map.getSize().multiplyBy(0.5);
    const centreOffset = map
      .project(event.center, event.zoom)
      .subtract(map.project(drawn.centre, event.zoom));
    const topLeft = viewHalf.multiplyBy(-scale).add(position).add(viewHalf).subtract(centreOffset);
    L.DomUtil.setTransform(canvas, topLeft, scale);
  }
}
