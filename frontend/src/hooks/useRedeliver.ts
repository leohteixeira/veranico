import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap, type ApiProblem } from "../api/problems";
import type { components } from "../api/schema";
import { keys } from "./keys";

/** Enqueues the webhook again after an abandoned delivery. */
export function useRedeliver() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation<components["schemas"]["ApprovalView"], ApiProblem, string>({
    mutationFn: async (approvalId) =>
      unwrap(
        await client.POST("/api/v1/approvals/{id}/redeliver", {
          params: { path: { id: approvalId } },
        }),
      ),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.approvals }),
        queryClient.invalidateQueries({ queryKey: keys.quotes }),
      ]),
  });
}
