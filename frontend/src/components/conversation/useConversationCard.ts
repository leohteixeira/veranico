import { useCallback, useMemo, useState } from "react";

import type { components } from "../../api/schema";
import { config } from "../../config";
import { useAllowance } from "../../hooks/useAllowance";
import { useChat } from "../../hooks/useChat";
import { useReplay } from "../../hooks/useReplay";
import { useI18n } from "../../i18n";
import type { SessionState } from "../../state/session";
import { useView } from "../../state/view";
import type { ConversationCardProps, ReplayControl } from "./ConversationCard";
import { exampleRequests } from "./exampleRequests";
import type { OpenFigure } from "./Figure";
import { prefersReducedMotion, useReplayPlayback, type PlaybackRun } from "./useReplayPlayback";

type GridPoint = components["schemas"]["GridPoint"];

interface ConversationOptions {
  /** Restore the stored conversation on mount (default true). */
  restore?: boolean;
  /** Overrides the system's reduced-motion preference (tests). */
  reducedMotion?: boolean;
}

interface Conversation {
  /** The agent session, for the live link between the conversation and the rest of the screen. */
  session: SessionState;
  /** Everything `ConversationCard` needs except the map point, which the shell owns. */
  card: Omit<ConversationCardProps, "mapPoint" | "onClearMapPoint" | "className">;
}

/**
 * Connects the conversation card to the agent session, the allowance, the recording and the view
 * store. The shell calls it once and also reads `session` for the live link.
 */
export function useConversationCard(options: ConversationOptions = {}): Conversation {
  const { locale } = useI18n();
  const { dispatch } = useView();
  const chat = useChat(locale, { restore: options.restore });
  const allowance = useAllowance();
  const [run, setRun] = useState<PlaybackRun | null>(null);
  const recording = useReplay(locale, run !== null);
  const playback = useReplayPlayback(recording.data, run, chat.beginReplay, chat.pushReplayEvent);

  const { send, reset } = chat;
  const reducedMotion = options.reducedMotion;
  const { refetch, isError } = recording;

  const onSend = useCallback(
    (text: string, mapPoint: GridPoint | null) => {
      void send(text, mapPoint);
    },
    [send],
  );

  const onReset = useCallback(() => {
    setRun(null);
    reset();
  }, [reset]);

  const onOpen = useCallback<OpenFigure>(
    (tab, key) => {
      dispatch({ type: "tab_opened", tab, highlight: key });
    },
    [dispatch],
  );

  const play = useCallback(() => {
    if (isError) void refetch();
    setRun((previous) => ({
      id: (previous?.id ?? 0) + 1,
      reducedMotion: reducedMotion ?? prefersReducedMotion(),
    }));
  }, [isError, refetch, reducedMotion]);

  let status: ReplayControl["status"] = "idle";
  if (run !== null) {
    if (recording.data === undefined) status = recording.isFetching ? "loading" : "failed";
    else status = playback.ended ? "ended" : "playing";
  }

  const examples = useMemo(() => exampleRequests(config.exampleCovers, locale), [locale]);

  return {
    session: chat.session,
    card: {
      session: chat.session,
      allowance: allowance.data ?? null,
      examples,
      replay: { status, play },
      onSend,
      onReset,
      onOpen,
    },
  };
}
