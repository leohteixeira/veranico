---
name: Veranico
description: A printed atlas page that answers back; parametric rainfall cover priced on a real map.
colors:
  parchment: "#efeadf"
  card: "#fffdf8"
  soft: "#f5efe2"
  line: "#e7dfcf"
  line-strong: "#cbbfa8"
  ink: "#1b2428"
  ink-2: "#4b585f"
  ink-3: "#626e76"
  teal: "#0f5e63"
  teal-wash: "#dcecec"
  button: "#143c44"
  approved: "#1c7350"
  approved-wash: "#e0f1e8"
  warning: "#d39a12"
  warning-wash: "#fbf0cf"
  danger: "#b3261e"
  danger-wash: "#f9e1de"
  brick: "#b3472a"
  bar: "#c9c1b1"
  night-ground: "#0a0e13"
  night-card: "#121821"
  night-soft: "#232932"
  night-ink: "#eef2f6"
  night-ink-2: "#bac4ce"
  night-ink-3: "#8b97a4"
  night-teal: "#5cc8c4"
  night-teal-wash: "#1d3239"
  night-approved: "#62d6a3"
  night-warning: "#ffd166"
  night-danger: "#ff9486"
  night-payout: "#ffa857"
typography:
  display:
    fontFamily: "Fraunces Variable, Georgia, serif"
    fontSize: "2rem"
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Fraunces Variable, Georgia, serif"
    fontSize: "1.0625rem"
    fontWeight: 500
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  body:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.4
  mono:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.4
rounded:
  sm: "10px"
  md: "16px"
  pill: "999px"
spacing:
  gutter: "14px"
  card-x: "16px"
  stack: "12px"
components:
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
  button-primary:
    backgroundColor: "{colors.button}"
    textColor: "{colors.card}"
    rounded: "{rounded.pill}"
    padding: "9px 16px"
  pill-option-pressed:
    backgroundColor: "{colors.button}"
    textColor: "{colors.card}"
    rounded: "{rounded.pill}"
    padding: "6px 12px"
  note:
    backgroundColor: "{colors.soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "9px 12px"
---

# Design System: Veranico

## Overview

**Creative North Star: "The atlas page that answers back"**

The real terrain is the page. The risk is a wash of colour laid over it, and the working panels
sit on it like index cards. This is the Atlas direction, pinned by the owner from three rendered
alternatives after rejecting a schematic grid of flat squares on blank paper as unlike a map. The
approved planning preview is kept, read-only, in `frontend/design-reference/`; the direction
contract is in `.impeccable/surfaces/frontend-src-app-tsx.md`.

The screen is a working surface (Operate): a broker describes an exposure, reads the basis risk a
few kilometres from the farm, reaches a priced quote and approves the submission personally.
Density is that of a tool, the brand lives in details: the serif figures, the paper ground, the
hairline grid of the weather cube.

The dark theme is not a second world. It keeps Atlas's type, radii and solid cards and puts them
over the darkened satellite basemap with a luminous ramp.

**Key Characteristics:**

- The map fills the stage; every panel is a card floating on it.
- One continuous risk surface over real terrain; the raw cells are one switch away.
- Serif for titles and large figures, sans for text, mono only for identifiers and tool names.
- Teal acts, brick pays, green approves. Colour is never the only carrier of a state.
- Every figure is shown as the API returned it and can be traced to its tool result.

## Colors

Warm paper and ink in the light theme, night glass and pale ink in the dark one; the roles are the
same in both. Tokens live in `frontend/src/design/tokens.css` (three flat blocks: shared, light,
dark) and every colour token is defined in both themes, which a test enforces.

### Primary

- **Deep Teal** (`teal`, dark `night-teal`): actions, links, the active step, the quote
  identifier, the focus ring. On its wash (`teal-wash`) for the waiting note.
- **Ink Teal** (`button`): the filled button and the pressed option of a switch. In the dark theme
  the filled button inverts to pale ink on night ground.

### Secondary

- **Brick** (`brick`, dark `night-payout`): payouts, on the timeline and the History chart. Never
  used for errors.
- **Approved Green** (`approved`, dark `night-approved`): approved and delivered states only.

### Tertiary

- **Amber** (`warning`, dark `night-warning`): the mark of a caveat (synthetic data, a trend
  warning). It marks; the ink says it, because amber fails contrast as text.
- **Signal Red** (`danger`, dark `night-danger`): failures and a flagged figure.

### Neutral

