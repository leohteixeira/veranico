# 0005. Runtime grounding check with a visible marker

Status: Accepted (2026-11-10)

## Context

The product's second proof is that the agent never states a number that did not come from a deterministic tool. The original brief checked this only in the evaluation suite. The chat is now open to the public (ADR 0006), so a live visitor could see an invented figure that no evaluation run ever observed.

## Decision

Governs SPEC section 9.5.

* After each agent answer, a pure function extracts every monetary value and percentage from the text (both locales) and looks for it in the tool results of that conversation and in the user's own messages. A figure is grounded when it equals such a value rounded to the precision the answer wrote it with.
* A value without a source produces a `grounding_flagged` event, a span attribute and a stored marker on the message. The interface marks the figure.
* The check does not block the stream.
* The same function is the `numbers_grounded` scorer in the evaluation suite. It lives in `assistant/domain`:
  `check_grounding(answer, tool_results, user_texts, locale) -> GroundingReport`.

The figure is flagged rather than blocked for two reasons: the text has already streamed when the check runs, and a false positive should not destroy an otherwise correct answer.

## Consequences

* The rule that is evaluated offline is the rule that runs in production; there is one implementation to test.
* The rounding rule and the number formats of both locales must be handled in this one function. A mistake there produces false flags or missed figures in both the runtime check and the scorer.
* The check detects; it does not prevent. A visitor can read an ungrounded figure before the marker appears.
* A flag is a visible admission of a possible error, shown to the same evaluators the demo is meant to convince.
* The check runs on every answer and needs the conversation's tool results, which is one reason full tool results are stored (ADR 0004).

## Alternatives considered

* **Evaluation only (the brief):** says nothing about the answer a live visitor is reading.
* **Blocking or withholding the answer:** the text has already streamed, and a false positive would destroy a correct answer.
