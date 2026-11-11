import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "../api/client";
import { unwrap } from "../api/problems";
import type { components } from "../api/schema";
import { keys } from "./keys";

type ApprovalView = components["schemas"]["ApprovalView"];

export const DELIVERY_POLL_MS = 2000;

/** An approved submission whose webhook has not reached a final state yet. */
export function deliveryInProgress(approval: ApprovalView): boolean {
  return (
    approval.status === "approved" &&
    (approval.delivery.status === "not_started" || approval.delivery.status === "delivering")
  );
}

/**
 * The approval queue of the workspace. It is polled only while a delivery is in progress, so the
 * retry and the receipt appear without a reload and an idle queue costs nothing.
 */
export function useApprovals() {
  const client = useApiClient();
  return useQuery({
    queryKey: keys.approvals,
    queryFn: async ({ signal }) => unwrap(await client.GET("/api/v1/approvals", { signal })),
    refetchInterval: (query) =>
      (query.state.data ?? []).some(deliveryInProgress) ? DELIVERY_POLL_MS : false,
  });
}
