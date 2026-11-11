# Design reference: notice

This folder is the planning preview the author approved as the visual reference for the Atlas
direction (`.impeccable/surfaces/frontend-src-app-tsx.md`). It is kept for reading only.

- **Reference only.** Nothing here is imported by the application. The folder is excluded from
  eslint, prettier, the type check, the tests and the build, and it is not shipped.
- **Synthetic weather values.** Every figure the preview shows (rainfall, trigger frequency,
  payouts, premiums, identifiers) is generated in the browser by `vr/engine.js` from a seed. None
  of it is weather history or a real quote.
- **Imagery.** The stitched basemap images in `vr/maps/` are by EOX: Sentinel-2 cloudless
  (CC BY-NC-SA 4.0) and Terrain Light. The exact attribution text each layer requires is verified
  against EOX's documentation in Task 5 of the web plan and recorded in `DESIGN.md`. The
  application itself uses live EOX tiles, not these images.
- **Do not edit.** Do not change, reformat, move or delete these files.
