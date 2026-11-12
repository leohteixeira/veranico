import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap } from "../api/problems";
import { keys } from "./keys";
import { allowanceHeader } from "./storage";

/** What is left of the visitor's daily allowance for the live agent. */
export function useAllowance() {
  const client = useApiClient();
  return useQuery({
    queryKey: keys.allowance,
    queryFn: async ({ signal }) =>
      unwrap(
        await client.GET("/api/v1/allowance", { params: { header: allowanceHeader() }, signal }),
      ),
  });
}
