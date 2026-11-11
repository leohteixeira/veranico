# 0009. Haiku 5.5 and spend ceilings in dollars

Status: Accepted (2026-11-10)

## Context

The original brief used a Sonnet model and a daily token budget. Two things changed the choice:

* Cost is a standing constraint from the owner. The agent's task is structured tool calling; the deterministic tools do the numeric work, and the agent is not allowed to compute figures.
* A token budget does not map to money. Input, output and cache tokens have different prices, so the same token count can cost different amounts.

## Decision

Governs SPEC sections 9.1 and 10.3, and the cost attribute of section 15.

* The agent model comes from `AGENT_MODEL`, default `claude-haiku-5-5`.
* The spend ceiling is in US dollars, computed from token usage with prices read from configuration: default US$ 10 per month and US$ 0.50 per day across all visitors. The check runs before each model call; the charge is recorded after it.
* Cost per call is computed from token counts with the same configured prices and recorded on the `llm.call` span.
* A spend limit is also set in the Anthropic Console, as the outer bound that also covers evaluation runs.
* The current model identifier and the token prices are not stated here. They must be verified in official documentation before coding (SPEC section 21), and the prices live in configuration.

## Consequences

* The ceiling is expressed in the unit the owner cares about, and the same price table feeds the ledger and the traces.
* The evaluation suite (SPEC section 16.6, 90% pass rate over 3 epochs) is the guard on quality for the smaller model. If it fails, the model is changed by configuration and re-evaluated.
* The configured prices must be kept equal to the provider's published prices. If they drift, the ledger and the ceiling count the wrong amount; the Console limit is the bound that does not depend on them.
* A change of model is a configuration change, but it is not free: it needs a new evaluation run, which costs money, and a price check.

## Alternatives considered

* **A Sonnet model (the brief):** higher cost for a task that is structured tool calling over deterministic tools.
* **A daily token budget (the brief):** does not map to money across input, output and cache prices.
