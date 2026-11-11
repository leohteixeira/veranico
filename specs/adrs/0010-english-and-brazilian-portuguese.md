# 0010. English and Brazilian Portuguese

Status: Accepted (2026-11-10)

## Context

The original brief was English only. The product is for Brazilian agriculture and is aimed at the Brazilian market, while the people evaluating it may read English. Both groups have to be able to use the interface, talk to the agent and read the term sheet.

## Decision

Governs SPEC section 13, rule 7 of section 9.3 and the term sheet of section 8.

* The interface exists in English and Brazilian Portuguese. The language is chosen from `?lang`, then the stored preference, then the browser language, and can be switched.
* The agent answers in the language the user writes in.
* The term sheet is rendered as one PDF per language.
* A recorded replay exists per language (SPEC section 9.6).
* Amounts are in BRL; number and date formatting follows the active locale.
* API field names, codes and logs are English only.
* Text for people (assumptions, audit actions, tool summaries, warnings, errors) crosses module boundaries as a code plus parameters (`Coded`), never as prose. Only presentation layers hold translated text: the HTTP problem mapper, the term sheet and the frontend. The interface translates problem codes, never English prose.

## Consequences

* Every user-facing string exists twice and both copies must be kept in step: the frontend catalogue, the term sheet, the replay fixtures.
* Number formatting by locale must not change values. `R$ 1.234,56` and `R$ 1,234.56` are the same figure, so the grounding check has to be locale aware (ADR 0005).
* A module cannot return a ready-made sentence. Each new message needs a code, parameters and a translation in every presentation layer that shows it.
* The evaluation suite carries a language check (`answers_in`) and one full flow in Portuguese.
* Logs and API codes stay in one language, so operation and integration do not depend on the visitor's locale.

## Alternatives considered

* **English only (the brief):** the product is for Brazilian agriculture and the Brazilian market.
* **Portuguese only:** evaluators may read English.
