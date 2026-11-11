import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap } from "../api/problems";
import { keys } from "./keys";

/** One quote, with its priced cover, submission and audit trail. */
export function useQuote(quoteId: string | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: keys.quote(quoteId),
    enabled: quoteId !== null,
    queryFn: async ({ signal }) => {
      if (quoteId === null) throw new Error("useQuote is disabled");
      return unwrap(
        await client.GET("/api/v1/quotes/{id}", { params: { path: { id: quoteId } }, signal }),
      );
    },
  });
}
