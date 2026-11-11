import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef } from "react";

import { useApiClient } from "../api/client";
import { ApiProblem, networkProblem, toApiProblem } from "../api/problems";
import type { components } from "../api/schema";
import { consumeEvents, parseEventStream, readChunks, type AgentEvent } from "../api/sse";
import type { Locale } from "../i18n";
import { initialSession, sessionReducer, type SessionState } from "../state/session";
import { keys } from "./keys";
import { fetchConversation } from "./useConversation";
import { allowanceHeader, storeConversationId, storedConversationId } from "./storage";

type GridPoint = components["schemas"]["GridPoint"];

/** Tools whose result changes what the Quote and Approvals tabs show. */
const TOOLS_THAT_CHANGE_QUOTES = new Set(["price_cover", "draft_term_sheet", "request_submission"]);

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export interface Chat {
  session: SessionState;
  /** Sends one message. Ignored while a turn is in progress; never retried automatically. */
  send: (text: string, mapPoint?: GridPoint | null) => Promise<void>;
  /** Starts over: aborts the request in progress and forgets the conversation. */
  reset: () => void;
  /** Switches the session to replay mode, empty, ready for recorded events. */
  beginReplay: () => void;
  /** Feeds one recorded event to the session (replay mode). */
  pushReplayEvent: (event: AgentEvent) => void;
}

interface ChatOptions {
  /** Restore the stored conversation on mount (default true). */
  restore?: boolean;
}

/**
 * The agent session: one reducer fed by the event stream of `POST /chat`.
 *
 * `POST /chat` is sent once per user action and never retried: a retry would spend the visitor's
 * allowance and duplicate the message. A stream that closes without `done` unlocks the composer
 * and, when `started` had arrived, reloads the stored conversation once.
 */
export function useChat(locale: Locale, options: ChatOptions = {}): Chat {
  const restore = options.restore ?? true;
  const client = useApiClient();
  const queryClient = useQueryClient();
  const [session, dispatch] = useReducer(sessionReducer, undefined, () => initialSession("live"));
  const conversationId = useRef<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  // Leaving the page aborts the request in progress.
  useEffect(
    () => () => {
      inFlight.current?.abort();
    },
    [],
  );

  // A stored conversation identifier restores the conversation; an unknown one starts fresh.
  useEffect(() => {
    if (!restore) return;
    const stored = storedConversationId();
    if (stored === null) return;
    const controller = new AbortController();
    fetchConversation(client, stored, controller.signal)
      .then((conversation) => {
        conversationId.current = conversation.conversation_id;
        dispatch({ type: "restored", conversation });
      })
      .catch((error: unknown) => {
        if (error instanceof ApiProblem && error.status !== 0) storeConversationId(null);
      });
    return () => {
      controller.abort();
    };
  }, [client, restore]);

  const send = useCallback(
    async (text: string, mapPoint: GridPoint | null = null) => {
      if (inFlight.current !== null) return;
      const controller = new AbortController();
      inFlight.current = controller;
      dispatch({ type: "user_sent", text });
      let started: string | null = null;
      try {
        const { data, error, response } = await client.POST("/api/v1/chat", {
          params: { header: allowanceHeader() },
          body: {
            conversation_id: conversationId.current,
            message: text,
            locale,
            map_point: mapPoint,
          },
          parseAs: "stream",
          signal: controller.signal,
        });
        if (error !== undefined || !response.ok || data === undefined || data === null) {
          const problem = toApiProblem(error, response);
          dispatch({
            type: "problem",
            code: problem.code,
            traceId: problem.traceId,
            replayAvailable: problem.replayAvailable,
          });
          return;
        }
        const end = await consumeEvents(parseEventStream(readChunks(data)), (event) => {
          if (event.type === "started") {
            // Known before any other event, and stored at once, so a cut stream can be reloaded.
            started = event.data.conversation_id;
            conversationId.current = started;
            storeConversationId(started);
          }
          if (
            event.type === "tool_finished" &&
            event.data.status === "ok" &&
            TOOLS_THAT_CHANGE_QUOTES.has(event.data.tool)
          ) {
            void queryClient.invalidateQueries({ queryKey: keys.quotes });
            void queryClient.invalidateQueries({ queryKey: keys.approvals });
          }
          dispatch(event);
        });
        if (end === "cut") {
          dispatch({ type: "stream_cut" });
          if (started !== null) {
            // Once: show what the server stored of the interrupted turn.
            try {
              const conversation = await fetchConversation(client, started, controller.signal);
              dispatch({ type: "restored", conversation, afterCut: true });
            } catch (reloadError) {
              if (isAbort(reloadError)) return;
              // The interrupted turn stays as it was streamed.
            }
          }
        }
      } catch (error) {
        if (isAbort(error)) return;
        const problem = networkProblem();
        dispatch({ type: "problem", code: problem.code, traceId: null, replayAvailable: false });
      } finally {
        if (inFlight.current === controller) inFlight.current = null;
        void queryClient.invalidateQueries({ queryKey: keys.allowance });
      }
    },
    [client, locale, queryClient],
  );

  const stop = useCallback(() => {
    inFlight.current?.abort();
    inFlight.current = null;
    conversationId.current = null;
  }, []);

  const reset = useCallback(() => {
    stop();
    storeConversationId(null);
    dispatch({ type: "reset" });
  }, [stop]);

  const beginReplay = useCallback(() => {
    stop();
    dispatch({ type: "reset", mode: "replay" });
  }, [stop]);

  const pushReplayEvent = useCallback((event: AgentEvent) => {
    dispatch(event);
  }, []);

  return { session, send, reset, beginReplay, pushReplayEvent };
}
