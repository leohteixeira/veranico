# 0019. Regional cubes read ERA5-Land from Google Earth Engine

## Status

Accepted on 2026-11-11 (the owner approved the change of source). It supersedes the download source of ADR 0018 (decision 1, and the request and cost figures of its consequences); decisions 2 and 3 of ADR 0018 stand. It amends step 1 of section 4.1 of the specification and the prerequisites table of section 20. The first real request is human gate H1.

## Context

The cubes need ERA5-Land precipitation on the 0.1° grid from 1950, summed by local day (ADR 0018). The owner has no Copernicus account and will use Earth Engine, which hosts the same product under the same licence. Read on 2026-11-11:

* Catalogue `ECMWF/ERA5_LAND/HOURLY` (developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_LAND_HOURLY): band `total_precipitation`, unit m, accumulated and reset at midnight; band `total_precipitation_hourly` holds the increments; image property `hour`; available from 1950-01-01T01:00Z; pixel size 11132 m. Terms: the Copernicus C3S/CAMS licence, notices "Generated using Copernicus Climate Change Service Information [Year]" or "Contains modified Copernicus Climate Change Service Information [Year]", and that neither the European Commission nor ECMWF is responsible for any use of the data. Earth Engine is not named in the required wording.
* Catalogue `ECMWF/ERA5_LAND/DAILY_AGGR`: `total_precipitation_sum`, from 1950-01-02, built from "the first hour's data of the following day", so it gives UTC days.
* `projects.image/computePixels` and `ee.data.computePixels` (reference/rest/v1/projects.image/computePixels, apidocs/ee-data-computepixels): a `grid` (`PixelGrid`: `crsCode`, `affineTransform`, `dimensions`), `fileFormat` `NUMPY_NDARRAY`; at most 48 MB uncompressed, 32768 pixels a side and 1024 bands, otherwise HTTP 400. `AffineTransform` places (0, 0) at the top-left corner of the top-left pixel.
* Authentication (guides/auth, cloud/earthengine_cloud_project_setup): `earthengine authenticate` stores credentials under `~/.config/earthengine/`; `ee.Initialize(project=...)` needs a Cloud project registered for Earth Engine with the API `earthengine.googleapis.com` enabled; noncommercial use is declared in the console. No environment variable for the project is documented, and the installed client (1.7.50) reads none.
* Noncommercial terms (earthengine.google.com/noncommercial): free for "an individual developer using Earth Engine for noncommercial purposes", who may not be paid for what is built with it.
* PyPI: `earthengine-api` 1.7.52 is the latest (2026-11-09); 1.7.50 (2026-10-26) is pinned, being more than two weeks old.

## Decision

1. The download step reads `ECMWF/ERA5_LAND/HOURLY`, band `total_precipitation`, the images whose `hour` is 0 or the region's offset k, from 01:00 UTC on 1 January to k:00 UTC on 1 January of the next year: one `computePixels` call per region and year, 731 or 733 bands of 20 by 20 pixels (about 2.3 MB). The local day is ADR 0018's formula on the accumulated band. The UTC daily aggregate is not used: it would be a deviation from the local days the specification requires.
2. The request names its grid: EPSG:4326, scale 0.1 and -0.1, origin at the region's north-west corner, 20 by 20 pixels, so pixel centres are the cell centres. Before anything is fetched, the native projection must be EPSG:4326 with 0.1° pixels centred on multiples of 0.1°; otherwise the build fails rather than resample.
3. The project comes from `EARTHENGINE_PROJECT`, a name of ours. A missing project, missing or refused credentials, a refused request, or an answer whose bands, time steps, shape or grid differ from the request, fails before any yearly file is written, with a message naming the step to take.
4. `cdsapi` is removed; `earthengine-api` stays in the optional `cube` group, imported only inside the download function. The dataset label `era5-land/cds` is a frozen contract value (contracts, OpenAPI, frontend, documents) and keeps naming the product; renaming it is left to the coordinator.

## Consequences

* The cubes stay ERA5-Land on the 0.1° grid with local days; 228 requests in all, none extra for 1 January.
* Not verified until H1: that `system:time_start` is the end of the accumulation (checked on the answer by the expected time steps and by refusing negative local-day totals), the native projection, the band order of `toBands` and how masked pixels arrive. NumPy output carries no unit; the band fixes it, and the H1 consistency test against Open-Meteo would show a factor of 1000.
* Whether the portfolio counts as noncommercial is the owner's declaration at registration.
