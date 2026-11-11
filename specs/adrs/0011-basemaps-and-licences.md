# 0011. EOX basemaps, MIT code and a non-commercial demo

Status: Accepted (2026-11-10)

## Context

The original brief used OpenStreetMap street tiles and Sentinel-2. The owner rejected a schematic map and asked for one that looks like a real map (ADR 0012). Relief (EOX Terrain Light) shows the terrain that matters for agriculture, and Sentinel-2 cloudless is the satellite option. Neither needs an account or a key.

The licence of the imagery limits what the demo may be used for, so it is part of the design.

## Decision

Governs SPEC sections 12.2 (item 1) and 12.6.

* **Relief:** EOX Terrain Light, the default basemap in the light theme.
* **Satellite:** EOX Sentinel-2 cloudless, most recent year, the default basemap in the dark theme.
* No accounts and no keys. Tile URLs live in configuration.
* The exact attribution each provider requires is shown legibly next to the map and in the README.
* Sentinel-2 cloudless imagery after 2016 is CC BY-NC-SA 4.0, so the demo is declared non-commercial in the README and in the interface. The source code is MIT.

**Open verification.** The exact attribution text, the tile URL templates and the licence of Terrain Light have not been verified. They must be checked in EOX's official documentation before release (SPEC section 21). Until then they are not stated as facts anywhere in the repository.

## Consequences

* The map looks like a map and shows terrain, with no account, key or tile bill.
* The demo cannot be used commercially while it shows this satellite layer. A commercial use needs another layer or a licence (see `docs/NEXT_STEPS.md`).
* The code licence (MIT) and the demo's terms (non-commercial) differ, and the README and the interface have to explain why.
* The tiles come from a third-party service the project does not control. The interface must handle a basemap that has not loaded (SPEC section 12.4).
* Release is blocked on the open verification above.

## Alternatives considered

* **OpenStreetMap standard tiles (the brief):** a street map, which does not tell the terrain story.
* **Keyed commercial tile providers:** need an account and add cost.
