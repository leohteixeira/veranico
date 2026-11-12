# 0021. Place names from the EOX overlay tiles

## Status

Accepted on 2026-11-12, decided by the owner. It adds item 7 to SPEC section 12.2 and requirement `R-12.2-7`.

## Context

The relief and satellite basemaps of ADR 0011 carry no lettering, so the map shows the farm's marker and no town a reader can place it by. The design finish review asked for place names; the request waited for the owner because the API returns no place names for a region and the specification listed none.

Three sources were compared on the real tiles of Sul de Minas, at the zoom the application opens with:

1. A curated list of towns per region, drawn by the application in Atlas's type, as the planning preview does.
2. A list of towns returned by the API with each region.
3. EOX's own overlay layer: transparent tiles of place names and state borders, made to sit over data on a background, served by the provider of both basemaps.

## Decision

Option 3.

* The light theme draws `overlay_3857` and the dark theme draws `overlay_bright_3857`. The layer follows the theme, not the basemap, because the dark theme darkens either basemap. Both layers, their tile matrix set (`g`) and their attribution were read in EOX's WMTS capabilities document on 2026-11-12.
* The tiles are drawn in a Leaflet pane of their own at z-index 360: over the risk layer (350), under the vector layers and the markers (400 and above). The pane takes no pointer events, so hovering a cell works through it.
* The tile URLs and the attribution live in `frontend/src/config.ts` (`placeLabels`). They have no `VITE_` override; the basemaps keep theirs.
* The attribution is shown in the timeline card after the basemap's, under the label "Place names:" ("Nomes de lugares:").
* A place-name tile that fails to load raises no notice. The failed-basemap state of SPEC 12.4 counts basemap tiles only.
* The end-to-end run answers place-name requests with a generated transparent tile, so the layer hides nothing in a capture.

## Consequences

* No list of places to keep, no change to the API, and no new provider, account or key.
* The lettering, the selection of places and their positions are the provider's. They change with the zoom, the typeface is not Atlas's, and a name can sit under the farm's label or a floating card. None of this can be tuned from the application. At 1440 px Sul de Minas opens with four towns named inside the cube frame; at 390 px the zoom is lower and the frame holds no name, only the towns around it.
* The layer also draws borders, in orange.
* The map requests about twice as many tiles from `tiles.maps.eox.at`.
* The attribution block gains one line.
* The captured map images of the presentation page in the portfolio repository show the map without names until they are captured again.

## Alternatives considered

* **Curated list drawn by the application (option 1):** full control of type, selection and collisions, at the cost of a sourced list of coordinates for each region. It stays in `docs/NEXT_STEPS.md`.
* **List of towns from the API (option 2):** the same control with the list on the server, but it changes a frozen contract for a display concern.
