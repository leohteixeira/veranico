import { act, fireEvent, render, screen } from "@testing-library/react";
import type { Map as LeafletMap } from "leaflet";
import { useEffect, type ReactNode } from "react";
import { CircleMarker, useMap } from "react-leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadConfig, type BasemapConfig, type BasemapId } from "../config";
import type { Theme } from "../design/theme";
import { I18nProvider, translate } from "../i18n";
import { REGIONS } from "../test/fixtures/bodies";
import { Attribution } from "./Attribution";
import { MapStage, PLACE_LABELS_PANE } from "./MapStage";
import { FIT_MARGIN, activeBasemap, fitPadding, regionBounds, veil, type Insets } from "./basemaps";

const WIDTH = 1280;
const HEIGHT = 800;
const BASEMAPS = loadConfig({}).basemaps;
const PLACE_LABELS = loadConfig({}).placeLabels;

const [SUL_DE_MINAS, SORRISO] = REGIONS;
if (SUL_DE_MINAS === undefined || SORRISO === undefined) throw new Error("fixture regions missing");

// jsdom lays nothing out: give every element the size of the stage so Leaflet has a viewport.
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(WIDTH);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(HEIGHT);
});

afterEach(() => {
  vi.restoreAllMocks();
});

const captured: { map: LeafletMap | null } = { map: null };

/** Hands the Leaflet map of the stage to the test. */
function Capture() {
  const map = useMap();
  useEffect(() => {
    captured.map = map;
  }, [map]);
  return null;
}

function theMap(): LeafletMap {
  if (captured.map === null) throw new Error("the map was not rendered");
  return captured.map;
}

interface StageOptions {
  theme?: Theme;
  choice?: BasemapId | null;
  region?: (typeof REGIONS)[number] | null;
  insets?: Insets;
  children?: ReactNode;
}

function stage({
  theme = "light",
  choice = null,
  region = SUL_DE_MINAS,
  insets,
  children,
}: StageOptions = {}) {
  return (
    <I18nProvider locale="en">
      <MapStage
        region={region ?? null}
        basemap={activeBasemap(theme, choice)}
        theme={theme}
        basemaps={BASEMAPS}
        {...(insets === undefined ? {} : { insets })}
      >
        <Capture />
        {children}
      </MapStage>
    </I18nProvider>
  );
}

/** The tiles of the basemap: the place names are tiles too, in a pane of their own. */
function tiles(container: HTMLElement): HTMLImageElement[] {
  return [...container.querySelectorAll<HTMLImageElement>(".leaflet-tile-pane img.leaflet-tile")];
}

function placeLabelsPane(container: HTMLElement): HTMLElement | null {
  return container.querySelector<HTMLElement>(`.leaflet-${PLACE_LABELS_PANE}-pane`);
}

function labelTiles(container: HTMLElement): HTMLImageElement[] {
  return [
    ...(placeLabelsPane(container)?.querySelectorAll<HTMLImageElement>("img.leaflet-tile") ?? []),
  ];
}

