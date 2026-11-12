import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ApiClientProvider, createApiClient, type ApiClient } from "../api/client";
import { SeasonTimeline } from "../components/timeline/SeasonTimeline";
import { config } from "../config";
import { useTheme, type Theme } from "../design/theme";
import { useCells } from "../hooks/useCells";
import { useRegions } from "../hooks/useRegions";
import { useTimelineSeries } from "../hooks/useTimelineSeries";
import { I18nProvider, resolveLocale } from "../i18n";
import { activeBasemap } from "../map/basemaps";
import { MapStage } from "../map/MapStage";
import { RiskLayerView } from "../map/RiskLayerView";

import "./embed.css";

/** The path of the embed route (SPEC 12.5). */
export const EMBED_PATH = "/embed/map";

/** The only thing the embed tells its host: the map and the first risk layer have drawn. */
export const EMBED_READY = { type: "veranico:embed-ready" } as const;

export function isEmbedPath(pathname: string): boolean {
  return pathname === EMBED_PATH || pathname === `${EMBED_PATH}/`;
}

export interface EmbedParams {
  /** The region asked for; an unknown or missing one falls back to the first. */
  regionId: string | null;
  /** The theme asked for; `null` follows the system. */
  theme: Theme | null;
}

/** `?region=<id>&theme=<light|dark>`; `lang` is read by `resolveLocale`. */
export function embedParams(search: string): EmbedParams {
  const query = new URLSearchParams(search);
  const theme = query.get("theme");
  return {
    regionId: query.get("region"),
    theme: theme === "light" || theme === "dark" ? theme : null,
  };
}

/**
 * The client of the embed. It sends no cookie: the embed has no workspace, and it reads only the
 * three public reference routes (`GET /regions`, `GET /regions/{id}/cells`,
 * `GET /weather/seasons`).
 */
export function createEmbedClient(baseUrl = ""): ApiClient {
  return createApiClient({ baseUrl, credentials: "omit" });
}

interface EmbedViewProps {
  regionId: string | null;
  theme: Theme | null;
}

function EmbedView({ regionId, theme: forced }: EmbedViewProps) {
  const { theme } = useTheme(forced ?? undefined);
  const basemap = activeBasemap(theme, null);
  const regions = useRegions();
  const [season, setSeason] = useState<number | null>(null);

  const region =
    regions.data?.find((item) => item.region_id === regionId) ?? regions.data?.[0] ?? null;
  const example = region === null ? undefined : config.exampleCovers[region.region_id];
  const point = example?.point ?? null;
  const index = example?.cover.index ?? null;

  const cells = useCells(
    region?.region_id ?? null,
    index === null
      ? null
      : { metric: season === null ? "trigger_frequency" : "season_anomaly", index, season },
  );
  const grid = cells.data ?? null;
  const timeline = useTimelineSeries({
    backtest: null,
    point,
    index,
    limitCents: example?.cover.limit.amount_cents ?? null,
  });

  // Posted once, after the effects of the map's layers, which draw the grid they were given. If
  // the region data never loads, nothing is posted and the host keeps its static image. The
  // message holds no data and the embed does not know which origin frames it, so it is not
  // restricted to one; the host checks who sent it.
  const announced = useRef(false);
  const drawn = grid !== null;
  useEffect(() => {
    if (!drawn || announced.current) return;
    announced.current = true;
    window.parent.postMessage(EMBED_READY, "*");
  }, [drawn]);

  return (
    <main className="embed">
      <div className="embed__map">
        <MapStage region={region} basemap={basemap} theme={theme}>
          <RiskLayerView
            grid={grid}
            region={region}
            point={point}
            render="surface"
            theme={theme}
            basemap={basemap}
          />
        </MapStage>
      </div>
      <SeasonTimeline
        className="embed__timeline"
        seasons={timeline.seasons}
        index={index}
        selected={season}
        suggested={grid?.suggested_season ?? null}
        onSelect={setSeason}
        status={index === null ? "ready" : timeline.status}
        onRetry={timeline.retry}
        basemap={config.basemaps[basemap]}
        placeLabels={config.placeLabels[theme]}
        synthetic={region?.synthetic === true}
      />
    </main>
  );
}

interface EmbedMapProps {
  /** The query string of the page; a test supplies its own. */
  search?: string;
  /** The API client; a test supplies its own. */
  client?: ApiClient;
}

/**
 * `/embed/map?region=<id>&lang=<en|pt-BR>&theme=<light|dark>`: the map, the risk layer and the
 * season timeline of one region with its example cover, read-only, for an iframe. No
 * conversation, no tabs, no workspace.
 */
export function EmbedMap({ search = window.location.search, client }: EmbedMapProps) {
  const [queryClient] = useState(() => new QueryClient());
  const [embedClient] = useState(() => client ?? createEmbedClient());
  const { regionId, theme } = embedParams(search);
  // The stored preference is not read: inside a frame, storage belongs to another context.
  const locale = resolveLocale(search, null, window.navigator.languages);
  return (
    <QueryClientProvider client={queryClient}>
      <ApiClientProvider client={embedClient}>
        <I18nProvider locale={locale}>
          <EmbedView regionId={regionId} theme={theme} />
        </I18nProvider>
      </ApiClientProvider>
    </QueryClientProvider>
  );
}
