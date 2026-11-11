"""Benchmark of the per-cell metrics on a full-size cube (SPEC 5.8, milestone M2).

A cube of 20 by 20 cells from 1950 through 2024, built with a seeded generator and served
by `FakeClimateFacade`. For each metric and each index type one uncached `cell_metrics`
call is timed, best of three with the cache cleared between runs. The threshold is fixed:
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
from veranico.modules.climate.contracts import RegionCube
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


@pytest.fixture(scope="module")
def cube() -> RegionCube:
    full_size = builders.region_cube(
        seed=CUBE_SEED, nx=20, ny=20, first_year=1950, last_year=builders.LAST_YEAR
    )
    assert full_size.precipitation_mm.shape == (27_394, 20, 20)  # 75 years of days
    return full_size


@pytest.mark.slow
@pytest.mark.req("R-5.8-6")
@pytest.mark.parametrize("metric", ["trigger_frequency", "season_anomaly"])
@pytest.mark.parametrize("index_type", ["rainfall_below", "dry_spell_above"])
async def test_uncached_cell_metrics_on_a_full_size_cube_take_under_a_second(
    cube: RegionCube, metric: Metric, index_type: IndexType
) -> None:
    climate = FakeClimateFacade()
    climate.add_cube(cube)
    service = PricingService(climate=climate, settings=settings_for_tests().pricing)
    request = CellMetricRequest(
        region_id=cube.region.region_id,
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
        f"\ncell_metrics {metric:<17} {index_type:<15} best of {RUNS}: {best * 1000:7.1f} ms "
        f"(runs: {', '.join(f'{t * 1000:.1f}' for t in timings)} ms) "
        f"on {platform.machine()} {platform.system()}, {os.cpu_count()} CPUs, "
        f"Python {platform.python_version()}"
    )
    assert len(grid.values) == 400
    assert len(grid.seasons) == 74
    assert sum(1 for name, _ in climate.calls if name == "region_cube") == RUNS  # never cached
    assert best < THRESHOLD_SECONDS
