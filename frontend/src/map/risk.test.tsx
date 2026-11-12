import { act, render, screen } from "@testing-library/react";
import L from "leaflet";
import { useEffect, type ReactNode } from "react";
import { useMap } from "react-leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../api/schema";
import { loadConfig } from "../config";
import { MAP_PAINT, type Rgba } from "../design/theme";
import { I18nProvider, translate, type Locale } from "../i18n";
import { INSURED_COL, INSURED_ROW, POINT, REGIONS, cellGrid } from "../test/fixtures/bodies";
import { MapStage } from "./MapStage";
import { paintRisk, type RenderMode, type RiskFrame } from "./RiskLayer";
import { RiskLayerView, isSynthetic } from "./RiskLayerView";
import {
  cellAt,
  cellBounds,
  cellCentre,
  distanceKm,
  gridBounds,
  neighbourRange,
  neighbours,
  pointCell,
  valueAt,
  type CellRef,
} from "./geometry";
import { classColour, classCount, classOf, colourAt, rampFor, rgbaCss, sampleRamp } from "./ramps";
import { FEATHER, rasterSize, renderSurface } from "./surface";

type Schemas = components["schemas"];
type CellGrid = Schemas["CellGrid"];

const [SUL_DE_MINAS] = REGIONS;
if (SUL_DE_MINAS === undefined) throw new Error("fixture regions missing");
const GRID = cellGrid(SUL_DE_MINAS);
const BASEMAPS = loadConfig({}).basemaps;

/** A four by four grid with a value in every cell, rising to the south-east. */
function smallGrid(values?: (number | null)[]): CellGrid {
  return {
    region_id: "test",
    metric: "trigger_frequency",
    nx: 4,
    ny: 4,
    north: -20,
    west: -46,
    step_deg: 0.1,
    values: values ?? Array.from({ length: 16 }, (_, index) => 0.02 + index * 0.025),
    // Four classes: five edges, both ends included.
    breaks: [0, 0.1, 0.2, 0.3, 0.4],
    seasons: [2001, 2002],
    cells_paying: null,
    suggested_season: null,
  };
}

const RAMP: Rgba[] = [
  [250, 230, 200, 0.6],
  [240, 180, 120, 0.7],
  [200, 100, 60, 0.8],
  [120, 40, 20, 0.9],
];
/** Five raster pixels per cell, so a cell centre falls on a pixel centre. */
const SIZE = { width: 20, height: 20 };

function pixel(raster: { width: number; data: Uint8ClampedArray }, x: number, y: number): number[] {
  const offset = (y * raster.width + x) * 4;
  return [...raster.data.slice(offset, offset + 4)];
}

function bytes(colour: Rgba): number[] {
  return [colour[0], colour[1], colour[2], colour[3] * 255];
}

function expectClose(actual: number[], expected: number[]): void {
  actual.forEach((channel, at) => {
    expect(Math.abs(channel - (expected[at] ?? NaN))).toBeLessThanOrEqual(1);
  });
}

