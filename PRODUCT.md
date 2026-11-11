# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React, TypeScript (strict), Vite, TanStack Query, Leaflet with react-leaflet, Recharts, pnpm. The API client is generated from the FastAPI OpenAPI document. The backend is Python with FastAPI. Chosen by the project brief, not delegated. The design direction is Atlas, recorded in `.impeccable/surfaces/frontend-src-app-tsx.md`.

## Users

- **Primary user:** a broker structuring parametric weather cover for an agricultural client in Brazil. They arrive with an exposure in plain language (crop, place, peril, limit) and a client conversation to prepare for.
- **Cold visitor:** someone evaluating the project as a portfolio piece, with a few minutes and no insurance background assumed. They reach the app from the portfolio presentation page and must be able to run the flow without guessing what to type.

## Product Purpose

Veranico turns a described exposure ("coffee farm, worried about a dry spell during flowering, R$ 300k limit") into a backtested trigger, an indicative price, a term sheet and a submission ready for human approval, in one conversation. Success is a broker reaching a defensible quote with every number traceable to its source, and a cold visitor completing the same flow unaided.

Pricing is illustrative. It is not actuarial or insurance advice, and the interface says so.

## Positioning

Basis risk made visible on the map. The ERA5-Land cell grid shows that the insured farm can sit in a cell that rarely triggers while a neighbouring cell triggers often, which is the main limitation of parametric cover and the thing a generic chat assistant cannot show.

Second proof: the agent never states a number that did not come from a deterministic tool in the same conversation, every price carries a `quote_id`, and only a human can approve a submission.

## Operating Context

- Laptop screen first; mobile is best effort.
- One working screen: a conversation with the agent beside a map, a season history chart, the quote, and an approvals queue.
- The map and the conversation are linked: resolving a location or backtesting an index moves and recolours the map; a priced quote pins its index definition to the region.
- Three showcase regions carry a full cell grid: coffee in Sul de Minas (MG), soybean around Sorriso (MT), sugarcane around Ribeirão Preto (SP). Any other point shows one cell.
- Daily weather history from 1950 through the last complete year.
- The landing page lives in the portfolio repository as the project's presentation page. This repository holds the working application only, which opens on the map.
- No login and no access gate. The chat is open to every visitor under a daily allowance per visitor; a code carried by the portfolio link only enlarges that allowance.
- Each browser gets an anonymous workspace. Its conversations, quotes and approvals are visible only there and expire automatically. The visitor acts as the human approver for their own submissions.
- The portfolio presentation page embeds the live map through a read-only `/embed/map` route.

## Capabilities and Constraints

- Perils: rainfall deficit and dry spells only. Index types `rainfall_below` and `dry_spell_above`.
- The interface renders numbers exactly as the API returns them and never recomputes them.
- A runtime check compares monetary values and percentages in each agent answer with the tool outputs of that conversation. A value without a source is flagged visibly on the message.
- Quote states: `draft`, `pending_approval`, `approved`, `rejected`, `submitted`. No agent action leaves `pending_approval`.
- Interface and term sheet in English and Brazilian Portuguese, with a language switch. The agent answers in the language the user writes in. Amounts are in BRL.
- The live agent has a per-visitor daily allowance and a global monthly spend ceiling. When either is reached the chat offers a recorded conversation to replay instead of an error; the map, the history and the public API keep working.
- Money is stored, served and displayed as integer BRL centavos; rates are fixed-decimal strings.
- Non-goals: real actuarial pricing, real carriers, user accounts, multi-tenancy, forecasting, other perils, retrieval over documents.
- Public address: the Cloud Run URL first, served at the root of its own origin; `veranico.leohteixeira.com` is an optional later mapping.

## Brand Commitments

- Name: Veranico, the Brazilian term for a dry spell inside the rainy season, which is the peril the main index measures.
- Required attribution, shown legibly next to the map and in the footer: Copernicus Climate Change Service (ERA5-Land) and Open-Meteo; the two EOX basemaps (Terrain Light and Sentinel-2 cloudless) with the exact attribution text each one requires, taken from EOX's documentation before release.
- The pricing disclaimer is always visible in the footer.
- The satellite basemap is EOX Sentinel-2 cloudless under CC BY-NC-SA, so the demo is declared non-commercial in the README and in the interface. The source code is MIT.

## Evidence on Hand

- Real: ERA5-Land daily precipitation; deterministic backtest, simulation and premium outputs; agent evaluation pass rates once the suite runs.
- Absent, and not to be fabricated: customers, testimonials, carrier partnerships, actuarial validation, usage figures.
- Design previews made before the data pipeline exists use synthetic values and must be labelled synthetic.

## Product Principles

1. The map explains the risk before the agent prices it.
2. Every number has a source the user can open.
3. The agent proposes; a human approves.
4. State the limits of the method next to the result, not in a separate page.
5. Data and tile licences are part of the design.
