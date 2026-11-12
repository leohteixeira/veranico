# 0016. Weather cubes keep the whole time axis in one chunk of 10 by 10 cells

## Status

Accepted on 2026-11-11, from measurements on the three real cubes (human gate H1, ADR 0019). It records the measurement step 3 of section 4.1 of the specification asks for.

## Context

A cube is daily precipitation for one region: 27,759 days (1950-01-01 to 2025-12-31) by 20 by 20 cells of 0.1°, stored as Zarr (format 3, float64, zstd). The service reads it in two ways: the series of one cell (backtest, price, evidence) and the whole cube (per-cell metrics for the map). The specification proposes the full time axis with small spatial blocks and asks for the read time of one point series under that layout and under a one-field-per-time-step layout.

`make build-cube REGION=<id> MEASURE=1` (`climate/infrastructure/chunk_measure.py`) writes the installed cube under both layouts and reads it five times, each read in a new process, timing only the opening of the store and the read (no interpreter start or imports). Measured at commit efebecb on 2026-11-11; the raw reports are in `backend/.cache/chunking/<region>.json`.

| Region | Layout | Chunk objects | Store size | Write | Point series read (median, min to max) | Whole cube read (median) |
|---|---|---:|---:|---:|---|---:|
| Sul de Minas | A: time=-1, lat=10, lon=10 | 4 | 44.7 MB | 0.19 s | 62 ms (62 to 66) | 104 ms |
| Sul de Minas | B: time=1, whole grid | 27,759 | 41.7 MB | 13.4 s | 7,861 ms (7,303 to 8,549) | 7,584 ms |
| Sorriso | A | 4 | 40.2 MB | 0.19 s | 60 ms (59 to 62) | 103 ms |
| Sorriso | B | 27,759 | 37.6 MB | 14.1 s | 7,329 ms (7,106 to 7,726) | 7,504 ms |
| Ribeirão Preto | A | 4 | 39.3 MB | 0.20 s | 63 ms (58 to 64) | 111 ms |
| Ribeirão Preto | B | 27,759 | 36.7 MB | 15.0 s | 7,389 ms (7,186 to 8,226) | 7,466 ms |

Python 3.12.14, xarray 2026.9.0, zarr 3.4.2, NumPy 2.5.4, Linux x86_64 with 12 CPUs.

## Decision

Layout A: the whole time axis in one chunk, 10 by 10 cells (`zarr_io.write_cube`), so a 20 by 20 cube is four chunk objects and the series of one cell is one of them.

## Consequences

* A point series reads in about 60 ms and the whole cube in about 105 ms; layout B is about 120 times slower for a point and 70 times for the cube, because every read touches all 27,759 objects. Layout A costs about 7% more storage (40 MB against 37 MB a region), which is immaterial.
* A point read decodes a whole quarter of the cube (100 cells) to return one. That is the price of four objects instead of hundreds, and the service keeps decoded cubes in memory anyway (`cube_cache_size`).
* Appending a year rewrites every chunk. The cubes are rebuilt offline from the cached yearly files (section 4.1), so no append path exists to optimise.
* Limits of the measurement: one machine, the local filesystem, the page cache warm (reads follow the write on the same host), so it measures decoding and file handling, not a cold disk or Cloud Storage. Not measured: reads from Cloud Storage, where layout B would also mean 27,759 requests per cube against 4; that only widens the gap.

## Alternatives considered

* Layout B, one field per day: the layout of a daily download, measured above and rejected.
* One chunk for the whole cube: one object, but a point read would decode all 400 cells instead of 100. Not measured; with four objects already, the gain of one is nil.
