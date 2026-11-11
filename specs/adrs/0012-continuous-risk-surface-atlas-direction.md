# 0012. Continuous risk surface by default, in the Atlas direction

Status: Accepted (2026-11-10)

## Context

The first design preview drew the risk as a grid of flat coloured squares on a blank ground. The owner rejected it as ugly and unlike a map. Three directions were then rendered on real imagery (Noturno, Atlas, Campo). The owner chose Atlas, with the surface as the default rendering, the cells behind a switch, and a dark theme that keeps Atlas's type and cards over darkened satellite imagery.

The data is a 0.1° grid. A smooth surface shows values between cell centres that are not data, and showing interpolated values as if they were data would be dishonest.

## Decision

Governs SPEC sections 12 (design direction), 12.2 (item 2) and 12.6 (themes). The design contract is `.impeccable/surfaces/frontend-src-app-tsx.md`.

* The design direction is **Atlas**: real relief and satellite basemaps, the risk as a continuous surface, floating cards.
* The risk layer draws the per-cell metric of the active region on a canvas layer. It opens as a continuous surface (bilinear interpolation between cell centres, for display only) with the ERA5-Land grid as hairlines.
* A Cells switch shows the raw 0.1° cells.
* The interface states that the smoothing is visual.
* On hover the map shows the exact cell, its value and a measured leg from the farm with the distance.
* Light and dark themes share Atlas's type and card anatomy; the dark theme uses the darkened satellite basemap with a luminous ramp.

## Consequences

* The first screen reads as a map, and basis risk is visible as colour changing a few kilometres from the farm.
* The surface is interpolated. The statement in the interface, the hairline grid, the hover on the exact cell and the Cells switch are what keep it honest, so none of them can be dropped.
* There are two renderings of the same layer to build and test, in two themes.
* The interpolation is display code in the frontend. It must never produce a figure: every number shown comes from the API (SPEC section 12).
* The schematic grid as the default is closed. Returning to it needs a new decision by the owner.

## Alternatives considered

* **Grid of flat squares as the default (the brief and the first preview):** rejected by the owner as ugly and unlike a map.
* **Noturno or Campo as the direction:** rendered next to Atlas; the owner chose Atlas. Noturno's treatment is kept as the dark theme.
* **Surface only, with no Cells switch:** would show interpolated values as if they were data.
