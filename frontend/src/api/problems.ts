import type { components } from "./schema";

export type Problem = components["schemas"]["Problem"];

/** Codes the interface gives to failures that carry no problem document. */
export const NETWORK_CODE = "network";
export const UNKNOWN_CODE = "unknown";

const REPLAY_CODES = new Set(["allowance_exhausted", "spend_ceiling_reached"]);

/** A refused or failed request. The interface shows the translated `code`, never API prose. */
export class ApiProblem extends Error {
  readonly code: string;
  readonly status: number;
  readonly traceId: string | null;
  /** True when the live agent is unavailable to this visitor and the recording can be played. */
  readonly replayAvailable: boolean;

  constructor(code: string, status: number, traceId: string | null, replayAvailable: boolean) {
    super(code);
    this.name = "ApiProblem";
    this.code = code;
    this.status = status;
    this.traceId = traceId;
    this.replayAvailable = replayAvailable;
  }
}

export function isProblem(value: unknown): value is Problem {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    typeof value.code === "string" &&
    "status" in value &&
    typeof value.status === "number"
  );
}

/** The problem of a non-2xx answer; a body that is not a problem document becomes `unknown`. */
export function toApiProblem(error: unknown, response: Response): ApiProblem {
  if (isProblem(error)) {
    const traceId =
      typeof error.trace_id === "string" && error.trace_id !== "" ? error.trace_id : null;
    return new ApiProblem(
      error.code,
      response.status,
      traceId,
      error.replay_available === true && REPLAY_CODES.has(error.code),
    );
  }
  return new ApiProblem(UNKNOWN_CODE, response.status, null, false);
}

/** A request that got no answer at all. */
export function networkProblem(): ApiProblem {
  return new ApiProblem(NETWORK_CODE, 0, null, false);
}

interface ApiResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** The body of a successful typed call, or a thrown `ApiProblem`. */
export function unwrap<T>(result: ApiResult<T>): T {
  if (result.error !== undefined || !result.response.ok || result.data === undefined) {
    throw toApiProblem(result.error, result.response);
  }
  return result.data;
}
