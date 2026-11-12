import { translate, useI18n } from "../../i18n";
import { Button } from "../common/Button";
import { Spinner } from "../common/Spinner";

export type DataStatus = "ready" | "loading" | "failed";

interface TabStateProps {
  /** `loading` or `failed`; a tab with its data renders its content instead. */
  status: Exclude<DataStatus, "ready">;
  onRetry?: () => void;
}

/** What a tab shows while its data loads, or when it did not load. */
export function TabState({ status, onRetry }: TabStateProps) {
  const { locale } = useI18n();
  if (status === "loading") {
    return (
      <div className="tab-state" data-state="loading">
        <Spinner label={translate(locale, "state.loading")} />
      </div>
    );
  }
  return (
    <div className="tab-state" data-state="failed" role="alert">
      <span>{translate(locale, "state.failed")}</span>
      {onRetry !== undefined && (
        <Button variant="link" onClick={onRetry}>
          {translate(locale, "action.retry")}
        </Button>
      )}
    </div>
  );
}

/** A tab with nothing to show yet: one sentence saying what will fill it. */
export function TabEmpty({ children }: { children: string }) {
  return (
    <p className="tab-state tab-state--empty" data-state="empty">
      {children}
    </p>
  );
}