- **Parchment** (`parchment`): the ground behind the map and the stacked layout.
- **Card White** (`card`) and **Soft Paper** (`soft`): card surface and the inset surface inside a
  card (tool rows, notes, examples).
- **Rule** (`line`, `line-strong`): hairline borders and dividers. In the dark theme they are white
  at 11% and 24% alpha.
- **Ink** (`ink`, `ink-2`, `ink-3`): text, secondary text, captions. `ink-3` and `approved` are
  darker than the approved preview so that small text meets AA.

### Map paint

The map is drawn on a canvas, which CSS tokens cannot reach, so its paint lives in
`frontend/src/design/theme.ts` (`MAP_PAINT`), copied from the preview's `atlas` (light) and
`noturno` (dark) paints.

- **Veil.** A flat colour laid over the tiles so the risk and the cards read on them: light
  `rgba(255,250,240,.12)` on relief and `rgba(250,246,238,.40)` on satellite; dark
  `rgba(8,12,18,.80)` on relief and `rgba(6,10,16,.52)` on satellite.
- **Trigger frequency ramp**, low to high, six stops. Light, sand to brick:
  `rgba(251,233,200,.6)`, `rgba(246,201,138,.7)`, `rgba(236,159,90,.76)`, `rgba(217,113,60,.82)`,
  `rgba(179,71,42,.86)`, `rgba(125,38,23,.9)`. Dark, luminous violet to yellow:
  `rgba(58,32,96,.32)`, `rgba(120,44,130,.48)`, `rgba(190,60,112,.62)`, `rgba(236,104,64,.74)`,
  `rgba(248,168,52,.84)`, `rgba(255,230,128,.92)`.
- **Season anomaly ramp**, dry to wet through a neutral midpoint, seven stops. Light, brick to
  teal: `rgba(163,57,31,.88)`, `rgba(217,113,60,.78)`, `rgba(241,192,143,.68)`,
  `rgba(232,228,220,.5)`, `rgba(167,211,214,.68)`, `rgba(78,163,176,.8)`, `rgba(18,112,127,.9)`.
  Dark, yellow to blue: `rgba(255,218,110,.92)`, `rgba(242,124,62,.8)`, `rgba(172,62,112,.58)`,
  `rgba(70,72,92,.26)`, `rgba(46,104,170,.56)`, `rgba(52,150,222,.76)`, `rgba(104,200,250,.88)`.
- **Classes come from the API.** `CellGrid.breaks` are class edges; a ramp is sampled to the
  number of classes the API returned. The interface computes no break.
- **Marker.** Ink Teal (`#143c44`) with card-white lettering on a card-white halo in the light
  theme; white with night lettering on a night halo in the dark one. A test holds the marker's
  3:1 and its label's 4.5:1 over any ground.

### Named Rules

**The Three Verbs Rule.** Teal acts, brick pays, green approves. A colour used for one of these is
not used for anything else.

**The Marked, Not Coloured Rule.** A state is never carried by colour alone: payout seasons have a
mark under the baseline, a flagged figure has its note, a warning has its icon and its sentence.

## Typography

**Display Font:** Fraunces Variable, with the optical size axis (fallback Georgia, serif)
**Body Font:** IBM Plex Sans 400, 500, 600 (fallback system-ui)
**Label/Mono Font:** IBM Plex Mono 400, 500 (fallback ui-monospace)

**Character:** A printed atlas: a warm, slightly old-style serif for names and figures over a
plain engineering sans for everything that is read at working size.

### Hierarchy

- **Display** (500, 2rem, tracking -0.015em): the one large figure of a tab: the insured cell's
  share, the indicative premium.
- **Title** (500, 1.0625rem to 1.375rem): card titles, the wordmark, the timeline readout.
- **Body** (400, 0.875rem, 1.5): conversation text and tab prose. Emphasis is 600.
- **Label** (400 to 600, 0.71875rem to 0.8125rem): field names, captions, switch options, tool row
  detail.
- **Mono** (400 to 500, 0.75rem to 0.8125rem): quote, submission and receipt identifiers, tool
  names, durations.

### Named Rules

**The Measured Mono Rule.** Mono is for identifiers, tool names and durations. It is never a
costume for "technical".

**The Tabular Rule.** Every number that can be compared with another uses tabular numerals (the
`num` class).

## Layout

