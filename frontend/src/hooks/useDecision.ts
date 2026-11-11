import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap, type ApiProblem } from "../api/problems";
import type { components } from "../api/schema";
import { keys } from "./keys";

type Schemas = components["schemas"];

interface DecisionInput {
  approvalId: string;
  decision: Schemas["Decision"];
}

/**
 * The human decision on a pending approval. Whatever the answer, the queue and the quotes are
 * reloaded: after a conflict (another tab decided first) the screen then shows the real state.
 */
export function useDecision() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation<Schemas["ApprovalView"], ApiProblem, DecisionInput>({
    mutationFn: async ({ approvalId, decision }) =>
      unwrap(
        await client.POST("/api/v1/approvals/{id}/decision", {
          params: { path: { id: approvalId } },
          body: decision,
        }),
      ),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.approvals }),
        queryClient.invalidateQueries({ queryKey: keys.quotes }),
      ]),
  });
}
