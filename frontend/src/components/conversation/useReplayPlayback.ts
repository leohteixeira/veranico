import { useEffect, useState } from "react";

import type { AgentEvent } from "../../api/sse";

/**
 * How long the playback waits after an event, in milliseconds. The server sends a recording at
 * once; the pace is the browser's, close to how a live answer arrives.
 */
const PAUSE_AFTER: Readonly<Partial<Record<AgentEvent["type"], number>>> = {
  started: 250,
  user_message: 700,
  tool_started: 600,
  tool_finished: 300,
  text_delta: 45,
  done: 900,
};

export interface PlaybackRun {
  /** Changes for every playback, so the same recording can be played again. */
  id: number;
  /** The visitor prefers reduced motion: the whole recording is shown at once. */
  reducedMotion: boolean;
}

interface Playback {
  /** The run has shown every event. */
  ended: boolean;
}

/**
 * Plays recorded events into the session. `begin` empties the session into replay mode and `push`
 * feeds it one event; both must be stable. Nothing plays until `run` and `events` are both set.
 */
export function useReplayPlayback(
  events: readonly AgentEvent[] | undefined,
  run: PlaybackRun | null,
  begin: () => void,
  push: (event: AgentEvent) => void,
): Playback {
  const [endedRun, setEndedRun] = useState<number | null>(null);
  const runId = run?.id ?? null;
  const reducedMotion = run?.reducedMotion ?? false;

  useEffect(() => {
    if (runId === null || events === undefined) return;
    begin();
    let at = 0;
    let timer = 0;
    const step = () => {
      let pause = 0;
      if (reducedMotion) {
        for (const event of events) push(event);
        at = events.length;
      } else {
        const event = events[at];
        if (event !== undefined) {
          push(event);
          pause = PAUSE_AFTER[event.type] ?? 0;
        }
        at += 1;
      }
      if (at >= events.length) setEndedRun(runId);
      else timer = window.setTimeout(step, pause);
    };
    timer = window.setTimeout(step, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [events, runId, reducedMotion, begin, push]);

  return { ended: runId !== null && endedRun === runId };
}

/** Whether the visitor asked the system for reduced motion. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}
