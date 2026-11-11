import { translate, useI18n } from "../../i18n";
import { Button } from "../common/Button";
import { Icon } from "../common/Icon";
import { Note } from "../common/Note";

interface ReplayBannerProps {
  ended: boolean;
  onPlayAgain: () => void;
}

/** Stays above a recording for as long as it is shown, so it is never read as a live answer. */
export function ReplayBanner({ ended, onPlayAgain }: ReplayBannerProps) {
  const { locale } = useI18n();
  return (
    <Note tone="wait" icon={<Icon name="play" />} className="replay-banner" role="status">
      {translate(locale, "chat.replay.banner")}
      {ended && (
        <>
          {" "}
          {translate(locale, "chat.replay.ended")}{" "}
          <Button variant="link" onClick={onPlayAgain}>
            {translate(locale, "chat.replay.again")}
          </Button>
        </>
      )}
    </Note>
  );
}