describe("ramps [R-12.2-2] [R-16.7-1]", () => {
  it("class_of_value_uses_the_api_breaks", () => {
    // The edges the API returned for a real grid: five classes, from its minimum to its maximum.
    const breaks = [0.447368, 0.547368, 0.647368, 0.747368, 0.847368, 0.947368];
    expect(classCount(breaks)).toBe(5);

    expect(classOf(0.447368, breaks)).toBe(0);
    expect(classOf(0.5, breaks)).toBe(0);
    // A value on an inner edge belongs to the class above it.
    expect(classOf(0.547368, breaks)).toBe(1);
    expect(classOf(0.8, breaks)).toBe(3);
    expect(classOf(0.9, breaks)).toBe(4);
    // The maximum is the last edge and belongs to the last class: there is no class beyond it.
    expect(classOf(0.947368, breaks)).toBe(4);
    // Six anomaly classes, symmetric around zero: zero opens the first wet class.
    const anomaly = [-0.6, -0.4, -0.2, 0, 0.2, 0.4, 0.6];
    expect(classCount(anomaly)).toBe(6);
    expect(classOf(-0.6, anomaly)).toBe(0);
    expect(classOf(-0.01, anomaly)).toBe(2);
    expect(classOf(0, anomaly)).toBe(3);
    expect(classOf(0.6, anomaly)).toBe(5);
    // Every cell equal: one class. No cell with a value: none.
    expect(classCount([0.2, 0.2])).toBe(1);
    expect(classOf(0.2, [0.2, 0.2])).toBe(0);
    expect(classCount([])).toBe(0);
    expect(classOf(0.2, [])).toBe(0);
  });

  it("ramp_is_sampled_to_the_number_of_classes", () => {
    const paint = MAP_PAINT.light;

    // One colour per class: n + 1 edges give n swatches, from the first stop to the last.
    const frequency = rampFor("trigger_frequency", paint, GRID.breaks);
    expect(GRID.breaks).toHaveLength(6);
    expect(frequency).toHaveLength(5);
    expect(frequency[0]).toEqual(paint.sequential[0]);
    expect(frequency[4]).toEqual(paint.sequential[5]);

    const anomaly = rampFor("season_anomaly", paint, [-0.6, -0.4, -0.2, 0, 0.2, 0.4, 0.6]);
    expect(anomaly).toHaveLength(6);
    expect(anomaly[0]).toEqual(paint.diverging[0]);
    expect(anomaly[5]).toEqual(paint.diverging[6]);

    expect(rampFor("trigger_frequency", paint, [0.2, 0.2])).toHaveLength(1);
    expect(rampFor("trigger_frequency", paint, [])).toEqual([]);
    expect(sampleRamp(paint.diverging, 7)).toEqual(paint.diverging);
  });

  it("the continuous colour is the class colour at the middle of a class, between the edges", () => {
    const breaks = [0, 0.1, 0.2, 0.3, 0.4];

    expectClose(bytes(colourAt(0.15, breaks, RAMP)), bytes(RAMP[1] as Rgba));
    expectClose(bytes(colourAt(0.25, breaks, RAMP)), bytes(RAMP[2] as Rgba));
    // The two ends take the first and last colour; nothing lies beyond them.
    expect(colourAt(0, breaks, RAMP)).toEqual(RAMP[0]);
    expect(colourAt(0.4, breaks, RAMP)).toEqual(RAMP[3]);
    expect(classColour(0.15, breaks, RAMP)).toEqual(RAMP[1]);
    expect(classColour(0.4, breaks, RAMP)).toEqual(RAMP[3]);
    // A grid where every cell is equal still has a colour.
    expect(colourAt(0.2, [0.2, 0.2], [RAMP[1] as Rgba])).toEqual(RAMP[1]);
    expect(colourAt(0.2, [], [])).toEqual([0, 0, 0, 0]);
    expect(rgbaCss([250.4, 230, 200, 0.6])).toBe("rgba(250,230,200,0.600)");
  });
});

