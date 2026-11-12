import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap } from "../api/problems";
import { keys } from "./keys";

/** The showcase regions. Public reference data: it does not change during a visit. */
export function useRegions() {
  const client = useApiClient();
  return useQuery({
    queryKey: keys.regions,
    queryFn: async ({ signal }) => unwrap(await client.GET("/api/v1/regions", { signal })),
    staleTime: Infinity,
  });
}
