/**
 * What the mock API does with `POST /chat`. Every other route behaves the same in all scenarios.
 *
 * - `happy`: the four turns of the happy path, one per request.
 * - `flagged`: an answer with a figure the grounding check flags.
 * - `error`: the model fails after the first tool (`error`, then `done`).
 * - `cut`: the stream closes in the middle of the first turn, without `done`.
 * - `exhausted`: the request is refused with `allowance_exhausted` and the replay offer.
 * - `ceiling`: the request is refused with `spend_ceiling_reached` and the replay offer.
 */
export const SCENARIOS = ["happy", "flagged", "error", "cut", "exhausted", "ceiling"] as const;

export type Scenario = (typeof SCENARIOS)[number];

export const DEFAULT_SCENARIO: Scenario = "happy";

/** The scenario named by `?mock=<name>` in the address, or the default. */
export function scenarioFrom(search: string): Scenario {
  const name = new URLSearchParams(search).get("mock");
  return SCENARIOS.find((scenario) => scenario === name) ?? DEFAULT_SCENARIO;
}
