import { useId, useState } from "react";

import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { translateProblem } from "../../../i18n/coded";
import { formatDate, formatMoney, formatNumber } from "../../../i18n/format";
import { Button } from "../../common/Button";
import { Icon } from "../../common/Icon";
import { Note } from "../../common/Note";
import { StateBadge, type StateTone } from "../../common/StateBadge";
import { FieldList } from "../FieldList";
import { DeliveryProgress } from "./DeliveryProgress";

type ApprovalView = components["schemas"]["ApprovalView"];

/** The longest decision note the API accepts (`Decision.note`). */
export const NOTE_MAX = 500;

interface ApprovalItemProps {
  approval: ApprovalView;
  /** A decision or a redelivery of this item is on its way. */
  busy: boolean;
  /** The code of the problem the last action on this item ended with. */
  problem: string | null;
  onDecide: (approve: boolean, note: string | null) => void;
  onRedeliver: () => void;
  onOpenQuote: (quoteId: string) => void;
  /** The webhook attempts from the quote's audit trail, oldest first. */
  attempts?: readonly components["schemas"]["AuditEntry"][];
}

type Display = { key: Parameters<typeof translate>[1]; tone: StateTone };

/** The one state shown on the item: the decision, then how the delivery stands. */
function display(approval: ApprovalView): Display {
  if (approval.status === "pending") return { key: "status.approval.pending", tone: "pending" };
  if (approval.status === "rejected") return { key: "status.approval.rejected", tone: "bad" };
  if (approval.delivery.status === "delivered") {
    return { key: "status.delivery.delivered", tone: "ok" };
  }
  if (approval.delivery.status === "abandoned") {
    return { key: "status.delivery.abandoned", tone: "bad" };
  }
  return { key: "status.delivery.delivering", tone: "pending" };
}

/**
 * One submission in the approval queue. While it is pending a person approves or rejects it, with
 * an optional note; afterwards the item shows the delivery to the carrier, or that it was closed.
 */
export function ApprovalItem({
  approval,
  busy,
  problem,
  onDecide,
  onRedeliver,
  onOpenQuote,
  attempts = [],
}: ApprovalItemProps) {
  const { locale } = useI18n();
  const [note, setNote] = useState("");
  const noteId = useId();
  const countId = useId();
  const tooLong = note.length > NOTE_MAX;
  const state = display(approval);

  const decide = (approve: boolean) => {
    if (tooLong || busy) return;
    const text = note.trim();
    onDecide(approve, text === "" ? null : text);
  };

  return (
    <li className="approval" data-approval={approval.approval_id} data-status={approval.status}>
      <div className="approval__head">
        <button
          type="button"
          className="approval__quote num"
          aria-label={translate(locale, "approvals.open_quote", { quote_id: approval.quote_id })}
          onClick={() => {
            onOpenQuote(approval.quote_id);
          }}
        >
          {approval.quote_id}
        </button>
        <StateBadge
          tone={state.tone}
          icon={state.tone === "ok" ? <Icon name="check" /> : undefined}
        >
          {translate(locale, state.key)}
        </StateBadge>
        <span className="approval__id num">{approval.approval_id}</span>
      </div>

      <FieldList
        fields={[
          {
            field: "carrier",
            label: translate(locale, "approvals.carrier"),
            value: approval.carrier_name,
          },
          {
            field: "location",
            label: translate(locale, "quote.location"),
            value: approval.location_label,
          },
          {
            field: "limit",
            label: translate(locale, "quote.limit"),
            value: formatMoney(approval.limit.amount_cents, locale),
          },
          {
            field: "premium",
            label: translate(locale, "approvals.premium"),
            value: formatMoney(approval.premium.amount_cents, locale),
          },
          {
            field: "requested",
            label: translate(locale, "approvals.requested"),
            value: formatDate(approval.requested_at, locale),
          },
        ]}
      />

      {approval.status === "pending" && (
        <>
          <Note tone="wait" icon={<Icon name="clock" />}>
            {translate(locale, "approvals.you_decide")}
          </Note>
          <div className="approval__note">
            <label htmlFor={noteId}>{translate(locale, "approvals.note")}</label>
            <textarea
              id={noteId}
              rows={2}
              value={note}
              aria-describedby={countId}
              aria-invalid={tooLong ? true : undefined}
              onChange={(event) => {
                setNote(event.target.value);
              }}
            />
            <p
              id={countId}
              className="approval__count num"
              data-over={tooLong ? "true" : undefined}
              role={tooLong ? "alert" : undefined}
            >
              {tooLong
                ? translate(locale, "approvals.note_too_long", {
                    max: formatNumber(NOTE_MAX, locale),
                  })
                : translate(locale, "approvals.note_count", {
                    count: formatNumber(note.length, locale),
                    max: formatNumber(NOTE_MAX, locale),
                  })}
            </p>
          </div>
          <div className="approval__actions">
            <Button
              variant="approve"
              disabled={busy || tooLong}
              onClick={() => {
                decide(true);
              }}
            >
              <Icon name="check" />
              {translate(locale, "approvals.approve")}
            </Button>
            <Button
              variant="reject"
              disabled={busy || tooLong}
              onClick={() => {
                decide(false);
              }}
            >
              {translate(locale, "approvals.reject")}
            </Button>
          </div>
        </>
      )}

      {approval.status === "approved" && (
        <DeliveryProgress
          delivery={approval.delivery}
          attempts={attempts}
          onRedeliver={onRedeliver}
          busy={busy}
        />
      )}

      {approval.status === "rejected" && (
        <Note tone="neutral" icon={<Icon name="close" />} data-closed="true">
          {translate(locale, "approvals.rejected")}
        </Note>
      )}

      {problem !== null && (
        <p className="approval__problem" role="alert" data-problem={problem}>
          {translateProblem(problem, locale)}
        </p>
      )}
    </li>
  );
}