The map is the stage (`frontend/src/app.css`). On it float, 14px from the edges: the top row; the
conversation card on the left (384px, 350px at or below 1240px); the tabs card on the right (344px,
500px when a tab other than Risk is open; 316px and 440px at or below 1240px); the season timeline
between them at the bottom. The map fits the region's weather cube in the area the cards leave
free, measured from the cards themselves.

At or below 1100px the same elements, in the same document order, stack: top row, map (height
`min(82vw, 500px)`), timeline, tabs, conversation (600px tall, its list scrolls inside). Nothing
scrolls sideways at 390px; tables that would not fit stack their secondary columns.

The embed (`/embed/map`) is the map over the timeline in a column that fills its frame. In a frame
narrower than 600px or shorter than 460px the map notes shrink to the synthetic label.

Spacing inside a card is 16px at the sides, 12px between blocks, and tighter (6px to 8px) inside a
group.

## Elevation & Depth

Two levels, both soft and offset, both warm in the light theme: the cards float on the map; the
things inside a card are flat and separated by hairlines or the soft paper tone.

### Shadow Vocabulary

- **Card** (`0 16px 40px rgba(64,48,20,.17)`; dark `0 16px 44px rgba(0,0,0,.5)`): cards and the
  floating switches of the top row. Nothing else.
- **Small** (`0 1px 3px rgba(64,48,20,.18)`; dark `0 1px 3px rgba(0,0,0,.4)`): the pressed option
  of an inset switch, the notes on the map.

### Named Rules

**The One Sheet Rule.** A card never sits inside a card. Inside a card, depth is a tone or a
hairline, never a second shadow.

## Shapes

Cards have 16px corners; things inside them 10px; switches, buttons and badges are pills. Borders
are 1px hairlines. The only hard-edged shapes are on the map: the cells, the cube outline and the
insured cell, drawn with mitred corners because they are data, not chrome.

## Components

### Buttons

- **Shape:** pill (999px).
- **Primary:** Ink Teal fill with card-white text, 9px by 16px; the small size is 7px by 13px.
- **Link:** text with an underline, for secondary actions inside a card ("Show one season",
  "Start over").
- **Hover / Focus:** colour shifts over 140ms; one focus ring for every control, 2px Deep Teal with
  a 2px offset, defined once in `global.css`.

### Chips

- **State badge:** a pill with a soft fill and a word; the state is also in the word.
- **Pill switch:** a segmented switch of two options, exactly one pressed (`aria-pressed`); floating
  on the map in the top row, inset inside a card.

### Cards / Containers

- **Corner Style:** 16px.
- **Background:** Card White; inset surfaces use Soft Paper.
- **Shadow Strategy:** the Card shadow, see Elevation.
- **Border:** 1px Rule.
- **Internal Padding:** 14px to 16px; a header is separated by a hairline.

### Inputs / Fields

- **Composer:** a soft paper field with a 14px radius and a round send button; the field is
  read-only, not disabled, while the agent streams, so the draft stays readable.
- **Region selector:** a native select drawn as a floating pill at the height of the switches, with
  the icon set's chevron laid over it; the browser keeps its keyboard and list behaviour.
- **Focus:** the shared ring; the composer rings its whole row.

### Navigation

- **Wordmark:** a link, in the same tab, to the project's page on the portfolio in the active
  language (`VITE_LANDING_URLS`); on hover its rule darkens and the name takes a hairline
  underline. The embed has no wordmark.
- **Tabs:** an ARIA tab list with arrow, Home and End keys; the open tab has a 2px Deep Teal
  underline; a count badge on Approvals says how many wait.

### Conversation

A six-segment progress bar with the step in words; user messages as soft bubbles on the right;
agent answers as plain text under collapsible tool rows (mono tool name, duration, one-line
summary). A figure in an answer is a button with a dashed underline that opens the tab and field it
came from; a figure the grounding check flagged is marked and noted, never a link.

### Risk layer and season timeline

The signature pair. The layer is one canvas over the tiles: a smoothed surface by default, raw
cells on request, the cube's grid as hairlines, the hovered or tapped cell outlined with a measured
leg from the farm. The timeline has one bar per season, payout seasons in brick with a mark below
the baseline, a dashed trigger line, and a range input over it for the keyboard. The timeline, the
History chart and the map share one selected season.

### States (SPEC 12.4) and where each is implemented

