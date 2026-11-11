import { useMutation } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap, type ApiProblem } from "../api/problems";
import type { components } from "../api/schema";

/**
 * Creates an API key for the workspace. The secret is returned once and is kept only by the
 * component that asked for it: it is never written to storage, and the mutation result is dropped
 * from the query cache as soon as that component is gone.
 */
export function useApiKey() {
  const client = useApiClient();
  return useMutation<components["schemas"]["ApiKeyIssued"], ApiProblem>({
    mutationFn: async () => unwrap(await client.POST("/api/v1/workspace/api-keys")),
    gcTime: 0,
  });
}
