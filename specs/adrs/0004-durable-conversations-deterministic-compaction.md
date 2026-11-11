# 0004. Durable conversations with deterministic compaction and no retrieval

Status: Accepted (2026-11-10)

## Context

The original brief kept conversations in memory. Cloud Run instances are ephemeral and there can be two of them (SPEC section 17), so the next message of a conversation can land on an instance that has never seen it.

A long conversation also has to be shortened before it is sent to the model. Cost and behaviour have to stay reproducible, which rules out asking the model to summarise its own history.

There is no document corpus in this product. Every fact the agent states comes from a tool result.

## Decision

Governs SPEC section 9.2.

* Conversations are durable in Firestore (`assistant_conversations`, messages as a subcollection), scoped to the workspace, so any instance can continue a conversation.
* Every message and every full tool result is stored.
* Compaction is deterministic and done by code, not by the model. When the prompt estimate crosses a configured threshold, the oldest tool results are replaced in the prompt by a structured summary generated from the stored result (quote id, window, index definition, aggregates). The stored full results are untouched.
* There is no retrieval over documents.

## Consequences

* A conversation survives an instance restart and a reload of the page (`GET /conversations/{id}`).
* The same conversation history always produces the same prompt, so compaction can be covered by deterministic unit tests and adds no model cost.
* Every turn costs Firestore writes, and full tool results are kept until the workspace expires (TTL, default 14 days).
* The summary generator is code tied to the shape of each tool's output; when an output model changes, the generator changes with it.
* After compaction the model sees only the summarised fields of an old result. Anything else from that result is no longer in the prompt, although it stays stored.

## Alternatives considered

* **In-memory state (the brief):** lost when the instance stops, and absent on the second instance.
* **Sticky sessions:** do not help when the instance a session is pinned to goes away.
* **Summaries written by the model:** an extra model call per compaction (cost) and a non-deterministic result.
* **Vector retrieval:** there is nothing to retrieve; every fact comes from tools.
