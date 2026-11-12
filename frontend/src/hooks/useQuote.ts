import { useQuery } from "@tanstack/react-query";

import { useApiClient, type ApiClient } from "../api/client";
import { unwrap } from "../api/problems";
import { keys } from "./keys";

/** The query of one quote, shared by the Quote tab and the delivery history of an approval. */
export function quoteQuery(client: ApiClient, quoteId: string | null) {
  return {
    queryKey: keys.quote(quoteId),
    enabled: quoteId !== null,
    queryFn: async ({ signal }: { signal: AbortSignal }) => {
      if (quoteId === null) throw new Error("the quote query is disabled");
      return unwrap(
        await client.GET("/api/v1/quotes/{id}", { params: { path: { id: quoteId } }, signal }),
      );
    },
  };
}

/** One quote, with its priced cover, submission and audit trail. */
export function useQuote(quoteId: string | null) {
  const client = useApiClient();
  return useQuery(quoteQuery(client, quoteId));
}
