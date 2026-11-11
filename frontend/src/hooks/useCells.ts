import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap } from "../api/problems";
import { indexQuery, keys, type CellsRequest } from "./keys";

/**
 * The per-cell metric of a region. While another season loads, the previous grid stays on the map
 * (`isPlaceholderData` is then true), so dragging the timeline never blanks the risk layer.
 */
export function useCells(regionId: string | null, request: CellsRequest | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: keys.cells(regionId, request),
    enabled: regionId !== null && request !== null,
    queryFn: async ({ signal }) => {
      if (regionId === null || request === null) throw new Error("useCells is disabled");
      return unwrap(
        await client.GET("/api/v1/regions/{id}/cells", {
          params: {
            path: { id: regionId },
            query: {
              metric: request.metric,
              ...(request.season === null ? {} : { season: request.season }),
              ...indexQuery(request.index),
            },
          },
          signal,
        }),
      );
    },
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}
