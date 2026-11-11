import { useMemo } from "react";

import { translate, useI18n } from "../../i18n";
import type { SessionMessage, ToolRow as ToolRowState } from "../../state/session";
import { Icon } from "../common/Icon";
import { Note } from "../common/Note";
import { Figure, type OpenFigure } from "./Figure";
import { linkFigures } from "./figures";
import { ToolRow } from "./ToolRow";

interface AgentMessageProps {
  message: SessionMessage;
  /** The finished tool rows of the conversation up to and including this answer. */
  toolResults: readonly ToolRowState[];
  onOpen: OpenFigure;
}

/** One answer: its tool calls, then its text with every figure linked to its source or marked. */
export function AgentMessage({ message, toolResults, onOpen }: AgentMessageProps) {
  const { locale } = useI18n();
  const paragraphs = useMemo(
    () =>
      message.text
        .split(/\n{2,}/)
        .filter((paragraph) => paragraph.trim() !== "")
        .map((paragraph) => linkFigures(paragraph, toolResults, message.flagged, locale)),
    [message.text, message.flagged, toolResults, locale],
  );
  const flaggedCount = message.flagged.length;

  return (
    <article className="msg msg--agent" data-message={message.id}>
      <span className="msg__who">{translate(locale, "app.name")}</span>
      {message.tools.length > 0 && (
        <ul className="tools">
          {message.tools.map((row) => (
            <ToolRow key={row.callId} row={row} />
          ))}
        </ul>
      )}
      {paragraphs.map((segments, at) => (
        <p key={at} className="msg__text">
          {segments.map((segment, index) =>
            segment.kind === "text" ? (
              segment.text
            ) : (
              <Figure key={index} segment={segment} onOpen={onOpen} />
            ),
          )}
        </p>
      ))}
      {flaggedCount > 0 && (
        <Note tone="warn" icon={<Icon name="warn" />} data-note="flagged">
          {translate(locale, flaggedCount === 1 ? "chat.flagged.one" : "chat.flagged.other", {
            count: flaggedCount,
          })}
        </Note>
      )}
    </article>
  );
}
