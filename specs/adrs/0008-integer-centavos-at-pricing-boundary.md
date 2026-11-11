# 0008. Integer centavos at the pricing boundary

Status: Accepted (2026-11-10)

## Context

The original brief did not say how money is represented. The same monetary figure appears in the API response, the term sheet PDF, the agent's text and the grounding check (ADR 0005), and the grounding check compares values. If each place rounded a float on its own, the figures would diverge by rounding and a correct answer could be flagged, or two documents could disagree by a centavo.

## Decision

Governs SPEC section 5.7.

* The numerical engine works in float64. Every monetary value leaving `pricing` is an integer number of BRL centavos, rounded once, half to even, at the module boundary. Everything stored, served and displayed is that integer. In the contracts this is `Money` (`amount_cents: int`, currency `BRL`).
* Rates and probabilities (rate on line, trigger frequency, probability of payout, p-value) leave as fixed-decimal strings with six decimal places (`Rate`).
* Physical quantities (millimetres, days) leave as numbers rounded to one decimal place.
* No module outside `pricing/domain` performs arithmetic on money. An architecture test bans `float` money fields in contracts and the use of `round(`, `Decimal(` and float arithmetic on `*_cents` values outside `pricing`.

## Consequences

* One rounding, in one place. The API, the PDF, the agent's text and the grounding check all read the same integer.
* The simulation still uses floats internally; exactness starts at the boundary, not inside the engine.
* Any new monetary figure, including a sum or difference of existing ones, must be computed inside `pricing` and added to its contract. Other modules and the frontend may only format.
* Rates are strings on the wire, so consumers parse them for display and never for arithmetic.
* The architecture test is a rule to maintain, and it will reject code that looks harmless (a `round(` on a `*_cents` value in another module).

## Alternatives considered

* **Float amounts across the boundary:** each consumer rounds on its own and the same figure diverges between the API, the PDF, the agent's text and the grounding check.
