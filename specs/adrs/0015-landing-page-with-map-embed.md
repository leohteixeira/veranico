# 0015. Landing page in the portfolio repository with a live map embed

Status: Accepted (2026-11-10)

## Context

The original brief had no landing page. The owner's portfolio site is a separate repository (`portifolio-landing-page`, Next.js) and is where a visitor first meets the project. The page should show the real map, not a screenshot. The workspace rule is that repositories never import each other's source; they share capabilities over HTTP.

## Decision

Governs SPEC section 12.5 and the portfolio page of milestone M6 (section 18).

* The presentation page lives in the portfolio repository, not in this one.
* It embeds `/embed/map` from the application in an iframe.
* `/embed/map` is a read-only route with the map, the risk layer and the timeline for a region.
* Only this route may be framed, and only by the origins in configuration (`Content-Security-Policy: frame-ancestors`).
* Sharing is over HTTP. No source is imported or copied across the two repositories.

## Consequences

* The portfolio shows the live product, and there is one implementation of the map.
* The page depends on the deployed application. If the service is down, or the portfolio's origin is missing from the configured list, the embed is empty.
* One presentation change can need work in two repositories with separate releases.
* The embed route is a public surface of its own to design, test and keep read-only; its `frame-ancestors` header is checked in the M4 gate.
* The rest of the application stays unframeable, so the full workspace cannot be embedded elsewhere.
* The page going live is a human gate (H3 in the goal contract) and depends on the deploy gate (H2).

## Alternatives considered

* **A landing page inside the application:** duplicates the portfolio.
* **Copying the map code into the portfolio:** shares source across repositories, which the workspace rules forbid.
