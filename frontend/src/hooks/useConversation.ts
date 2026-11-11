import { useQuery } from "@tanstack/react-query";

import { useApiClient, type ApiClient } from "../api/client";
import { unwrap } from "../api/problems";
import { keys } from "./keys";

/** The stored conversation, as the API holds it. */
export async function fetchConversation(
  client: ApiClient,
  conversationId: string,
  signal?: AbortSignal,
) {
  return unwrap(
    await client.GET("/api/v1/conversations/{id}", {
      params: { path: { id: conversationId } },
      ...(signal === undefined ? {} : { signal }),
    }),
  );
}

/** A stored conversation, to restore the screen after a reload. */
export function useConversation(conversationId: string | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: keys.conversation(conversationId),
    enabled: conversationId !== null,
    queryFn: ({ signal }) => {
      if (conversationId === null) throw new Error("useConversation is disabled");
      return fetchConversation(client, conversationId, signal);
    },
    retry: false,
    staleTime: Infinity,
  });
}