describe("basemaps [R-12.2-1] [R-16.7-1]", () => {
  it("relief_is_default_in_light_and_satellite_in_dark", () => {
    expect(activeBasemap("light", null)).toBe("relief");
    expect(activeBasemap("dark", null)).toBe("satellite");

    const light = render(stage({ theme: "light" }));
    expect(tiles(light.container).length).toBeGreaterThan(0);
    expect(tiles(light.container).every((tile) => tile.src.includes("terrain-light_3857"))).toBe(
      true,
    );
    light.unmount();

    const dark = render(stage({ theme: "dark" }));
    expect(tiles(dark.container).length).toBeGreaterThan(0);
    expect(tiles(dark.container).every((tile) => tile.src.includes("s2cloudless-2025_3857"))).toBe(
      true,
    );
  });

  it("an_explicit_basemap_choice_survives_a_theme_change", () => {
    expect(activeBasemap("light", "satellite")).toBe("satellite");
    expect(activeBasemap("dark", "satellite")).toBe("satellite");
    expect(activeBasemap("dark", "relief")).toBe("relief");

    const { container, rerender } = render(stage({ theme: "light", choice: "satellite" }));
    rerender(stage({ theme: "dark", choice: "satellite" }));

    expect(container.querySelector(".map-stage")).toHaveAttribute("data-basemap", "satellite");
    expect(tiles(container).every((tile) => tile.src.includes("s2cloudless-2025_3857"))).toBe(true);
  });

  it("both basemaps come from configuration, over HTTPS, in Leaflet's template form", () => {
    for (const id of ["relief", "satellite"] as const) {
      const basemap = BASEMAPS[id];
      expect(basemap.urlTemplate).toMatch(
        /^https:\/\/tiles\.maps\.eox\.at\/wmts\/1\.0\.0\/[a-z0-9_-]+\/default\/g\/\{z\}\/\{y\}\/\{x\}\.jpg$/,
      );
      expect(basemap.attribution).not.toBe("");
      expect(basemap.licenceNote).not.toBe("");
      expect(basemap.maxZoom).toBeGreaterThan(8);
    }

    const replaced: BasemapConfig = {
      urlTemplate: "https://tiles.test/{z}/{y}/{x}.jpg",
      attribution: "Test tiles",
      licenceNote: "",
      maxZoom: 10,
    };
    const { container } = render(
      <I18nProvider locale="en">
        <MapStage
          region={SUL_DE_MINAS}
          basemap="relief"
          theme="light"
          basemaps={{ ...BASEMAPS, relief: replaced }}
        />
      </I18nProvider>,
    );
    expect(tiles(container).every((tile) => tile.src.startsWith("https://tiles.test/"))).toBe(true);
  });

  it("the veil of each theme is the reference paint, as a ground under thinned tiles", () => {
    expect(veil("light", "relief")).toEqual({ ground: "rgb(255, 250, 240)", tileOpacity: 0.88 });
    expect(veil("light", "satellite")).toEqual({ ground: "rgb(250, 246, 238)", tileOpacity: 0.6 });
    expect(veil("dark", "satellite")).toEqual({ ground: "rgb(6, 10, 16)", tileOpacity: 0.48 });
    expect(veil("dark", "relief")).toEqual({ ground: "rgb(8, 12, 18)", tileOpacity: 0.2 });

    const { container } = render(stage({ theme: "dark" }));
    const style = container.querySelector<HTMLElement>(".map-stage")?.style;
    expect(style?.getPropertyValue("--map-ground")).toBe("rgb(6, 10, 16)");
    expect(style?.getPropertyValue("--map-tile-opacity")).toBe("0.48");
  });
});

