"""The installed real cubes against fresh Open-Meteo series (SPEC 4.4). Open until H1.

    uv run pytest tests/integration/climate/test_consistency_live.py -m live -q -s

Needs the network and, for each region, a real cube (ERA5-Land read from Google Earth
Engine, ADR 0019) in the weather store the environment names. A region without a real
cube is skipped with the reason: a synthetic cube has nothing to agree with.

The first run at H1 is a measurement: the printed reports are what the two tolerance
constants in `domain/consistency.py` are set from, once.
"""

import random
from dataclasses import asdict

import httpx
import pytest

from veranico.modules.climate.domain.consistency import compare_series, within_tolerance
from veranico.modules.climate.domain.regions import cell_of, region_by_id
from veranico.modules.climate.infrastructure.open_meteo import OpenMeteoArchive
from veranico.modules.climate.module import StoreSettings, store_from_environment
from veranico.shared.kernel.clock import SystemClock
from veranico.shared.kernel.ids import cube_dataset_id

pytestmark = pytest.mark.live

# The same places as the recorded test.
PLACES = {
    "sul-de-minas": (-21.55, -45.43),  # Varginha
    "sorriso": (-12.55, -55.72),  # Sorriso
    "ribeirao-preto": (-21.18, -47.81),  # Ribeirao Preto
}


@pytest.mark.req("R-4.4-3")
@pytest.mark.parametrize("region_id", sorted(PLACES))
async def test_the_real_cube_agrees_with_open_meteo(region_id: str) -> None:
    settings = StoreSettings()
    store = store_from_environment(settings, SystemClock())
    source = await store.cube_source(region_id)
    if source != "era5-land/cds":
        pytest.skip(
            f"human gate H1 is open: the cube of {region_id} is {source or 'not installed'}"
        )
    region = region_by_id(region_id)
    assert region is not None
    lat, lon = PLACES[region_id]
    cell = await store.read_series(cube_dataset_id(region_id, *cell_of(region, lat, lon)))

    async with httpx.AsyncClient() as http:
        archive = OpenMeteoArchive(http, settings.climate, rng=random.Random())
        point = await archive.fetch(lat, lon, cell.dataset.first_year, cell.dataset.last_year)

    report = compare_series(cell.dates, cell.precipitation_mm, point.dates, point.precipitation_mm)
    print(f"\n{region_id}: {asdict(report)}")
    assert report.overlap_days >= 365
    assert within_tolerance(report)
