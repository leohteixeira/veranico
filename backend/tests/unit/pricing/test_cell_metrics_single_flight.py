"""Concurrent `cell_metrics` calls: one computation per uncached request, off the event loop.

The load campaign of SPEC 16.5 showed identical uncached requests computing the same grid
several times at once, each waiting its own turn for the cube. These tests hold the cube
back with a gate, so the order of events is fixed and no test depends on timing.
"""

import asyncio
import threading
from typing import Any

import pytest

from tests.fakes.climate import FakeClimateFacade
from tests.fakes.settings import settings_for_tests
from tests.unit.pricing.test_cell_metrics_service import (
    DRY_SPELL,
    REGION_ID,
    anomaly,
    cube_reads,
    frequency,
    hand_cube,
)
from veranico.modules.climate.contracts import RegionCube
from veranico.modules.pricing.application.service import PricingService
from veranico.modules.pricing.contracts import CellGrid, CellMetricRequest
from veranico.shared.kernel.errors import InsufficientHistoryError


class GatedClimate(FakeClimateFacade):
    """Answers `region_cube` only once the gate is open, like a cube still being decoded."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    async def region_cube(self, region_id: str) -> RegionCube:
        cube = await super().region_cube(region_id)
        await self.gate.wait()
        return cube


def gated_service(**pricing: Any) -> tuple[PricingService, GatedClimate]:
    climate = GatedClimate()
    climate.add_cube(hand_cube())
    settings = settings_for_tests(pricing={"min_seasons": 4, **pricing})
    return PricingService(climate=climate, settings=settings.pricing), climate


async def started(
    service: PricingService, *requests: CellMetricRequest
) -> list[asyncio.Task[CellGrid]]:
    """Start one call per request and let each run up to the closed gate."""
    tasks = [asyncio.create_task(service.cell_metrics(request)) for request in requests]
    for _ in range(3):
        await asyncio.sleep(0)
    return tasks


@pytest.mark.req("R-5.8-6")
async def test_identical_uncached_requests_share_one_computation() -> None:
    service, climate = gated_service()

    tasks = await started(service, *[frequency()] * 5)
    assert cube_reads(climate) == 1  # the other four wait for the first, they do not start
    climate.gate.set()
    grids = await asyncio.gather(*tasks)

    assert all(grid is grids[0] for grid in grids)
    assert cube_reads(climate) == 1
    assert await service.cell_metrics(frequency()) is grids[0]  # and it was cached once
    assert cube_reads(climate) == 1


@pytest.mark.req("R-5.8-6")
async def test_trigger_frequency_requests_of_different_seasons_share_one_computation() -> None:
    service, climate = gated_service()

    tasks = await started(service, frequency(season=2001), frequency(season=2002), frequency())
    climate.gate.set()
    grids = await asyncio.gather(*tasks)

    assert cube_reads(climate) == 1
    assert grids[1] is grids[0]
    assert grids[2] is grids[0]


@pytest.mark.req("R-5.8-6")
async def test_different_requests_are_computed_separately() -> None:
    service, climate = gated_service()

    tasks = await started(service, frequency(), frequency(DRY_SPELL), anomaly(2001))
    climate.gate.set()
    first, second, third = await asyncio.gather(*tasks)

    assert cube_reads(climate) == 3
    assert first.values != second.values
    assert third.metric == "season_anomaly"
    assert first.region_id == REGION_ID


@pytest.mark.req("R-5.8-6")
async def test_a_failed_computation_reaches_every_waiter_and_is_not_kept() -> None:
    service, climate = gated_service(min_seasons=5)  # the hand cube has four seasons

    tasks = await started(service, *[frequency()] * 3)
    climate.gate.set()
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    assert [type(outcome) for outcome in outcomes] == [InsufficientHistoryError] * 3
    assert cube_reads(climate) == 1
    with pytest.raises(InsufficientHistoryError):
        await service.cell_metrics(frequency())  # a later request tries again
    assert cube_reads(climate) == 2
    assert len(service.cell_cache) == 0


@pytest.mark.req("R-5.8-6")
async def test_a_caller_that_goes_away_does_not_cancel_the_others() -> None:
    service, climate = gated_service()

    leaving, staying = await started(service, frequency(), frequency())
    leaving.cancel()
    await asyncio.sleep(0)
    climate.gate.set()
    grid = await staying

    assert leaving.cancelled()
    assert len(grid.values) == 4
    assert cube_reads(climate) == 1


@pytest.mark.req("R-5.8-6")
async def test_the_grid_is_computed_even_when_its_only_caller_goes_away() -> None:
    service, climate = gated_service()

    (leaving,) = await started(service, frequency())
    leaving.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leaving
    climate.gate.set()

    grid = await service.cell_metrics(frequency())  # joins the computation still going on
    assert cube_reads(climate) == 1
    assert await service.cell_metrics(frequency()) is grid  # which cached its grid
    assert cube_reads(climate) == 1


@pytest.mark.req("R-5.8-6")
async def test_the_grid_is_computed_off_the_event_loop() -> None:
    service, climate = gated_service()
    climate.gate.set()
    threads: list[int] = []
    cell_grid = service._cell_grid

    def recording(cube: RegionCube, request: CellMetricRequest) -> CellGrid:
        threads.append(threading.get_ident())
        return cell_grid(cube, request)

    service._cell_grid = recording  # type: ignore[method-assign]  # a spy on the real method
    await service.cell_metrics(frequency())

    assert threads
    assert threads[0] != threading.get_ident()