| State | Where |
| --- | --- |
| First run with example requests | `components/conversation/Examples.tsx` |
| Streaming with tool rows | `components/conversation/MessageList.tsx`, `ToolRow.tsx`, `ProgressBar.tsx` |
| Flagged figure | `components/conversation/Figure.tsx`, `figures.ts` |
| Allowance or ceiling reached, replay offered | `components/conversation/ReplayOffer.tsx` |
| Replay playing | `components/conversation/ReplayBanner.tsx`, `useReplayPlayback.ts`; recorded quote in `components/tabs/quote/QuoteTab.tsx` |
| Point outside the showcase regions | `map/RiskLayerView.tsx` (single cell and note), `components/topbar/RegionSelect.tsx`, `state/link.ts` |
| Pending approval | `components/tabs/approvals/ApprovalItem.tsx`; the waiting note in `MessageList.tsx` |
| Approved and delivering, delivered, delivery abandoned | `components/tabs/approvals/DeliveryProgress.tsx` |
| Rejected | `components/tabs/approvals/ApprovalItem.tsx` |
| Loading and failed data | `components/tabs/TabState.tsx`, `components/timeline/SeasonTimeline.tsx` |
| Basemap that has not loaded | `map/MapStage.tsx` (the risk layer stays; retry offered) |
| Turn that ended without an answer | `components/conversation/MessageList.tsx` |

## Do's and Don'ts

### Do:

- **Do** keep the map as the stage and every panel as one card on it.
- **Do** show figures exactly as the API returned them; the interface derives only the length of
  the measured leg and the minimum and maximum over returned cells.
- **Do** label synthetic weather wherever its figures appear (`Region.synthetic`, a dataset source
  of `synthetic`), on the map, in the Risk tab and in the embed.
- **Do** keep the attribution, the non-commercial notice and the pricing disclaimer in the timeline
  card, next to the map, in both layouts and in the embed.
- **Do** route every visible string through the catalogue, in English and Brazilian Portuguese.

### Don't:

- **Don't** draw the risk as flat squares on blank paper; the owner rejected that as unlike a map.
- **Don't** put a card inside a card, or give anything inside a card its own shadow.
- **Don't** use brick for errors, green for anything but approval, or amber as text.
- **Don't** use mono for anything but identifiers, tool names and durations.
- **Don't** let colour alone carry a state.

## Provenance and licences

The application ships no raster image. The built files contain the script, the style sheet and the
font files below; the basemaps are fetched as tiles at run time.

| Asset | Source | Licence |
| --- | --- | --- |
| Fraunces Variable (optical size axis) | `@fontsource-variable/fraunces` 5.3.0, self-hosted | SIL Open Font License 1.1 |
| IBM Plex Sans 400, 500, 600 (Latin) | `@fontsource/ibm-plex-sans` 5.3.0, self-hosted | SIL Open Font License 1.1 |
| IBM Plex Mono 400, 500 (Latin) | `@fontsource/ibm-plex-mono` 5.3.0, self-hosted | SIL Open Font License 1.1 |
| Icons | Authored for this project, one stroke on a 16 by 16 grid (`components/common/Icon.tsx`) | MIT, with the source |
| Wordmark | Authored for this project (`components/topbar/TopBar.tsx`) | MIT, with the source |
| Relief basemap tiles | EOX Terrain Light, layer `terrain-light_3857`, fetched from `tiles.maps.eox.at` | Free to use with attribution (EOX::Maps) |
| Satellite basemap tiles | EOX Sentinel-2 cloudless 2025, layer `s2cloudless-2025_3857`, fetched from `tiles.maps.eox.at` | CC BY-NC-SA 4.0 |
| Place-name tiles | EOX Overlay, layer `overlay_3857` in the light theme and `overlay_bright_3857` in the dark theme, fetched from `tiles.maps.eox.at` | Free to use with attribution (EOX::Maps) |
| `frontend/e2e/fixtures/tile.png` and `labels.png` (tests only, not shipped) | Generated by `frontend/e2e/fixtures/make-tile.mjs`: two flat colours, and a fully transparent tile for the place names; derived from no provider's imagery | MIT, with the source |
| `frontend/design-reference/` (reference only, not shipped) | The approved planning preview; its stitched map images are by EOX, see its `NOTICE.md` | As stated in `NOTICE.md` |

Because Sentinel-2 cloudless is CC BY-NC-SA 4.0, the demo is declared non-commercial in the
interface and in the README.

### Attribution texts

Shown in the timeline card (`map/Attribution.tsx`). The providers' wording is not translated; it
was verified in EOX's own documents on 2026-11-11 (sources in `frontend/src/config.ts`).

