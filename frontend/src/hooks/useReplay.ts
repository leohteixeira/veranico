import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { toApiProblem } from "../api/problems";
import { parseEventText } from "../api/sse";
import type { Locale } from "../i18n";
import { keys } from "./keys";

/**
 * The recorded conversation in one language: every event of every recorded turn, in order, with
 * the recorded requests as `user_message` events. The server sends the recording at once; the
 * conversation card paces it. Loaded only when asked for (`enabled`).
 */
export function useReplay(locale: Locale, enabled: boolean) {
  const client = useApiClient();
  return useQuery({
    queryKey: keys.replay(locale),
    enabled,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await client.GET("/api/v1/replays/{locale}", {
        params: { path: { locale } },
        parseAs: "text",
        signal,
      });
      if (error !== undefined || !response.ok || data === undefined) {
        throw toApiProblem(error, response);
      }
      return parseEventText(data);
    },
    staleTime: Infinity,
  });
}
