---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: []
---

# Surface brief: application workspace

## Scope and mode

The single working screen of the Veranico application (the map as the stage, with the conversation, the risk panel and the season timeline over it) and the read-only `/embed/map` route. Visitor mode: Operate. The landing page is a separate surface in the portfolio repository and reuses this world in Persuade mode.

## Audience, job, task

- A broker preparing a client conversation, and a cold visitor evaluating the project in a few minutes.
- Task: describe an exposure, read the basis risk on the map, reach a priced quote, draft the term sheet, request a submission and approve it as the human.
- Proof carried by the screen: the insured cell against its neighbours; every figure tied to a `quote_id`; the approval step owned by a person.
- The chat is open without an access code. Each visitor has a small daily allowance; when it or the global ceiling runs out, the chat offers a recorded replay instead of an error.
- Conversations, quotes and approvals are scoped to an anonymous per-browser workspace.

## States that must be designed

First run with example requests; agent streaming with tool cards; a figure flagged as not found in tool outputs; allowance or ceiling reached with replay offered; point outside the showcase regions (one cell, note about the regional view); pending approval; approved and delivered; rejected; webhook delivery retrying; loading and failed data, including a basemap that has not loaded.

## Direction contract

THESIS: A printed atlas page that answers back: the real terrain is the page, the risk is a wash of colour laid over it, and the working panels sit on it like index cards. Refuses the schematic grid of flat squares on blank paper, which the user rejected as ugly and unlike a map.

OWN-WORLD: Light relief basemap (EOX Terrain Light) by default and Sentinel-2 cloudless as the satellite option, both real tiles. Trigger frequency is one sand-to-brick ramp; a season's anomaly runs brick (dry) to teal (wet) through a neutral midpoint. Warm white cards with soft elevation and 16px radii on a parchment ground. Deep teal for actions, the active step and the quote identifier; brick for payouts; green for approved. Fraunces for titles and large figures, IBM Plex Sans for text, IBM Plex Mono for identifiers and tool names.

STORY: The visitor sees the farm on a real map, sees the risk change colour a few kilometres away, watches the agent price the cover with every figure tagged to its quote, and approves the submission personally.

FIRST VIEWPORT: The map fills the stage. Floating on it: a top row with the wordmark, region selector, basemap switch (satellite or relief), render switch (surface or cells) and language; a conversation card on the left with a six-segment progress bar, collapsed tool rows and the composer; a card on the right with tabs Risk, History, Quote, Approvals, open on Risk with the insured cell's figure, the range of its eight neighbours, the legend and a three-by-three neighbourhood; a season timeline card at the bottom, one bar per season with payout seasons marked, draggable. Attribution and the pricing disclaimer sit in the timeline card.

FORM: Atlas, a user-pinned direction chosen from three rendered alternatives (Noturno, Atlas, Campo) after the user rejected the dealt direction Course over Terrain (seed key eac09ab5). Signature move: the risk as a continuous surface over real terrain, with the ERA5-Land grid as hairlines, the exact cell revealed on hover with a measured leg from the farm, and a Cells switch that shows the raw 0.1° data.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Decisions carried by this brief

- The map opens on the continuous surface; cells are one switch away, and the interface states that the smoothing is visual only.
- The season view defaults to the season most evenly split between dry and wet cells, because it shows basis risk at a glance.
- The dark theme keeps Atlas's type and card anatomy over a darkened satellite basemap with a luminous ramp (the treatment previewed as Noturno).

## Reference

The approved planning preview is the artifact published in the planning session (three directions; Atlas is the second). Its weather values are synthetic; its basemap imagery is real.
