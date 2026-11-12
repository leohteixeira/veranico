# 0020. Error codes `unauthorized` and `internal_error`

## Status

Accepted on 2026-11-12. It amends the frozen list of error codes in the contracts (section 1 of `docs/veranico/contracts.md` in the workspace repository), as SPEC section 3.1 requires for a contract change.

## Context

The pre-deploy end-to-end campaign (run `20261111T232853Z`) found two gaps against the specification:

* A request to the public broker API with a missing, malformed or unknown key answered 403 `forbidden` without a `WWW-Authenticate` header. RFC 9110 (section 15.5.2) and RFC 6750 (section 3) reserve 401 with `WWW-Authenticate: Bearer` for a request that carries no valid credential; 403 is for a known principal that is not allowed.
* An unexpected exception inside a tool escaped the agent loop. The stream ended without the `error` and `done` events of SPEC 9.1, and an unhandled exception on an HTTP route answered 500 as plain text instead of an RFC 9457 problem with a stable code (SPEC 11).

Neither case has a code in the frozen list, and the interface translates codes, never prose.

## Decision

1. `unauthorized`: HTTP 401 with `WWW-Authenticate: Bearer`, for a public API request whose key is missing, malformed or unknown. Only the HTTP layer translates the `forbidden` refusal of `access` into it; `forbidden` (403) keeps its meaning everywhere else, including the internal routes.
2. `internal_error`: not retryable. It is used as a tool error when a tool raises an unexpected exception, as the `error` event that ends a turn after an unexpected failure (followed by `done`), and as the problem code of a 500 answer. The message is generic and carries no paths or internals; the stack goes to the server log only.
3. Both codes are translated in English and Brazilian Portuguese.

## Consequences

* Broker clients see the standard challenge and can tell a bad key from a refused action.
* A defect or a failing store no longer leaves a tool row running or a stream open; the conversation stays usable after the failure.
* The frozen list in the workspace contracts document still lacks the two codes until the coordinator updates it; this ADR is the record of the change.