describe("surface [R-12.2-2] [R-16.7-1]", () => {
  it("raster_at_a_cell_centre_equals_the_cell_colour", () => {
    const grid = smallGrid();
    const raster = renderSurface(grid, RAMP, SIZE);

    for (const [row, col] of [
      [1, 1],
      [1, 2],
      [2, 1],
      [2, 2],
    ] as const) {
      const value = valueAt(grid, row, col) ?? NaN;
      expectClose(
        pixel(raster, col * 5 + 2, row * 5 + 2),
        bytes(colourAt(value, grid.breaks, RAMP)),
      );
    }
    expect(rasterSize({ nx: 20, ny: 20 })).toEqual({ width: 96, height: 96 });
  });

  it("raster_between_two_centres_is_between_their_colours", () => {
    const grid = smallGrid();
    const raster = renderSurface(grid, RAMP, SIZE);
    const left = pixel(raster, 7, 7);
    const right = pixel(raster, 12, 7);

    for (const x of [8, 9, 10, 11]) {
      const between = pixel(raster, x, 7);
      between.forEach((channel, at) => {
        const low = Math.min(left[at] ?? NaN, right[at] ?? NaN);
        const high = Math.max(left[at] ?? NaN, right[at] ?? NaN);
        expect(channel).toBeGreaterThanOrEqual(low);
        expect(channel).toBeLessThanOrEqual(high);
      });
    }
    expect(pixel(raster, 9, 7)).not.toEqual(left);
  });

  it("edge_alpha_feathers_to_zero", () => {
    const grid = smallGrid(Array.from({ length: 16 }, () => 0.15));
    const raster = renderSurface(grid, RAMP, SIZE);
    const full = (RAMP[1] as Rgba)[3] * 255;
    const alpha = (x: number, y: number) => pixel(raster, x, y)[3] ?? NaN;

    for (let step = 0; step < FEATHER; step += 1) {
      const expected = (full * (step + 1)) / FEATHER;
      // The same fade from each of the four borders.
      expect(Math.abs(alpha(step, 10) - expected)).toBeLessThanOrEqual(1);
      expect(Math.abs(alpha(19 - step, 10) - expected)).toBeLessThanOrEqual(1);
      expect(Math.abs(alpha(10, step) - expected)).toBeLessThanOrEqual(1);
      expect(Math.abs(alpha(10, 19 - step) - expected)).toBeLessThanOrEqual(1);
    }
    expect(alpha(0, 10)).toBeLessThan(alpha(1, 10));
    expect(Math.abs(alpha(10, 10) - full)).toBeLessThanOrEqual(1);
  });

  it("null_cells_are_transparent", () => {
    const values = smallGrid().values;
    values[2 * 4 + 2] = null;
    const grid = smallGrid(values);
    const raster = renderSurface(grid, RAMP, SIZE);

    for (let y = 10; y < 15; y += 1) {
      for (let x = 10; x < 15; x += 1) expect(pixel(raster, x, y)[3]).toBe(0);
    }
    // The neighbour to the west is drawn, and the empty cell does not bleed into it: at the
    // last pixel before the gap the colour is still the neighbour's own.
    const west = valueAt(grid, 2, 1) ?? NaN;
    expectClose(pixel(raster, 9, 12), bytes(colourAt(west, grid.breaks, RAMP)));
    expect(pixel(raster, 9, 12)[3]).toBeGreaterThan(0);
  });
});

describe("geometry [R-12.2-3] [R-12-2] [R-16.7-1]", () => {
  it("cell_at_maps_a_point_to_row_and_column_north_to_south", () => {
    expect(cellAt(GRID, POINT.lat, POINT.lon)).toEqual({ row: INSURED_ROW, col: INSURED_COL });
    // Just inside the north-west corner is row 0, column 0; the south-east corner is the last.
    expect(cellAt(GRID, GRID.north - 0.01, GRID.west + 0.01)).toEqual({ row: 0, col: 0 });
    expect(cellAt(GRID, GRID.north - 1.99, GRID.west + 1.99)).toEqual({ row: 19, col: 19 });

    const [[south, west], [north, east]] = cellBounds(GRID, INSURED_ROW, INSURED_COL);
    expect(POINT.lat).toBeGreaterThan(south);
    expect(POINT.lat).toBeLessThan(north);
    expect(POINT.lon).toBeGreaterThan(west);
    expect(POINT.lon).toBeLessThan(east);
    const centre = cellCentre(GRID, 0, 0);
    expect(centre.lat).toBeCloseTo(GRID.north - 0.05, 9);
    expect(centre.lon).toBeCloseTo(GRID.west + 0.05, 9);
    expect(gridBounds(GRID)[0][0]).toBeCloseTo(SUL_DE_MINAS.south, 9);
    expect(gridBounds(GRID)[1][1]).toBeCloseTo(SUL_DE_MINAS.east, 9);
  });

  it("point_outside_the_grid_has_no_cell", () => {
    expect(cellAt(GRID, GRID.north + 0.01, GRID.west + 1)).toBeNull();
    expect(cellAt(GRID, GRID.north - 1, GRID.west - 0.01)).toBeNull();
    expect(cellAt(GRID, GRID.north - 2.01, GRID.west + 1)).toBeNull();
    expect(cellAt(GRID, -12.6, -55.66)).toBeNull();
    expect(valueAt(GRID, -1, 0)).toBeNull();
  });

  it("neighbours_at_a_corner_are_three", () => {
    expect(neighbours(GRID, 0, 0)).toHaveLength(3);
    expect(neighbours(GRID, 19, 19)).toHaveLength(3);
    expect(neighbours(GRID, 0, 5)).toHaveLength(5);
    expect(neighbours(GRID, 9, 10)).toHaveLength(8);
    expect(neighbours(GRID, 9, 10)).not.toContainEqual({ row: 9, col: 10 });
  });

  it("the neighbour range is the minimum and maximum of values the API returned", () => {
    const values = smallGrid().values;
    values[0] = null;
    const grid = smallGrid(values);
    const around = neighbours(grid, 1, 1)
      .map((cell) => valueAt(grid, cell.row, cell.col))
      .filter((value): value is number => value !== null);

    expect(around).toHaveLength(7);
    expect(neighbourRange(grid, 1, 1)).toEqual({
      min: Math.min(...around),
      max: Math.max(...around),
    });
    expect(neighbourRange(smallGrid(Array.from({ length: 16 }, () => null)), 1, 1)).toBeNull();
  });

  it("distance_matches_a_known_pair", () => {
    // One degree of latitude along a meridian on the mean Earth radius.
    expect(distanceKm({ lat: 0, lon: 0 }, { lat: 1, lon: 0 })).toBeCloseTo(111.195, 2);
    expect(distanceKm({ lat: 0, lon: 0 }, { lat: 0, lon: 1 })).toBeCloseTo(111.195, 2);
    // A degree of longitude shortens with the cosine of the latitude.
    expect(distanceKm({ lat: 60, lon: 0 }, { lat: 60, lon: 1 })).toBeCloseTo(55.597, 1);
    expect(distanceKm(POINT, POINT)).toBe(0);
  });

  it("the outline of a point outside the regions is a cell of the ERA5 0.25 degree grid", () => {
    const [[south, west], [north, east]] = pointCell({ lat: -12.62, lon: -55.66 });

    expect(south).toBeCloseTo(-12.625, 9);
    expect(north).toBeCloseTo(-12.375, 9);
    expect(west).toBeCloseTo(-55.875, 9);
    expect(east).toBeCloseTo(-55.625, 9);
    // It says nothing about which grid point the quote used: the note names the source's.
    expect(translate("en", "map.outside_showcase")).toContain(
      "the ERA5 grid point the weather source returned",
    );
  });
});

