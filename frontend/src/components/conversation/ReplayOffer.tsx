import { translate, useI18n } from "../../i18n";
import { Button } from "../common/Button";
import { Icon } from "../common/Icon";
import { Note } from "../common/Note";
import { Spinner } from "../common/Spinner";

/** Where the recording is: not asked for, loading, being played, played to the end, or failed. */
export type ReplayStatus = "idle" | "loading" | "playing" | "ended" | "failed";

interface ReplayOfferProps {
  /** Why the live agent is unavailable, already translated. */
  reason: string;
  status: ReplayStatus;
  onPlay: () => void;
}

/** Takes the composer's place when the live agent is unavailable: the recording can be played. */
export function ReplayOffer({ reason, status, onPlay }: ReplayOfferProps) {
  const { locale } = useI18n();
  return (
    <div className="replay-offer">
      <Note tone="warn" icon={<Icon name="warn" />}>
        {reason} {translate(locale, "chat.replay.offer")}
      </Note>
      {status === "failed" && (
        <p className="replay-offer__failed" role="alert">
          {translate(locale, "chat.replay.failed")}
        </p>
      )}
      <div className="replay-offer__actions">
        <Button onClick={onPlay} disabled={status === "loading"}>
          {status === "loading" ? <Spinner /> : <Icon name="play" />}
          {translate(
            locale,
            status === "loading"
              ? "chat.replay.loading"
              : status === "failed"
                ? "action.retry"
                : "chat.replay.play",
          )}
        </Button>
      </div>
    </div>
  );
}
