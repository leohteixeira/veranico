"""Benchmark of the per-cell metrics on a full-size cube (SPEC 5.8, milestone M2).

Two cubes of 20 by 20 cells from 1950 through 2024, served by `FakeClimateFacade`: one from
the seeded test builder and one from the generator `climate` uses for its showcase regions.
For each cube, metric and index type one uncached `cell_metrics` call is timed, best of
three with the cache cleared between runs. The threshold is fixed:
if a case fails, the computation is fixed, not the number.

Run with `-s` to see the measured times:

    uv run pytest tests/integration/pricing/test_cell_metrics_speed.py -m slow -q -s
"""

import os
import platform
import time
from typing import Literal

import pytest

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.settings import settings_for_tests
from veranico.modules.pricing.application.service import PricingService
from veranico.modules.pricing.contracts import (
    CellMetricRequest,
    IndexDefinition,
    IndexType,
    Window,
)

THRESHOLD_SECONDS = 1.0
RUNS = 3
CUBE_SEED = 20
SEASON = 1987
WINDOW = Window(start="10-01", end="03-31")  # 182 days, crossing the year
INDEXES: dict[IndexType, IndexDefinition] = {
    "rainfall_below": IndexDefinition(
        index_type="rainfall_below", window=WINDOW, trigger=600.0, exit=300.0
    ),
    "dry_spell_above": IndexDefinition(
        index_type="dry_spell_above", window=WINDOW, trigger=9.0, exit=18.0
    ),
}
Metric = Literal["trigger_frequency", "season_anomaly"]


CubeSource = Literal["builder", "generated"]


@pytest.fixture(scope="module", params=["builder", "generated"])
def climate_with_cube(request: pytest.FixtureRequest) -> tuple[CubeSource, FakeClimateFacade, str]:
    """A fake climate serving one full-size cube: the test builder's, or the generated one.

    `generated` is the cube of the showcase region as `climate` itself generates it.
    """
    source: CubeSource = request.param
    climate = FakeClimateFacade()
    if source == "builder":
        cube = builders.region_cube(
            seed=CUBE_SEED, nx=20, ny=20, first_year=1950, last_year=builders.LAST_YEAR
        )
        assert cube.precipitation_mm.shape == (27_394, 20, 20)  # 75 years of days
        region = climate.add_cube(cube)
    else:
        region = climate.with_synthetic_region(
            "sorriso", seed=CUBE_SEED, first_year=1950, last_year=builders.LAST_YEAR
        )
    return source, climate, region.region_id


def cube_fetches(climate: FakeClimateFacade) -> int:
    return sum(1 for name, _ in climate.calls if name == "region_cube")


@pytest.mark.slow
@pytest.mark.req("R-5.8-6")
@pytest.mark.parametrize("metric", ["trigger_frequency", "season_anomaly"])
@pytest.mark.parametrize("index_type", ["rainfall_below", "dry_spell_above"])
async def test_uncached_cell_metrics_on_a_full_size_cube_take_under_a_second(
    climate_with_cube: tuple[CubeSource, FakeClimateFacade, str],
    metric: Metric,
    index_type: IndexType,
) -> None:
    source, climate, region_id = climate_with_cube
    fetches_before = cube_fetches(climate)
    service = PricingService(climate=climate, settings=settings_for_tests().pricing)
    request = CellMetricRequest(
        region_id=region_id,
        metric=metric,
        index=INDEXES[index_type],
        season=SEASON if metric == "season_anomaly" else None,
    )

    timings = []
    for _ in range(RUNS):
        service.cell_cache.clear()
        started = time.perf_counter()
        grid = await service.cell_metrics(request)
        timings.append(time.perf_counter() - started)
    best = min(timings)

    print(
        f"\ncell_metrics {source:<9} cube {metric:<17} {index_type:<15} "
        f"best of {RUNS}: {best * 1000:7.1f} ms "
        f"(runs: {', '.join(f'{t * 1000:.1f}' for t in timings)} ms) "
        f"on {platform.machine()} {platform.system()}, {os.cpu_count()} CPUs, "
        f"Python {platform.python_version()}"
    )
    assert len(grid.values) == 400
    assert len(grid.seasons) == 74
    assert cube_fetches(climate) - fetches_before == RUNS  # never served from the cache
    assert best < THRESHOLD_SECONDS
