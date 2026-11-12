import "leaflet/dist/leaflet.css";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { MapContainer, Pane, TileLayer, useMap } from "react-leaflet";

import type { components } from "../api/schema";
import { Button } from "../components/common/Button";
import { Icon } from "../components/common/Icon";
import { Note } from "../components/common/Note";
import { config, type BasemapConfig, type BasemapId, type PlaceLabelsConfig } from "../config";
import { MAP_PAINT, type Theme } from "../design/theme";
import { useI18n } from "../i18n";
import { NO_INSETS, fitPadding, regionBounds, veil, type Insets } from "./basemaps";
import "./map.css";

type Region = components["schemas"]["Region"];

/** Brazil, before a region is known. */
const INITIAL_CENTRE: [number, number] = [-15.5, -50.5];
const INITIAL_ZOOM = 4;
const MIN_ZOOM = 4;

/** The pane of the place names: over the risk canvas (350), under the vector layers (400). */
export const PLACE_LABELS_PANE = "place-labels";

function prefersReducedMotion(): boolean {
  // No media queries (an old browser, a test): move without animation.
  if (typeof window.matchMedia !== "function") return true;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

interface FitRegionProps {
  region: Region | null;
  insets: Insets;
}

/** Fits the region's cube inside the area the cards leave free, again when either changes. */
function FitRegion({ region, insets }: FitRegionProps) {
  const map = useMap();
  const fitted = useRef(false);
  const { top, right, bottom, left } = insets;

  useEffect(() => {
    if (region === null) return;
    map.invalidateSize({ animate: false });
    map.fitBounds(regionBounds(region), {
      ...fitPadding({ top, right, bottom, left }),
      // The first fit is the opening view; later ones travel, unless motion is unwelcome.
      animate: fitted.current && !prefersReducedMotion(),
    });
    fitted.current = true;
  }, [map, region, top, right, bottom, left]);

  return null;
}

interface TileStatus {
  /** The layer these counts belong to. */
  layer: string;
  loaded: number;
  failed: number;
}

interface MapStageProps {
  /** The showcase region in view, or `null` before one is known. */
  region: Region | null;
  /** The basemap to show, already resolved from the theme and the visitor's choice. */
  basemap: BasemapId;
  theme: Theme;
  /** What the floating cards cover; the region is fitted in what is left. */
  insets?: Insets;
  /** The tile sources; the build-time configuration unless a test supplies its own. */
  basemaps?: Record<BasemapId, BasemapConfig>;
  /** The place-name layers, by theme; the build-time configuration unless a test supplies its own. */
  placeLabels?: Record<Theme, PlaceLabelsConfig>;
  /** Layers drawn over the basemap: the risk layer, the insured point, the hovered cell. */
  children?: ReactNode;
}

/**
 * The stage: a Leaflet map filling its parent, with one of the two configured basemaps under the
 * veil of the theme and the place names of the theme over the risk layer. Layers are passed as
 * children, so they stay when the basemap fails to load. A place-name tile that fails is only a
 * missing label: it does not count towards the basemap notice.
 * The attribution is not drawn here: `Attribution` shows it in the timeline card.
 */
export function MapStage({
  region,
  basemap,
  theme,
  insets = NO_INSETS,
  basemaps = config.basemaps,
  placeLabels = config.placeLabels,
  children,
}: MapStageProps) {
  const { t } = useI18n();
  const [attempt, setAttempt] = useState(0);
  const layer = `${basemap}:${attempt}`;
  const [tiles, setTiles] = useState<TileStatus>({ layer, loaded: 0, failed: 0 });
  const source = basemaps[basemap];
  const paint = veil(theme, basemap);

  const count = (field: "loaded" | "failed") => {
    setTiles((previous) => {
      const current = previous.layer === layer ? previous : { layer, loaded: 0, failed: 0 };
      return { ...current, [field]: current[field] + 1 };
    });
  };
  // Failed: tiles of this basemap were refused and none has arrived.
  const failed = tiles.layer === layer && tiles.failed > 0 && tiles.loaded === 0;

  const style = {
    "--map-ground": paint.ground,
    "--map-tile-opacity": paint.tileOpacity,
    "--map-inset-top": `${insets.top}px`,
    "--map-inset-left": `${insets.left}px`,
    "--map-inset-right": `${insets.right}px`,
    "--map-inset-bottom": `${insets.bottom}px`,
    "--map-marker": MAP_PAINT[theme].marker,
    "--map-marker-ink": MAP_PAINT[theme].markerInk,
  } as CSSProperties;

  return (
    <section
      className="map-stage"
      style={style}
      data-basemap={basemap}
      aria-label={region === null ? t("map.label_empty") : t("map.label", { region: region.name })}
    >
      <MapContainer
        center={INITIAL_CENTRE}
        zoom={INITIAL_ZOOM}
        minZoom={MIN_ZOOM}
        maxZoom={source.maxZoom}
        zoomControl={false}
        // Whole zoom levels only: at a fractional zoom the scaled tiles show hairline seams.
        attributionControl={false}
      >
        <TileLayer
          key={layer}
          url={source.urlTemplate}
          maxZoom={source.maxZoom}
          eventHandlers={{
            tileload: () => {
              count("loaded");
            },
            tileerror: () => {
              count("failed");
            },
          }}
        />
        <Pane name={PLACE_LABELS_PANE} style={{ zIndex: 360, pointerEvents: "none" }}>
          <TileLayer key={theme} url={placeLabels[theme].urlTemplate} maxZoom={source.maxZoom} />
        </Pane>
        <FitRegion region={region} insets={insets} />
        {children}
      </MapContainer>
      {failed && (
        <Note tone="warn" role="status" className="map-stage__failed" icon={<Icon name="warn" />}>
          <span>{t("map.basemap_failed")}</span>
          <Button
            variant="link"
            size="sm"
            onClick={() => {
              setAttempt((value) => value + 1);
            }}
          >
            {t("map.basemap_retry")}
          </Button>
        </Note>
      )}
    </section>
  );
}
