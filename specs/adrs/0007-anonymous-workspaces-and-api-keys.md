# 0007. Anonymous workspace per browser and API keys per workspace

Status: Accepted (2026-11-10)

## Context

The original brief had one global approvals queue and shared broker keys. With an open demo (ADR 0006), that means visitors would see and approve each other's submissions. Isolation is needed, but a login is not acceptable: creating an account is friction for an evaluator who has a few minutes.

## Decision

Governs SPEC sections 10.1 and 10.2, and the approval rule of section 6.

* **Anonymous workspace:** each browser gets a random workspace id in a signed, HttpOnly cookie. Conversations, quotes, documents and approvals belong to a workspace and are visible only there. Workspace data expires automatically (Firestore TTL, default 14 days). The visitor acts as the human approver for submissions in their workspace.
* **Public API keys:** a visitor can create an API key for their workspace from the interface. The key is shown once and stored only as a hash. Requests to the public broker API authenticate with `Authorization: Bearer <key>` and act inside that workspace, so quotes created through the API appear in the same visitor's Quote and Approvals tabs. There is a rate limit per key. Keys expire with the workspace.
* **Approval:** only `POST /api/v1/approvals/{id}/decision`, called from a browser session that owns the quote's workspace, moves a quote out of `pending_approval`. No agent tool and no API key can.
* A request for a quote of another workspace is answered `not_found` (contracts, section 5).

## Consequences

* Visitors cannot see or decide each other's quotes, with no account to create.
* Clearing cookies loses the workspace. There is no way to recover it.
* All workspace data expires by TTL; nothing a visitor creates is permanent.
* An API key cannot approve, so a broker integrating through the API still needs the browser session for the approval step.
* Every route needs a workspace isolation test, and every workspace-scoped document needs `expires_at`.

## Alternatives considered

* **User accounts:** friction for an evaluator with a few minutes.
* **One shared demo key published with the landing link:** no isolation and no way to revoke it for one visitor.
* **Global approvals queue (the brief):** visitors would see and approve each other's submissions.