/** A stand-in for the 2D context that records what the layer asked for. */
function fakeContext() {
  const calls: Record<string, unknown[][]> = {};
  const record =
    (name: string) =>
    (...args: unknown[]) => {
      (calls[name] ??= []).push(args);
    };
  const context = {
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    globalAlpha: 1,
    imageSmoothingEnabled: false,
    imageSmoothingQuality: "low",
    setTransform: record("setTransform"),
    clearRect: record("clearRect"),
    beginPath: record("beginPath"),
    rect: record("rect"),
    fill: record("fill"),
    fillRect: record("fillRect"),
    moveTo: record("moveTo"),
    lineTo: record("lineTo"),
    stroke: record("stroke"),
    strokeRect: record("strokeRect"),
    drawImage: record("drawImage"),
    putImageData: record("putImageData"),
    createImageData: (width: number, height: number) => ({
      width,
      height,
      data: new Uint8ClampedArray(width * height * 4),
    }),
  };
  const count = (name: string) => calls[name]?.length ?? 0;
  return { context, calls, count };
}

describe("risk painting [R-12.2-2] [R-12.2-6]", () => {
  const frame: RiskFrame = {
    width: 400,
    height: 300,
    xs: [100, 150, 200, 250, 300],
    ys: [50, 100, 150, 200, 250],
  };
  const paint = MAP_PAINT.light;

  function drawn(mode: RenderMode, grid = smallGrid()) {
    const fake = fakeContext();
    paintRisk(
      fake.context as unknown as CanvasRenderingContext2D,
      frame,
      { grid, render: mode, paint, basemap: "relief" },
      mode === "surface" ? ({} as CanvasImageSource) : null,
    );
    return fake;
  }

  it("cells_switch_draws_flat_cells", () => {
    const values = smallGrid().values;
    values[5] = null;
    const cells = drawn("cells", smallGrid(values));

    // One flat rectangle per cell that has a value, and no interpolated surface.
    expect(cells.count("fillRect")).toBe(15);
    expect(cells.count("drawImage")).toBe(0);
    expect(cells.calls.fillRect?.[0]).toEqual([100, 50, 50.5, 50.5]);

    const surface = drawn("surface");
    expect(surface.count("drawImage")).toBe(1);
    expect(surface.calls.drawImage?.[0]?.slice(1)).toEqual([100, 50, 200, 200]);
    expect(surface.count("fillRect")).toBe(0);
  });

  it("dims the outside, draws the grid hairlines at half strength over the surface, and the border", () => {
    const surface = drawn("surface");

    // The whole stage minus the cube, filled with the even-odd rule.
    expect(surface.calls.rect).toEqual([
      [0, 0, 400, 300],
      [100, 50, 200, 200],
    ]);
    expect(surface.calls.fill).toEqual([["evenodd"]]);
    // Three inner lines each way; the border is the cube.
    expect(surface.count("moveTo")).toBe(6);
    expect(surface.calls.strokeRect).toEqual([[100, 50, 200, 200]]);
    expect(surface.context.strokeStyle).toBe(paint.cube);

    let alphaAtStroke = 0;
    const fake = fakeContext();
    fake.context.stroke = () => {
      alphaAtStroke = fake.context.globalAlpha;
    };
    paintRisk(
      fake.context as unknown as CanvasRenderingContext2D,
      frame,
      { grid: smallGrid(), render: "surface", paint, basemap: "relief" },
      null,
    );
    expect(alphaAtStroke).toBe(0.5);
    paintRisk(
      fake.context as unknown as CanvasRenderingContext2D,
      frame,
      { grid: smallGrid(), render: "cells", paint, basemap: "relief" },
      null,
    );
    expect(alphaAtStroke).toBe(1);
  });
});

