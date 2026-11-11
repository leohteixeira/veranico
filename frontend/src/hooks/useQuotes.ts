import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap } from "../api/problems";
import { keys } from "./keys";

/** The quotes of this browser's workspace. */
export function useQuotes() {
  const client = useApiClient();
  return useQuery({
    queryKey: keys.quotes,
    queryFn: async ({ signal }) => unwrap(await client.GET("/api/v1/quotes", { signal })),
  });
}
