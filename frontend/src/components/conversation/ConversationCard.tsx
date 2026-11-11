import type { components } from "../../api/schema";
import { translate, useI18n } from "../../i18n";
import { translateProblem } from "../../i18n/coded";
import { formatNumber } from "../../i18n/format";
import type { SessionState } from "../../state/session";
import { Button } from "../common/Button";
import { Card } from "../common/Card";
import { Composer } from "./Composer";
import type { ExampleRequest } from "./exampleRequests";
import { Examples } from "./Examples";
import type { OpenFigure } from "./Figure";
import { MessageList } from "./MessageList";
import { ProgressBar } from "./ProgressBar";
import { ReplayBanner } from "./ReplayBanner";
import { ReplayOffer, type ReplayStatus } from "./ReplayOffer";

import "./conversation.css";

type Schemas = components["schemas"];
type GridPoint = Schemas["GridPoint"];

export interface ReplayControl {
  status: ReplayStatus;
  /** Loads the recording in the visitor's language and plays it from the start. */
  play: () => void;
}

export interface ConversationCardProps {
  session: SessionState;
  /** `GET /allowance`, or `null` until it answers. The API gives what is left, not a total. */
  allowance: Schemas["Allowance"] | null;
  examples: readonly ExampleRequest[];
  replay: ReplayControl;
  /** A point the visitor marked on the map, waiting to go with the next request. */
  mapPoint?: GridPoint | null;
  onClearMapPoint?: () => void;
  onSend: (text: string, mapPoint: GridPoint | null) => void;
  /** Start over: forget the conversation (and leave a recording). */
  onReset: () => void;
  /** A figure, a quote identifier or a note asks for a tab, and maybe a field in it. */
  onOpen: OpenFigure;
  className?: string;
}

function noop(): void {
  // No point to clear when the card is used without the map.
}

/**
 * The conversation with the agent: progress and allowance on top, the messages with their tool
 * calls, and the composer. When the live agent is unavailable the composer gives way to the
 * recording, which is always labelled as one.
 */
export function ConversationCard({
  session,
  allowance,
  examples,
  replay,
  mapPoint = null,
  onClearMapPoint = noop,
  onSend,
  onReset,
  onOpen,
  className,
}: ConversationCardProps) {
  const { locale } = useI18n();
  const replaying = session.mode === "replay";
  const exhausted = session.replayOffered || allowance?.messages_left === 0;
  const started = session.messages.length > 0 || replaying;

  return (
    <Card
      as="section"
      className={className === undefined ? "conversation" : `conversation ${className}`}
      aria-label={translate(locale, "chat.title")}
      data-mode={session.mode}
    >
      <header className="conversation__head">
        <div className="conversation__title-row">
          <h2 className="conversation__title">{translate(locale, "chat.title")}</h2>
          <Button variant="link" onClick={onReset} disabled={!started && !session.streaming}>
            {translate(locale, "chat.restart")}
          </Button>
        </div>
        <ProgressBar step={session.step} />
        {allowance !== null && (
          <p className="conversation__meter" data-left={allowance.messages_left}>
            {translate(
              locale,
              allowance.messages_left === 1 ? "chat.meter.one" : "chat.meter.other",
              {
                count: formatNumber(allowance.messages_left, locale),
              },
            )}
          </p>
        )}
      </header>

      {replaying && (
        <div className="conversation__banner">
          <ReplayBanner ended={replay.status === "ended"} onPlayAgain={replay.play} />
        </div>
      )}

      <MessageList
        session={session}
        onOpen={onOpen}
        empty={
          replaying || exhausted ? undefined : (
            <Examples
              examples={examples}
              disabled={session.streaming}
              onPick={(text) => {
                onSend(text, null);
              }}
            />
          )
        }
      />

      {!replaying && (
        <footer className="conversation__foot">
          {exhausted ? (
            <ReplayOffer
              reason={
                session.problem !== null
                  ? translateProblem(session.problem.code, locale)
                  : translate(locale, "admission.visitor_allowance")
              }
              status={replay.status}
              onPlay={replay.play}
            />
          ) : (
            <Composer
              locked={session.streaming}
              problem={session.problem}
              rejectedText={session.rejectedText}
              mapPoint={mapPoint}
              onClearMapPoint={onClearMapPoint}
              onSend={onSend}
            />
          )}
        </footer>
      )}
    </Card>
  );
}
