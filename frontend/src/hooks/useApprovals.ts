import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap } from "../api/problems";
import type { components } from "../api/schema";
import { keys } from "./keys";
import { quoteQuery } from "./useQuote";

type Schemas = components["schemas"];
type ApprovalView = Schemas["ApprovalView"];
type AuditEntry = Schemas["AuditEntry"];

export const DELIVERY_POLL_MS = 2000;

/** An approved submission whose webhook has not reached a final state yet. */
export function deliveryInProgress(approval: ApprovalView): boolean {
  return (
    approval.status === "approved" &&
    (approval.delivery.status === "not_started" || approval.delivery.status === "delivering")
  );
}

function deliveryChanged(before: ApprovalView, after: ApprovalView): boolean {
  return (
    before.status !== after.status ||
    before.delivery.status !== after.delivery.status ||
    before.delivery.attempts !== after.delivery.attempts ||
    before.delivery.receipt_id !== after.delivery.receipt_id
  );
}

/**
 * The approval queue of the workspace. It is polled only while a delivery is in progress, so the
 * retry and the receipt appear without a reload and an idle queue costs nothing. When a polled
 * delivery moves (an attempt, the receipt), the quote it belongs to is reloaded too, so the Quote
 * tab's status and audit trail follow the delivery in the same session.
 */
export function useApprovals() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: keys.approvals,
    queryFn: async ({ signal }) => {
      const before = queryClient.getQueryData<ApprovalView[]>(keys.approvals) ?? [];
      const after = unwrap(await client.GET("/api/v1/approvals", { signal }));
      const previous = new Map(before.map((approval) => [approval.approval_id, approval]));
      for (const approval of after) {
        const earlier = previous.get(approval.approval_id);
        if (earlier !== undefined && deliveryChanged(earlier, approval)) {
          void queryClient.invalidateQueries({ queryKey: keys.quote(approval.quote_id) });
        }
      }
      return after;
    },
    refetchInterval: (query) =>
      (query.state.data ?? []).some(deliveryInProgress) ? DELIVERY_POLL_MS : false,
  });
}

/**
 * The webhook attempts of each approved submission that has made one, by quote id, read from the
 * quote's audit trail (the delivery state keeps only the last error). The history stays on the
 * card after the delivery ends, so the failed first attempt and the retry remain visible.
 */
export function useDeliveryAttempts(
  approvals: readonly ApprovalView[] | undefined,
): ReadonlyMap<string, readonly AuditEntry[]> {
  const client = useApiClient();
  const quoteIds = (approvals ?? [])
    .filter((approval) => approval.status === "approved" && approval.delivery.attempts > 0)
    .map((approval) => approval.quote_id);
  return useQueries({
    queries: quoteIds.map((quoteId) => quoteQuery(client, quoteId)),
    combine: (results) =>
      new Map(
        results.flatMap((result, at) => {
          const quoteId = quoteIds[at];
          if (quoteId === undefined || result.data === undefined) return [];
          const attempts = result.data.audit.filter(
            (entry) => entry.action.code === "audit.webhook_attempt",
          );
          return [[quoteId, attempts] as const];
        }),
      ),
  });
}