- Relief: "Terrain Light { Data © OpenStreetMap contributors and others, Rendering © EOX }",
  linked to `https://maps.eox.at/#data`, with "EOX::Maps, free to use with attribution" linked to
  `https://maps.eox.at/`.
- Satellite: "EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified
  Copernicus Sentinel data 2025)", linked to `https://cloudless.eox.at`, with "CC BY-NC-SA 4.0"
  linked to `https://creativecommons.org/licenses/by-nc-sa/4.0/`.
- Place names, after the label "Place names:": "Overlay { Data © OpenStreetMap contributors,
  Rendering © EOX and MapServer }" in the light theme and "Overlay bright { Data © OpenStreetMap
  contributors, Rendering © EOX and MapServer }" in the dark theme, linked to
  `https://maps.eox.at/#data`. Verified in EOX's WMTS capabilities document on 2026-11-12.
- Weather, for a region with real weather: "Weather: Copernicus Climate Change Service. ERA5-Land
  for the regional cubes; ERA5 through Open-Meteo for any other point. CC BY 4.0."
- Weather, for a synthetic region (`Region.synthetic`, or a dataset source of `synthetic`), in the
  application and in `/embed/map`: "Weather: the surface of this region is synthetic, generated
  for the demonstration; it is not weather history. A point outside the showcase regions uses ERA5
  through Open-Meteo (Copernicus Climate Change Service, CC BY 4.0)." A generated surface is never
  credited to ERA5-Land.
- Notices: "Non-commercial demo." and "Pricing is illustrative. It is not actuarial or insurance
  advice."
- Synthetic label: "Synthetic weather data, not weather history" on the map; "Synthetic weather
  data: these figures are generated for the demo and are not weather history." in the Risk tab.

### Test data

The happy path the tests play is the recorded conversation. `frontend/src/test/fixtures/recording.ts`
reads `backend/src/veranico/modules/assistant/replays/<locale>.jsonl` (the recordings of human gate
H1: claude-haiku-5-5, prompt v3, the real ERA5-Land cube of Sul de Minas) and the fixtures derive
everything from it: the four turns of `POST /chat`, the replay stream, and the bodies the mock API
answers in that flow (the place, the dataset, the cover, the backtest and the season values for
that cover, the priced quote, the submission and the approval). A new recording changes the tests'
figures without an edit; `UPDATE_FIXTURES=1 pnpm test src/test/fixtures` rewrites the `.sse` files.
The recording carries no per-cell grid, so `backend/scripts/export_cells.py` writes
`recorded-cells.json` from the same cube (it refuses a cube whose checksum differs from the
recording's): the region as `GET /regions` serves it (`synthetic: false`), the trigger frequency of
the recorded cover and the anomaly of every season. The Playwright flow and the two screenshots in
`frontend/e2e/evidence/` therefore show recorded figures over the real surface (trigger 105 mm,
exit 70 mm, 11 of 76 seasons paying, premium R$ 40,637.88), with no synthetic label.

Authored, because no recording holds them: the timestamps of the quote's audit trail, the human
decision, the delivery and its receipt, the API key, the flagged and the error streams, a
significant trend for the warning tests, and the two other regions, whose grids and season values
stay synthetic and are labelled `synthetic: true`. Both recordings price the same figures; the mock
serves one quote body with each recording's own identifiers.

## Finish review

The Impeccable finish review ran on 2026-11-11 with a fresh reviewer, on captures of the
production build with real basemap tiles and synthetic weather fixtures. The detector ran once and
left no blocking finding. The full record, with the reviewer's sections and the captures, is in
`.impeccable/review/finish-review.md`.

**Verdict: `disposition: fix`.** The owner's decision on it is human gate H3 and is open.

- Matched: the topology and first viewport of the contract, the type, the light theme's material
  and ground, the conversation, tabs and timeline cards.
- Applied after the review, not re-scored by the reviewer: a figure keeps its closing punctuation
  on its line; the quote identifier is Deep Teal everywhere; the audit trail's rail is 1px.
- Waiting for the owner, because each changes the approved look or goes beyond the specification:
  the surface fading inside the cube frame; the dark ramp hiding terrain in its top classes; no
  place names on the map; the conversation far down the stacked layout; no authored moment of
  motion.
- Decided by the owner on 2026-11-12: place names are drawn from EOX's overlay tiles, over the
  risk layer and under the markers (ADR 0021). The lettering is the provider's, not Atlas's.

Not canonized above as rules: the feathered edge of the surface and the dark ramp's alphas are
recorded as built, and both are open findings of this review.