const WIDTH = 1280;
const HEIGHT = 800;
const captured: { map: L.Map | null } = { map: null };

function Capture() {
  const map = useMap();
  useEffect(() => {
    captured.map = map;
  }, [map]);
  return null;
}

function theMap(): L.Map {
  if (captured.map === null) throw new Error("the map was not rendered");
  return captured.map;
}

interface ViewOptions {
  grid?: CellGrid | null;
  region?: Schemas["Region"] | null;
  point?: { lat: number; lon: number } | null;
  mode?: RenderMode;
  datasetSource?: string | null;
  locale?: Locale;
  onActiveCell?: (cell: CellRef | null) => void;
  children?: ReactNode;
}

function view({
  grid = GRID,
  region = SUL_DE_MINAS,
  point = POINT,
  mode = "surface",
  datasetSource = null,
  locale = "en",
  onActiveCell,
}: ViewOptions = {}) {
  return (
    <I18nProvider locale={locale}>
      <MapStage region={region ?? null} basemap="relief" theme="light" basemaps={BASEMAPS}>
        <Capture />
        <RiskLayerView
          grid={grid}
          region={region ?? null}
          point={point}
          render={mode}
          theme="light"
          basemap="relief"
          datasetSource={datasetSource}
          {...(onActiveCell === undefined ? {} : { onActiveCell })}
        />
      </MapStage>
    </I18nProvider>
  );
}

function fire(type: "mousemove" | "click" | "mouseout", lat: number, lon: number): void {
  act(() => {
    theMap().fire(type, { latlng: L.latLng(lat, lon) });
  });
}

