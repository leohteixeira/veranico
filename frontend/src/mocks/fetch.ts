import { setApiTransport } from "../api/client";
import { createMockState, handle, type MockState } from "./handlers";
import { scenarioFrom } from "./scenarios";

/** A `fetch` for the typed client that answers from the mock handlers. */
export function createMockFetch(state: MockState): (request: Request) => Promise<Response> {
  return (request) => handle(request, state);
}

/** Milliseconds between stream chunks in the browser, so the conversation visibly streams. */
const DEVELOPMENT_CHUNK_DELAY_MS = 60;

/**
 * Makes the application's client answer from the mock layer. Development only: `main.tsx` calls
 * this when `VITE_API_MOCK=1`, and `?mock=<scenario>` in the address picks the scenario.
 */
export function installMockApi(search: string): MockState {
  const state = createMockState(scenarioFrom(search), DEVELOPMENT_CHUNK_DELAY_MS);
  setApiTransport(createMockFetch(state));
  return state;
}