describe("attribution [R-12.2-1] [R-4.4-6] [R-12.6-2] [R-1-1]", () => {
  it("attribution_of_the_active_basemap_and_of_the_weather_data_is_visible", () => {
    const { rerender } = render(
      <I18nProvider locale="en">
        <Attribution basemap={BASEMAPS.relief} placeLabels={PLACE_LABELS.light} />
      </I18nProvider>,
    );

    const relief = screen.getByRole("link", {
      name: "Terrain Light { Data © OpenStreetMap contributors and others, Rendering © EOX }",
    });
    expect(relief).toBeVisible();
    expect(relief).toHaveAttribute("href", "https://maps.eox.at/#data");
    const weather = screen.getByText(translate("en", "app.weather_attribution"));
    expect(weather).toBeVisible();
    expect(weather).toHaveTextContent("Copernicus Climate Change Service");
    expect(weather).toHaveTextContent("ERA5-Land");
    expect(weather).toHaveTextContent("Open-Meteo");
    expect(weather).toHaveTextContent("CC BY 4.0");
    expect(screen.queryByText(/EOxCloudless/)).toBeNull();

    rerender(
      <I18nProvider locale="en">
        <Attribution basemap={BASEMAPS.satellite} placeLabels={PLACE_LABELS.dark} />
      </I18nProvider>,
    );

    expect(
      screen.getByRole("link", {
        name: "EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2025)",
      }),
    ).toHaveAttribute("href", "https://cloudless.eox.at");
    expect(screen.getByRole("link", { name: "CC BY-NC-SA 4.0" })).toHaveAttribute(
      "href",
      "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    );
    expect(screen.queryByText(/Terrain Light/)).toBeNull();
  });

  it.each(["en", "pt-BR"] as const)(
    "a synthetic region does not credit ERA5-Land for its surface (%s) [R-12.6-2]",
    (locale) => {
      const { rerender } = render(
        <I18nProvider locale={locale}>
          <Attribution basemap={BASEMAPS.relief} placeLabels={PLACE_LABELS.light} synthetic />
        </I18nProvider>,
      );

      const synthetic = screen.getByText(translate(locale, "app.weather_attribution_synthetic"));
      expect(synthetic).toBeVisible();
      // The regional surface is generated: no ERA5-Land credit, and the ERA5 credit stays for
      // the points it applies to.
      expect(synthetic).not.toHaveTextContent("ERA5-Land");
      expect(synthetic).toHaveTextContent("Open-Meteo");
      expect(synthetic).toHaveTextContent("CC BY 4.0");
      expect(screen.queryByText(translate(locale, "app.weather_attribution"))).toBeNull();

      rerender(
        <I18nProvider locale={locale}>
          <Attribution
            basemap={BASEMAPS.relief}
            placeLabels={PLACE_LABELS.light}
            synthetic={false}
          />
        </I18nProvider>,
      );

      expect(screen.getByText(translate(locale, "app.weather_attribution"))).toBeVisible();
      expect(screen.queryByText(translate(locale, "app.weather_attribution_synthetic"))).toBeNull();
    },
  );

  it("the synthetic weather line says what the surface is, in both languages", () => {
    expect(translate("en", "app.weather_attribution_synthetic")).toMatch(
      /synthetic.*not weather history/,
    );
    expect(translate("pt-BR", "app.weather_attribution_synthetic")).toMatch(
      /sintética.*não é histórico de clima/,
    );
  });

  it("non_commercial_notice_is_shown", () => {
    render(
      <I18nProvider locale="pt-BR">
        <Attribution basemap={BASEMAPS.satellite} placeLabels={PLACE_LABELS.dark} />
      </I18nProvider>,
    );

    expect(screen.getByText(translate("pt-BR", "app.non_commercial"))).toBeVisible();
    // The pricing disclaimer travels with it, and the provider's wording is not translated.
    expect(screen.getByText(translate("pt-BR", "app.disclaimer"))).toBeVisible();
    expect(screen.getByText(/EOxCloudless/)).toBeVisible();
  });
});

describe("place names [R-12.2-7]", () => {
  it("place_names_are_a_tile_layer_over_the_risk_layer_and_follow_the_theme", () => {
    const light = render(stage({ theme: "light" }));
    // Over the risk canvas (350), under the vector layers (400), and transparent to the pointer.
    expect(placeLabelsPane(light.container)?.style.zIndex).toBe("360");
    expect(placeLabelsPane(light.container)?.style.pointerEvents).toBe("none");
    expect(labelTiles(light.container).length).toBeGreaterThan(0);
    expect(labelTiles(light.container).every((tile) => tile.src.includes("/overlay_3857/"))).toBe(
      true,
    );
    light.unmount();

    // The dark theme darkens either basemap, so it takes the bright lettering even on relief.
    const dark = render(stage({ theme: "dark", choice: "relief" }));
    expect(labelTiles(dark.container).length).toBeGreaterThan(0);
    expect(
      labelTiles(dark.container).every((tile) => tile.src.includes("/overlay_bright_3857/")),
    ).toBe(true);
    expect(tiles(dark.container).every((tile) => tile.src.includes("terrain-light_3857"))).toBe(
      true,
    );
  });

  it("both place-name layers come from configuration, over HTTPS, as transparent tiles", () => {
    for (const theme of ["light", "dark"] as const) {
      const labels = PLACE_LABELS[theme];
      expect(labels.urlTemplate).toMatch(
        /^https:\/\/tiles\.maps\.eox\.at\/wmts\/1\.0\.0\/[a-z0-9_-]+\/default\/g\/\{z\}\/\{y\}\/\{x\}\.png$/,
      );
      expect(labels.attribution).toContain("OpenStreetMap contributors");
      expect(labels.attributionUrl).toMatch(/^https:\/\//);
    }

    const replaced = {
      urlTemplate: "https://labels.test/{z}/{y}/{x}.png",
      attribution: "Test labels",
      attributionUrl: "https://labels.test/",
    };
    const { container } = render(
      <I18nProvider locale="en">
        <MapStage
          region={SUL_DE_MINAS}
          basemap="relief"
          theme="light"
          basemaps={BASEMAPS}
          placeLabels={{ ...PLACE_LABELS, light: replaced }}
        />
      </I18nProvider>,
    );
    expect(labelTiles(container).every((tile) => tile.src.startsWith("https://labels.test/"))).toBe(
      true,
    );
  });

  it("a_place_name_tile_that_fails_is_not_a_failed_basemap", () => {
    const { container } = render(stage());

    for (const tile of labelTiles(container)) fireEvent.error(tile);

    expect(screen.queryByRole("status")).toBeNull();
  });

  it("the_place_name_layer_is_credited_next_to_the_map_in_both_themes", () => {
    const { rerender } = render(
      <I18nProvider locale="pt-BR">
        <Attribution basemap={BASEMAPS.relief} placeLabels={PLACE_LABELS.light} />
      </I18nProvider>,
    );

    expect(screen.getByText(translate("pt-BR", "attribution.place_names"))).toBeVisible();
    // The provider's wording is not translated.
    expect(
      screen.getByRole("link", {
        name: "Overlay { Data © OpenStreetMap contributors, Rendering © EOX and MapServer }",
      }),
    ).toHaveAttribute("href", "https://maps.eox.at/#data");

    rerender(
      <I18nProvider locale="pt-BR">
        <Attribution basemap={BASEMAPS.satellite} placeLabels={PLACE_LABELS.dark} />
      </I18nProvider>,
    );

    expect(
      screen.getByRole("link", {
        name: "Overlay bright { Data © OpenStreetMap contributors, Rendering © EOX and MapServer }",
      }),
    ).toHaveAttribute("href", "https://maps.eox.at/#data");
  });
});

describe("map stage [R-12.4-12] [R-16.7-1]", () => {
  it("tile_errors_show_the_basemap_failed_state_and_the_risk_layer_stays", () => {
    const { container } = render(
      stage({ children: <CircleMarker center={[-21.41, -45.48]} radius={6} /> }),
    );
    expect(screen.queryByRole("status")).toBeNull();
    const layerCount = () => container.querySelectorAll("path.leaflet-interactive").length;
    expect(layerCount()).toBe(1);

    for (const tile of tiles(container)) fireEvent.error(tile);

    expect(screen.getByRole("status")).toHaveTextContent(translate("en", "map.basemap_failed"));
    expect(layerCount()).toBe(1);

    // Asking again loads a fresh layer; a tile that arrives clears the state.
    fireEvent.click(screen.getByRole("button", { name: translate("en", "map.basemap_retry") }));
    expect(screen.queryByRole("status")).toBeNull();
    const [first, ...rest] = tiles(container);
    if (first === undefined) throw new Error("no tile was requested again");
    fireEvent.load(first);
    for (const tile of rest) fireEvent.error(tile);
    expect(screen.queryByRole("status")).toBeNull();
    expect(layerCount()).toBe(1);
  });

  it("region_change_fits_the_cube_inside_the_free_area_between_the_cards", () => {
    const insets: Insets = { top: 76, right: 400, bottom: 190, left: 392 };
    expect(fitPadding(insets)).toEqual({
      paddingTopLeft: [392 + FIT_MARGIN, 76 + FIT_MARGIN],
      paddingBottomRight: [400 + FIT_MARGIN, 190 + FIT_MARGIN],
    });

    const { rerender } = render(stage({ region: SUL_DE_MINAS, insets }));

    const inFreeArea = (region: (typeof REGIONS)[number]) => {
      const [[south, west], [north, east]] = regionBounds(region);
      const topLeft = theMap().latLngToContainerPoint([north, west]);
      const bottomRight = theMap().latLngToContainerPoint([south, east]);
      expect(topLeft.x).toBeGreaterThanOrEqual(insets.left);
      expect(topLeft.y).toBeGreaterThanOrEqual(insets.top);
      expect(bottomRight.x).toBeLessThanOrEqual(WIDTH - insets.right);
      expect(bottomRight.y).toBeLessThanOrEqual(HEIGHT - insets.bottom);
      // Fitted, not merely contained: the cube uses most of one free dimension.
      const used = Math.max(
        (bottomRight.x - topLeft.x) / (WIDTH - insets.left - insets.right),
        (bottomRight.y - topLeft.y) / (HEIGHT - insets.top - insets.bottom),
      );
      expect(used).toBeGreaterThan(0.6);
    };
    inFreeArea(SUL_DE_MINAS);

    act(() => {
      rerender(stage({ region: SORRISO, insets }));
    });
    inFreeArea(SORRISO);

    // Cards that grow move the cube again.
    const wider: Insets = { ...insets, left: 520 };
    act(() => {
      rerender(stage({ region: SORRISO, insets: wider }));
    });
    expect(theMap().latLngToContainerPoint([SORRISO.north, SORRISO.west]).x).toBeGreaterThanOrEqual(
      520,
    );
  });

  it("names the map after its region and shows no Leaflet attribution control", () => {
    const { container, rerender } = render(stage({ region: null }));
    expect(screen.getByRole("region", { name: "Map" })).toBeInTheDocument();

    rerender(stage({ region: SUL_DE_MINAS }));

    expect(screen.getByRole("region", { name: `Map of ${SUL_DE_MINAS.name}` })).toBeInTheDocument();
    expect(container.querySelector(".leaflet-control-attribution")).toBeNull();
  });
});
