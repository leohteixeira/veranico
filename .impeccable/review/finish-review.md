# Finish review: application workspace and embed

- Date: 2026-11-11, on the working tree after plan 08 Task 13.
- Reviewer: a fresh agent with no build history, run from the Impeccable finish-reviewer role
  (`reference/degraded/finish-reviewer.md`), because the harness has no shipped
  `impeccable-v2-finish-reviewer` agent. It read the captures and sampled the sources; it had no
  browser.
- Build path: code-led, user-pinned direction (Atlas). No approved comp and no QUALITY BAR card;
  the planning preview in `frontend/design-reference/` served as the critique reference.
- Captures, in this folder, from the production build with real EOX tiles and SYNTHETIC weather
  fixtures (labelled synthetic on screen): `desktop.png`, `mobile.png`, `desktop-dark-quote.png`,
  `mobile-dark-quote.png`. Remake them with
  `E2E_REVIEW=1 E2E_LIVE_TILES=1 pnpm exec playwright test review-captures` from `frontend/`.
- Detector: `impeccable detect --json frontend/src`, run once. One warning (`layout-transition`,
  a width transition on the tabs card), removed. No blocking finding.

## Disposition

**disposition: fix**

The word is the reviewer's and is reported as returned. The decision on this review is the
owner's (human gate H3) and is **open**.

## Reviewer's sections, as returned

### persistence

Pass. `PRODUCT.md` exists; the build is code-led, so no `.impeccable/build/` is expected; no comp
round and no approval is owed; FORM carries the dealt seed key `eac09ab5` and records the user's
pin of Atlas over it. DESIGN.md was absent at review time, as expected on a new world.

### fidelity

Judged against the contract's FIRST VIEWPORT and OWN-WORLD (no comp, so no element matrix against
the preview).

| Element | Verdict |
| --- | --- |
| Topology: map stage, top row, conversation left, tabs right, timeline bottom | match |
| Top row: wordmark, region, basemap, render, language | match |
| Theme switch in the top row | adaptation (the brief's dark-theme decision) |
| Conversation card: six segments, tool rows, composer | match |
| Tabs card open on Risk: figure, neighbour range, legend, three-by-three | match |
| Timeline: one bar per season, payout marks, attribution and disclaimer inside | match |
| Map notes card (synthetic label, grid count, smoothing statement) | adaptation (brief and PRODUCT) |
| Tabs card widening to 500px off Risk | adaptation, uncited by the reviewer |
| Signature: continuous surface with grid hairlines | match in light, contradicted in dark |
| Signature: surface meets the cube frame | contradicted (the wash feathers to transparent inside the frame) |
| Signature: hover cell with measured leg | present in code, not captured |
| Cells switch | match |
| TYPE | match |
| MATERIAL | match in light, contradicted in dark (the top ramp class is an opaque slab) |
| GROUND, light | match |
| GROUND, dark | adaptation (the previewed night tokens the user confirmed) |
| Colour roles | partial (the quote identifier was plain ink) |
| Mobile reading order | contradicted against STORY and the cold visitor's task |

What the preview dared that the build did not: toponyms (town dots with haloed labels, a label on
the cube frame).

### ceiling

Unused devices of the world: lettering on the map (place names, graticule, scale bar); an authored
moment of motion; a label on the cube frame.

### material_fixes

1. Surface edge: run the wash at full strength to the cube frame instead of fading inside it.
2. Dark ramp: the top classes hide the satellite terrain and the bottom class nearly vanishes;
   rebalance so terrain shows through every class.
3. Toponyms: draw town names on the map and label the cube frame.
4. Mobile order: at 390px the conversation sits about 1,350px down with nothing pointing to it.
5. Orphaned punctuation after a figure button ("; one-in-ten payout" starting a line).
6. Quote identifier in deep teal, as the contract assigns.
7. Audit trail entries carry a 2px `border-left` stripe.
8. Motion: author one moment on the signature, honouring reduced motion.

### keep

Real terrain reading through a single sand-to-brick wash with the hairline grid, under solid warm
index cards in Fraunces and Plex, with the synthetic label, attribution and disclaimer staying
beside the result.

## What was done with the fixes

Applied in one batch and recaptured over the same files. These were **not** re-scored by the
reviewer; the status below is the build's own statement, to be checked by the owner.

| Fix | Status | Note |
| --- | --- | --- |
| 5. Orphaned punctuation | applied | A figure and its closing punctuation are one unbreakable piece; covered by a test. Visible in `desktop-dark-quote.png`. |
| 6. Quote identifier colour | applied | Deep teal in the Quote tab, the approval queue and the conversation. |
| 7. Audit side stripe | applied | The rail is 1px. |

Left for the owner's decision, with the reason each was not changed here:

| Fix | Why it waits |
| --- | --- |
| 1. Surface edge | The feather at the cube's edge is how the approved preview draws the surface, and the preview is binding for this plan. Changing it is a change of the approved look. |
| 2. Dark ramp | The stops and their alphas are the preview's night paint, copied as approved. Rebalancing them is a change of the approved look. |
| 3. Toponyms | The API returns no place names for a region, and the specification lists none. It needs a data source and a decision; listed for `docs/NEXT_STEPS.md`. |
| 4. Mobile order | The specification fixes the stacked order as map, timeline, tabs, conversation (R-12.1-6). A jump to the conversation is an addition outside it; listed for `docs/NEXT_STEPS.md`. |
| 8. Motion | An authored moment on the map surface is new design work beyond the plan's polish; listed for `docs/NEXT_STEPS.md`. |

Known open items the reviewer was told about and did not restate: at 390px the map notes card
covers the lower part of the fitted region; cells are not reachable by keyboard on the map itself
(the Risk tab's neighbourhood is the accessible route).
