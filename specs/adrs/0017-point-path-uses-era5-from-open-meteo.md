# 0017. The point path uses ERA5 precipitation from Open-Meteo, labelled as such

## Status

Accepted on 2026-11-11 by the build coordinator while the owner was away. It amends a premise of the specification, so the owner's confirmation is requested in the delivery report.

## Context

Section 4 of the specification assumed that both weather sources deliver the same product, ERA5-Land daily precipitation: the regional cubes from the Copernicus Climate Data Store and the point fallback from the Open-Meteo Historical Weather API.

Checked live on 2026-11-11 against `https://archive-api.open-meteo.com/v1/archive` (`daily=precipitation_sum`, `timezone=auto`, a point in Sul de Minas, 2020-01-01 to 2020-01-05):

| `models=` | Grid point returned | `precipitation_sum` |
|---|---|---|
| `era5_land` | 0.1° grid | `null` for every day |
| `era5` | 0.25° grid | values |
| `era5_seamless` | 0.1° grid | the same values as `era5` |

Open-Meteo does not serve precipitation for ERA5-Land. `era5_seamless` answers with the ERA5 values while reporting the ERA5-Land grid point, so two points 0.1° apart inside one ERA5 cell would look like two cells with identical histories. The product's subject is basis risk between grid cells, and the contract value `DatasetRef.source = "era5-land/open-meteo"` would state a provenance the data does not have.

## Decision

1. The point path requests `models=era5`. The dataset is keyed by the H3 cell of the 0.25° grid point the API returns, as section 4.2 already requires ("the grid point the API returns").
2. The contract literal `"era5-land/open-meteo"` is replaced by `"era5/open-meteo"` in `DatasetRef.source`. Nothing can produce the old value, so it is removed, not kept beside the new one.
3. The first year stays 1950, so point and cube histories cover the same seasons.
4. The interface, the term sheet and the README name the point source as ERA5 (Copernicus Climate Change Service, through Open-Meteo), and the cubes as ERA5-Land. Both remain CC BY 4.0.

Consumers changed in the same commit as the contract: `climate/contracts.py`, the frozen contract snapshot, `tests/fakes/builders.py`, `openapi.json` and the generated frontend types. Consumers changed by their owners right after: `climate` (manifest source, request, fixtures), `pricing` (one test parameter), the frontend (the translated source labels).

## Consequences

* A point outside the showcase regions is priced on a 0.25° product; a point inside a region, once the real cubes exist, on a 0.1° product. The two are related (ERA5-Land is forced by ERA5 precipitation) but not identical, and the interface says which one a quote used through `assumption.data_source`.
* The cube versus point consistency check of section 4.4 compares two different products. It keeps proving the mechanism; its tolerance stays provisional until the real cubes exist (human gate H1) and must then be set from measured differences, not assumed small. Set at H1 on 2026-11-11: the real cells differ from the ERA5 series by 1.26 to 1.50 mm a day on average and 2.5% to 8.3% in total over 1950 to 2025; the limits are 1.8 mm and 10% (section 4.4, `climate/domain/consistency.py`).
* Until H1 closes, the showcase regions run on synthetic cubes, so the only real weather history in the product is ERA5 through Open-Meteo. H1 closed on 2026-11-11: a region with its real cube built runs on ERA5-Land; a fresh clone, which has none, still runs on synthetic cubes.
* The sentence in section 4 of the specification, "Both sources deliver the same reanalysis product", no longer holds. Section 22 lists this ADR.
