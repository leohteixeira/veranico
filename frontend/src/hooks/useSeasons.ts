import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap } from "../api/problems";
import { indexQuery, keys, type SeasonsRequest } from "./keys";

/** The seasonal index series of a point; payouts are included when a limit is given. */
export function useSeasons(request: SeasonsRequest | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: keys.seasons(request),
    enabled: request !== null,
    queryFn: async ({ signal }) => {
      if (request === null) throw new Error("useSeasons is disabled");
      return unwrap(
        await client.GET("/api/v1/weather/seasons", {
          params: {
            query: {
              lat: request.lat,
              lon: request.lon,
              ...(request.limitCents === null ? {} : { limit_cents: request.limitCents }),
              ...indexQuery(request.index),
            },
          },
          signal,
        }),
      );
    },
    staleTime: Infinity,
  });
}
