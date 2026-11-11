# 0006. Open chat with visitor allowance, spend ceiling and recorded replay

Status: Accepted (2026-11-10)

## Context

The original brief required a demo access code before anyone could use the chat. The owner decided the chat should be open, because that is more attractive to recruiters and evaluators, and that spending should be limited another way. Cost remains a standing constraint.

## Decision

Governs SPEC sections 10.3 and 9.6. There is no login and no access gate.

* **Visitor allowance:** a per-visitor daily allowance for the live agent, keyed by a salted hash of the client IP. Default 2 conversations and 15 messages per day. A code carried by the portfolio link enlarges it (default 6 conversations and 60 messages); the code is not required for anything.
* **Spend ceiling:** in US dollars, computed from token usage with prices read from configuration. Default US$ 10 per month and US$ 0.50 per day across all visitors. The check runs before each model call; the charge is recorded after it.
* A maximum message length and a per-conversation token budget.
* **When the allowance or a ceiling is exhausted,** `POST /chat` answers with a problem document that carries `replay_available`, and the interface offers the recorded replay. The map, history, quotes and the public API keep working.
* **Recorded replay:** a recorded conversation of the full flow exists per language as a versioned fixture, produced from a real run and reviewed. It is served from `GET /api/v1/replays/{locale}` and clearly labelled as a recording. A replay creates no quote and no approval.
* A spend limit is also set in the Anthropic Console, as the outer bound that also covers evaluation runs.
* Raw IP addresses are never stored or logged.

## Consequences

* A visitor reaches the live agent with no code and no account.
* Abuse is bounded by money, not prevented. Once a ceiling is reached, every visitor gets the replay until it resets, including the evaluator the demo exists for.
* The IP-based allowance is imperfect: visitors on a shared network share one allowance.
* The charge is recorded after the call, so a ceiling can be passed by the cost of calls already in flight; the Console limit is the outer bound.
* The replays are fixtures to maintain: they are recorded from a real run, reviewed, and exist once per language.

## Alternatives considered

* **Required access code (the brief):** friction; most visitors would leave.
* **Login:** rejected for the same friction; see ADR 0007.
* **No limit:** unbounded cost.
