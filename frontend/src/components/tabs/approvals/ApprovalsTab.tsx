import { useState } from "react";

import type { components } from "../../../api/schema";
import { useApprovals } from "../../../hooks/useApprovals";
import { useDecision } from "../../../hooks/useDecision";
import { useRedeliver } from "../../../hooks/useRedeliver";
import { translate, useI18n } from "../../../i18n";
import { TabEmpty, TabState } from "../TabState";
import { ApprovalItem } from "./ApprovalItem";

import "../tabs.css";

type ApprovalView = components["schemas"]["ApprovalView"];

/** How many items wait for a decision: the count on the tab. */
export function pendingCount(approvals: readonly ApprovalView[] | undefined): number {
  return (approvals ?? []).filter((approval) => approval.status === "pending").length;
}

interface ApprovalsTabProps {
  onOpenQuote: (quoteId: string) => void;
}

/**
 * The approval queue of the workspace. A decision or a redelivery reloads the queue whatever the
 * answer, so after a conflict (another tab decided first) the item shows its real state next to
 * the problem.
 */
export function ApprovalsTab({ onOpenQuote }: ApprovalsTabProps) {
  const { locale } = useI18n();
  const approvals = useApprovals();
  const decision = useDecision();
  const redelivery = useRedeliver();
  // The item the last action was on, so its problem is shown on that item only.
  const [acted, setActed] = useState<string | null>(null);

  if (approvals.data === undefined) {
    return (
      <TabState
        status={approvals.isError ? "failed" : "loading"}
        onRetry={() => {
          void approvals.refetch();
        }}
      />
    );
  }
  if (approvals.data.length === 0) {
    return <TabEmpty>{translate(locale, "approvals.empty")}</TabEmpty>;
  }

  const problem = decision.error?.code ?? redelivery.error?.code ?? null;
  return (
    <ul className="approvals">
      {approvals.data.map((approval) => {
        const id = approval.approval_id;
        return (
          <ApprovalItem
            key={id}
            approval={approval}
            busy={acted === id && (decision.isPending || redelivery.isPending)}
            problem={acted === id ? problem : null}
            onOpenQuote={onOpenQuote}
            onDecide={(approve, note) => {
              setActed(id);
              redelivery.reset();
              decision.mutate({ approvalId: id, decision: { approve, note } });
            }}
            onRedeliver={() => {
              setActed(id);
              decision.reset();
              redelivery.mutate(id);
            }}
          />
        );
      })}
    </ul>
  );
}