describe("risk layer on the map [R-12.2-2] [R-12.2-3] [R-12.2-6] [R-12.4-6] [R-16.7-1]", () => {
  let canvas: ReturnType<typeof fakeContext>;

  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(WIDTH);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(HEIGHT);
    canvas = fakeContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      canvas.context as unknown as CanvasRenderingContext2D,
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("layer_redraws_on_move_zoom_and_resize", () => {
    const { container } = render(view());
    const layer = container.querySelector<HTMLCanvasElement>("canvas.risk-layer");
    expect(layer).not.toBeNull();
    expect(layer?.width).toBe(WIDTH);
    expect(layer?.height).toBe(HEIGHT);
    // The canvas sits under the vector layers and over the tiles, and takes no pointer events.
    expect(layer?.parentElement?.style.zIndex).toBe("350");
    expect(layer).toHaveAttribute("aria-hidden", "true");

    for (const event of ["move", "moveend", "zoomend", "resize"]) {
      const before = canvas.count("clearRect");
      act(() => {
        theMap().fire(event);
      });
      expect(canvas.count("clearRect"), event).toBe(before + 1);
    }

    // After a pan the canvas is pinned back to the corner of the viewport.
    act(() => {
      theMap().panBy([120, -40], { animate: false });
    });
    const corner = theMap().containerPointToLayerPoint([0, 0]);
    expect(L.DomUtil.getPosition(layer as HTMLElement)).toEqual(corner);
  });

  it("cells_switch_draws_flat_cells on the map and the surface raster is built once", () => {
    const { rerender } = render(view({ mode: "surface" }));
    expect(canvas.count("putImageData")).toBe(1);
    expect(canvas.count("drawImage")).toBeGreaterThan(0);
    expect(canvas.count("fillRect")).toBe(0);
    act(() => {
      theMap().fire("move");
    });
    expect(canvas.count("putImageData")).toBe(1);

    rerender(view({ mode: "cells" }));

    expect(canvas.count("fillRect")).toBe(GRID.nx * GRID.ny);
  });

  it("smoothing_note_is_shown_in_surface_mode", () => {
    const { rerender } = render(view({ mode: "surface" }));
    expect(screen.getByText(translate("en", "map.smoothing"))).toBeInTheDocument();
    expect(screen.getByText("Weather grid: 400 cells of 0.1°")).toBeInTheDocument();

    rerender(view({ mode: "cells" }));

    expect(screen.queryByText(translate("en", "map.smoothing"))).toBeNull();
    expect(screen.getByText("Weather grid: 400 cells of 0.1°")).toBeInTheDocument();
  });

  it("hover_shows_cell_value_and_leg_with_distance", () => {
    const onActiveCell = vi.fn();
    const { container } = render(view({ onActiveCell }));
    expect(container.querySelector(".map-hover-cell")).toBeNull();
    const target = { row: 6, col: 14 };
    const centre = cellCentre(GRID, target.row, target.col);

    fire("mousemove", centre.lat + 0.02, centre.lon - 0.03);

    expect(container.querySelector(".map-hover-cell")).not.toBeNull();
    expect(container.querySelector(".map-leg")).not.toBeNull();
    // The value is the API's, formatted; the distance is the geometric length of the leg.
    const value = valueAt(GRID, target.row, target.col) ?? NaN;
    const rate = new Intl.NumberFormat("en-US", { style: "percent" }).format(value);
    expect(screen.getByText(`Pays in ${rate} of seasons`)).toBeInTheDocument();
    const km = distanceKm(POINT, centre).toFixed(1);
    expect(screen.getByText(`${km} km`)).toBeInTheDocument();
    expect(screen.getByText(`${km} km from the farm`)).toBeInTheDocument();
    expect(screen.getByText("21.10° S, 45.10° W")).toBeInTheDocument();
    expect(onActiveCell).toHaveBeenLastCalledWith(target);

    fire("mouseout", centre.lat, centre.lon);

    expect(container.querySelector(".map-hover-cell")).toBeNull();
    expect(onActiveCell).toHaveBeenLastCalledWith(null);

    // The insured cell is already outlined: hovering it adds no second outline and no leg.
    fire("mousemove", POINT.lat, POINT.lon);
    expect(container.querySelector(".map-hover-cell")).toBeNull();
    expect(container.querySelector(".map-leg")).toBeNull();
  });

  it("a season's anomaly is shown signed, in the language of the page", () => {
    const anomaly = cellGrid(SUL_DE_MINAS, { metric: "season_anomaly", season: 1987 });
    render(view({ grid: anomaly, locale: "pt-BR" }));
    const centre = cellCentre(anomaly, 3, 3);

    fire("mousemove", centre.lat, centre.lon);

    const value = valueAt(anomaly, 3, 3) ?? NaN;
    const text = new Intl.NumberFormat("pt-BR", {
      style: "percent",
      signDisplay: "exceptZero",
    }).format(value);
    expect(screen.getByText(`${text} contra a mediana`)).toBeInTheDocument();
    expect(screen.getByText("Fazenda")).toBeInTheDocument();
  });

  it("tap_selects_a_cell_on_touch", () => {
    const { container } = render(view());
    const first = cellCentre(GRID, 4, 4);
    const second = cellCentre(GRID, 15, 12);

    // A tap arrives as a click with no pointer movement before it; the selection stays.
    fire("click", first.lat, first.lon);
    expect(container.querySelectorAll(".map-hover-cell")).toHaveLength(1);
    expect(screen.getByText("20.90° S, 46.10° W")).toBeInTheDocument();

    fire("click", second.lat, second.lon);
    expect(container.querySelectorAll(".map-hover-cell")).toHaveLength(1);
    expect(screen.queryByText("20.90° S, 46.10° W")).toBeNull();

    // Tapping the selected cell again, or outside the cube, clears it.
    fire("click", second.lat, second.lon);
    expect(container.querySelector(".map-hover-cell")).toBeNull();
    fire("click", first.lat, first.lon);
    fire("click", GRID.north + 0.5, GRID.west);
    expect(container.querySelector(".map-hover-cell")).toBeNull();
  });

  it("insured_cell_is_outlined", () => {
    const { container } = render(view());

    expect(container.querySelectorAll(".map-insured-cell")).toHaveLength(1);
    expect(container.querySelectorAll(".map-insured-point")).toHaveLength(1);
    expect(screen.getByText("Farm")).toBeInTheDocument();
    // The outline is the cell of the grid the point falls in.
    const [[south, west], [north, east]] = cellBounds(GRID, INSURED_ROW, INSURED_COL);
    const topLeft = theMap().latLngToLayerPoint([north, west]);
    const bottomRight = theMap().latLngToLayerPoint([south, east]);
    const path = container.querySelector(".map-insured-cell")?.getAttribute("d") ?? "";
    expect(path).toContain(`${topLeft.x} ${topLeft.y}`);
    expect(path).toContain(`${bottomRight.x} ${bottomRight.y}`);
  });

  it("point_outside_showcase_shows_marker_single_cell_and_note", () => {
    const { container } = render(
      view({ grid: null, region: null, point: { lat: -9.41, lon: -40.5 } }),
    );

    expect(container.querySelectorAll(".map-insured-point")).toHaveLength(1);
    expect(container.querySelectorAll(".map-insured-cell")).toHaveLength(1);
    expect(screen.getByText(translate("en", "map.outside_showcase"))).toBeInTheDocument();
    // No regional view: nothing is painted and nothing is said about smoothing or a cube.
    expect(canvas.count("drawImage")).toBe(0);
    expect(canvas.count("fillRect")).toBe(0);
    expect(screen.queryByText(translate("en", "map.smoothing"))).toBeNull();
    expect(screen.queryByText(/Weather grid/)).toBeNull();

    fire("mousemove", -9.4, -40.4);
    expect(container.querySelector(".map-hover-cell")).toBeNull();
  });

  it("synthetic_label_follows_region_synthetic", () => {
    // The recorded region is real; the same region labelled generated by the API.
    const generated = { ...SUL_DE_MINAS, synthetic: true };
    expect(isSynthetic(generated, null)).toBe(true);

    render(view({ region: generated }));

    expect(screen.getByText(translate("en", "map.synthetic"))).toBeInTheDocument();
  });

  it("synthetic_label_follows_dataset_source", () => {
    const real = { ...SUL_DE_MINAS, synthetic: false };
    expect(isSynthetic(real, "synthetic")).toBe(true);
    expect(isSynthetic(null, "synthetic")).toBe(true);

    render(view({ region: real, datasetSource: "synthetic" }));

    expect(screen.getByText(translate("en", "map.synthetic"))).toBeInTheDocument();
  });

  it("no_synthetic_label_for_a_real_cube", () => {
    const real = { ...SUL_DE_MINAS, synthetic: false };
    expect(isSynthetic(real, null)).toBe(false);
    expect(isSynthetic(real, "era5-land/cds")).toBe(false);
    expect(isSynthetic(null, "era5/open-meteo")).toBe(false);

    render(view({ region: real, datasetSource: "era5-land/cds" }));

    expect(screen.queryByText(translate("en", "map.synthetic"))).toBeNull();
  });
});
