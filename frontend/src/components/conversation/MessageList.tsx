import { useEffect, useMemo, useRef, type ReactNode } from "react";

import { translate, useI18n } from "../../i18n";
import { translateProblem, translateValue } from "../../i18n/coded";
import type { SessionState, ToolRow as ToolRowState } from "../../state/session";
import { Button } from "../common/Button";
import { Icon } from "../common/Icon";
import { Note } from "../common/Note";
import { Spinner } from "../common/Spinner";
import { AgentMessage } from "./AgentMessage";
import type { OpenFigure } from "./Figure";

interface MessageListProps {
  session: SessionState;
  onOpen: OpenFigure;
  /** Shown instead of the messages while the conversation is empty (the first run). */
  empty?: ReactNode;
}

/** For each message, the finished tool rows of the conversation up to and including it. */
function resultsUpTo(session: SessionState): ToolRowState[][] {
  const all: ToolRowState[] = [];
  return session.messages.map((message) => {
    all.push(...message.tools.filter((row) => row.status !== "running"));
    return [...all];
  });
}

/** The tools that had completed when the last turn broke off. */
function completedTools(session: SessionState): string[] {
  if (session.error !== null) return session.error.completed;
  const last = session.messages[session.messages.length - 1];
  if (last === undefined || last.role !== "assistant") return [];
  return last.tools.filter((row) => row.status === "ok").map((row) => row.tool);
}

/**
 * The conversation, announced politely as it grows. After the messages come the notes about how
 * the last turn ended: an interruption with what had completed, a limit, a pending approval.
 */
export function MessageList({ session, onOpen, empty }: MessageListProps) {
  const { locale } = useI18n();
  const box = useRef<HTMLDivElement>(null);
  const results = useMemo(() => resultsUpTo(session), [session]);

  // The newest content stays in view, unless the visitor scrolled up to read. The first run is
  // read from its top.
  const pinned = useRef(true);
  const hasMessages = session.messages.length > 0;
  useEffect(() => {
    const element = box.current;
    if (element !== null && hasMessages && pinned.current) element.scrollTop = element.scrollHeight;
  }, [hasMessages, session.messages, session.streaming]);

  const last = session.messages[session.messages.length - 1];
  const working =
    session.streaming &&
    (last === undefined ||
      last.role === "user" ||
      (last.text === "" && !last.tools.some((row) => row.status === "running")));

  // A turn can end with no text and no tool call (a refusal with no text): there is nothing to
  // put in a bubble, so the list says so in one line instead.
  const isBlank = (message: SessionState["messages"][number]) =>
    message.role === "assistant" &&
    message.text.trim() === "" &&
    message.tools.length === 0 &&
    message.flagged.length === 0;
  const broken = session.error !== null || session.interrupted;
  const unanswered =
    !session.streaming &&
    !broken &&
    last !== undefined &&
    (isBlank(last) || (last.role === "user" && session.stopReason === "end_turn"));
  // A restored conversation that ends with the visitor's message: the answer was cut by a reload
  // or a lost connection, and the server keeps no part of a cut answer. Nothing is streaming, so
  // the visitor is told to send the message again.
  const answerLost =
    session.mode === "live" &&
    !session.streaming &&
    !broken &&
    session.stopReason === null &&
    last !== undefined &&
    last.role === "user";
  const completed = broken ? completedTools(session) : [];
  const limit =
    session.stopReason === "tool_limit" || session.stopReason === "budget"
      ? session.stopReason
      : null;

  return (
    <div
      ref={box}
      className="msgs"
      role="log"
      aria-live="polite"
      aria-label={translate(locale, "chat.messages")}
      tabIndex={0}
      onScroll={(event) => {
        const { scrollHeight, scrollTop, clientHeight } = event.currentTarget;
        pinned.current = scrollHeight - scrollTop - clientHeight < 48;
      }}
    >
      {!hasMessages && empty}
      {session.messages.map((message, at) =>
        message.role === "user" ? (
          <div key={message.id} className="msg msg--user">
            <span className="sr-only">{translate(locale, "chat.you")}</span>
            <p className="msg__text">{message.text}</p>
          </div>
        ) : isBlank(message) ? null : (
          <AgentMessage
            key={message.id}
            message={message}
            toolResults={results[at] ?? []}
            onOpen={onOpen}
          />
        ),
      )}
      {unanswered && (
        <p className="msg__unanswered" data-note="no-answer">
          {translate(locale, "chat.no_answer")}
        </p>
      )}
      {answerLost && (
        <Note tone="warn" icon={<Icon name="warn" />} role="status" data-note="answer-lost">
          {translate(locale, "chat.answer_lost")}
        </Note>
      )}
      {working && (
        <p className="msg__working">
          <Spinner label={translate(locale, "chat.working")} />
        </p>
      )}
      {broken && (
        <Note tone="warn" icon={<Icon name="warn" />} data-note="interrupted">
          {session.error !== null
            ? translateProblem(session.error.code, locale)
            : translate(locale, "chat.interrupted")}{" "}
          {completed.length === 0
            ? translate(locale, "chat.completed_none")
            : translate(locale, "chat.completed", {
                tools: completed.map((tool) => translateValue("toolname", tool, locale)).join(", "),
              })}
        </Note>
      )}
      {limit !== null && (
        <Note tone="warn" icon={<Icon name="warn" />} data-note="limit">
          {translate(locale, `stop.${limit}`)}
        </Note>
      )}
      {session.pendingApproval !== null && !session.streaming && (
        <Note tone="wait" icon={<Icon name="clock" />} data-note="approval">
          {translate(locale, "chat.approval")}{" "}
          <Button
            variant="link"
            onClick={() => {
              onOpen("approvals", null);
            }}
          >
            {translate(locale, "chat.open_approvals")}
          </Button>
        </Note>
      )}
    </div>
  );
}
