# 0018. Regional cubes are built from hourly ERA5-Land, two time steps a day

## Status

Accepted on 2026-11-11 by the build coordinator while the owner was away. It amends step 1 of section 4.1 of the specification, so the owner's confirmation is requested in the delivery report. The request itself can only be proven with a Copernicus account (human gate H1); what is unverified is listed below.

## Context

Section 4.1 of the specification says the backfill job "requests ERA5-Land daily statistics from the Copernicus Climate Data Store". Read on 2026-11-11:

* The catalogue entry `derived-era5-land-daily-statistics` states that "the accumulated variables are omitted (e.g. total precipitation, runoff, etc". It serves daily mean, maximum and minimum only. ECMWF's documentation of the daily statistics repeats it: "ERA5-Land daily accumulated parameters are not available from the catalogue entry."
* In the hourly entry `reanalysis-era5-land`, `total_precipitation` (short name `tp`, metres) is accumulated from 00 UTC over the steps 01 to 24, so the value stamped 00 UTC is the total of the previous UTC day. ECMWF's ERA5-Land documentation adds that a daily accumulation for a zone other than UTC needs the data sampled at two time steps.

The specification also requires daily values aggregated by local day (section 4), which is what the point path gets from Open-Meteo with `timezone=auto`.

## Decision

1. The download step requests `reanalysis-era5-land`, variable `total_precipitation`, one request per region and year, with two time steps a day: 00:00 UTC and the hour equal to the region's offset behind UTC (03:00 for Sul de Minas and Ribeirão Preto, 04:00 for the Mato Grosso region; Brazil has had no daylight saving time since 2019, and the fixed offset is used for every year).
2. The local-day total for a zone `k` hours behind UTC is `tp(D+1, 00:00) - tp(D, k:00) + tp(D+1, k:00)`: the UTC day `D`, minus its first `k` hours, plus the first `k` hours of the next UTC day. It is derived from the accumulation rule above, not quoted from a page, and is covered by a unit test on a hand-written series.
3. The download step, behind one small function, writes one NetCDF file per region and year holding local-day sums. The converter (`convert_years`) reads only that shape, and the synthetic file of the pipeline tests has the same shape, so everything after the download is exercised without an account.

## Consequences

* The cubes stay ERA5-Land on the 0.1° grid, with local days, as the specification intends. The cost is 228 requests (3 regions, 76 years) of 730 small fields each, plus 228 one-day requests for 1 January of the following year (the last local day of a year needs it, and a request is a product of years, months, days and times), instead of one server-side daily product.
* Years before 2019 with daylight saving time in the Centre-South are aggregated on the fixed standard offset. Open-Meteo's `timezone=auto` follows the historical clock, so in those summers the two sources cut the day one hour apart. The consistency check of section 4.4 already compares two different products (ADR 0017) and its tolerance is set from measured differences at H1.
* Not verified, and to be confirmed with the first real request at H1 before `make build-cube` is trusted: the request keys and option values of the hourly entry (variable, time, area order, NetCDF output), the variable and coordinate names inside the returned file, and any request size limit. A mismatch must fail the download step with a clear message, never produce a cube.

## Alternatives considered

* The 00:00 step only: half the fields, but UTC days, three to four hours off the local day the specification requires and the point path uses.
* All 24 steps: twelve times the volume for the same result.
* ERA5 daily statistics on single levels: one server-side sum and the same product as the point path, but on the 0.25° grid, where a 2° region is 8 by 8 cells instead of 20 by 20. It would remove the reason for the cubes.
