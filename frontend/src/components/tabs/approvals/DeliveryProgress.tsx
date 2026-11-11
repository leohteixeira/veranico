import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { formatNumber } from "../../../i18n/format";
import { Button } from "../../common/Button";
import { Icon } from "../../common/Icon";
import { Note } from "../../common/Note";
import { Spinner } from "../../common/Spinner";

interface DeliveryProgressProps {
  delivery: components["schemas"]["DeliveryState"];
  /** Asks for the webhook to be sent again after an abandoned delivery. */
  onRedeliver: () => void;
  busy: boolean;
}

/**
 * Where the webhook of an approved submission stands: being delivered (with the attempts so far
 * and the last error code), delivered with the carrier's receipt, or abandoned with redelivery.
 */
export function DeliveryProgress({ delivery, onRedeliver, busy }: DeliveryProgressProps) {
  const { locale } = useI18n();
  const attempts = formatNumber(delivery.attempts, locale);
  // The error code is the API's own identifier, shown as data.
  const lastError =
    delivery.last_error_code === null ? null : (
      <>
        {" "}
        <span data-field="last_error">
          {translate(locale, "approvals.last_error", { code: delivery.last_error_code })}
        </span>
      </>
    );

  if (delivery.status === "delivered") {
    return (
      <Note tone="ok" icon={<Icon name="check" />} role="status" data-delivery="delivered">
        {translate(locale, "approvals.delivered", { receipt_id: delivery.receipt_id ?? "" })}
      </Note>
    );
  }

  if (delivery.status === "abandoned") {
    return (
      <>
        <Note tone="danger" icon={<Icon name="warn" />} role="status" data-delivery="abandoned">
          {translate(locale, "approvals.abandoned", { count: attempts })}
          {lastError}
        </Note>
        <div className="approval__actions">
          <Button variant="ghost" size="sm" onClick={onRedeliver} disabled={busy}>
            {busy ? <Spinner /> : <Icon name="refresh" />}
            {translate(locale, "approvals.redeliver")}
          </Button>
        </div>
      </>
    );
  }

  return (
    <Note tone="wait" icon={<Spinner />} role="status" data-delivery={delivery.status}>
      {translate(locale, "approvals.delivering")}
      {delivery.attempts > 0 && (
        <>
          {" "}
          <span data-field="attempts">
            {translate(
              locale,
              delivery.attempts === 1 ? "approvals.attempts.one" : "approvals.attempts.other",
              { count: attempts },
            )}
          </span>
        </>
      )}
      {lastError}
    </Note>
  );
}
