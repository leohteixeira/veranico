import numpy as np
import pytest

from tests.fakes import builders
from tests.fakes.climate import DEFAULT_EVIDENCE, FakeClimateFacade
from veranico.modules.climate.contracts import EvidenceRequest, Location, LocationCandidates
from veranico.shared.kernel.errors import (
    DatasetNotFoundError,
    InvalidArgumentsError,
    LocationNotFoundError,
    OutsideCoverageError,
    WeatherSourceUnavailableError,
)
from veranico.shared.kernel.ids import DatasetId, cube_dataset_id

LAT, LON = builders.LAT, builders.LON


def location(label: str, lat: float = LAT, lon: float = LON) -> Location:
    return Location(
        label=label,
        lat=lat,
        lon=lon,
        h3_cell=builders.h3_cell_for(lat, lon),
        admin_region="Mato Grosso",
        country_code="BR",
    )


def evidence_request(dataset_id: DatasetId) -> EvidenceRequest:
    return EvidenceRequest(
        dataset_id=dataset_id,
        window_start="10-01",
        window_end="03-31",
        first_season=1950,
        last_season=2023,
        attributes={"quote_id": "Q-000001"},
    )


async def test_resolving_coordinates_gives_a_deterministic_cell_without_any_lookup() -> None:
    climate = FakeClimateFacade()

    first = await climate.resolve_location(None, LAT, LON)
    second = await climate.resolve_location(None, LAT, LON)
    elsewhere = await climate.resolve_location(None, -21.2, -47.8)

    assert isinstance(first, Location)
    assert isinstance(elsewhere, Location)
    assert first == second
    assert first.h3_cell == builders.h3_cell_for(LAT, LON)
    assert elsewhere.h3_cell != first.h3_cell
    assert (first.lat, first.lon) == (LAT, LON)


async def test_resolving_a_registered_name_returns_its_location() -> None:
    climate = FakeClimateFacade()
    climate.add_location("Sorriso", location("Sorriso, MT"))

    assert await climate.resolve_location("sorriso", None, None) == location("Sorriso, MT")


async def test_an_unknown_name_is_location_not_found() -> None:
    with pytest.raises(LocationNotFoundError):
        await FakeClimateFacade().resolve_location("Atlantis", None, None)


async def test_an_ambiguous_name_returns_candidates_and_does_not_raise() -> None:
    climate = FakeClimateFacade()
    candidates = [location("Santa Rita, MG", -22.2, -45.7), location("Santa Rita, PB", -7.1, -34.9)]
    climate.add_candidates("Santa Rita", candidates)

    found = await climate.resolve_location("Santa Rita", None, None)

    assert found == LocationCandidates(candidates=candidates)
    with pytest.raises(ValueError, match="two to five"):
        climate.add_candidates("One", candidates[:1])


@pytest.mark.parametrize("arguments", [(None, None, None), (None, LAT, None), ("x", LAT, None)])
async def test_neither_a_name_nor_both_coordinates_is_invalid_arguments(
    arguments: tuple[str | None, float | None, float | None],
) -> None:
    with pytest.raises(InvalidArgumentsError):
        await FakeClimateFacade().resolve_location(*arguments)


async def test_a_point_outside_brazil_is_outside_coverage() -> None:
    climate = FakeClimateFacade()

    with pytest.raises(OutsideCoverageError):
        await climate.resolve_location(None, 48.85, 2.35)
    with pytest.raises(OutsideCoverageError):
        await climate.ensure_history(48.85, 2.35)


async def test_ensure_history_is_idempotent_and_returns_the_registered_dataset() -> None:
    climate = FakeClimateFacade()
    series = builders.daily_series(seed=1)
    climate.add_series(series)

    first = await climate.ensure_history(LAT, LON)
    second = await climate.ensure_history(LAT, LON)

    assert first == second == series.dataset
    assert first.source == "synthetic"
    assert [name for name, _ in climate.calls] == ["ensure_history", "ensure_history"]


async def test_ensure_history_without_a_registered_series_is_a_setup_mistake() -> None:
    with pytest.raises(LookupError, match="add_series"):
        await FakeClimateFacade().ensure_history(LAT, LON)


async def test_a_registered_series_carries_only_precipitation() -> None:
    climate = FakeClimateFacade()
    dataset = climate.add_series(builders.daily_series(seed=1))

    series = await climate.daily_series(dataset.dataset_id)

    assert series.__slots__ == ("dataset", "dates", "precipitation_mm")
    assert series.dates.dtype == np.dtype("datetime64[D]")
    assert series.precipitation_mm.dtype == np.float64
    assert len(series.dates) == len(series.precipitation_mm) == dataset.days
    assert np.all(np.diff(series.dates).astype(int) == 1)  # strictly increasing, no gaps
    assert await climate.describe(dataset.dataset_id) == dataset


async def test_an_unknown_dataset_is_dataset_not_found() -> None:
    climate = FakeClimateFacade()
    unknown = builders.point_dataset_for(-21.2, -47.8)

    with pytest.raises(DatasetNotFoundError):
        await climate.describe(unknown)
    with pytest.raises(DatasetNotFoundError):
        await climate.daily_series(unknown)
    with pytest.raises(DatasetNotFoundError):
        await climate.region_cube("sorriso")
    with pytest.raises(DatasetNotFoundError):
        await climate.export_evidence(evidence_request(unknown))


async def test_a_registered_cube_serves_its_region_its_cells_and_points_inside_it() -> None:
    climate = FakeClimateFacade()
    cube = builders.region_cube(seed=3, nx=2, ny=2)
    climate.add_cube(cube)
    area = cube.region

    inside = await climate.ensure_history(area.north - 0.15, area.west + 0.05)
    cell = await climate.daily_series(cube_dataset_id("sorriso", 1, 0))

    assert await climate.regions() == [area]
    assert area.synthetic is True
    assert await climate.region_cube("sorriso") is cube
    assert cube.precipitation_mm.shape == (len(cube.dates), 2, 2)
    assert inside.dataset_id == "cube:sorriso:1:0"
    assert (inside.kind, inside.region_id, inside.source) == ("cube", "sorriso", "synthetic")
    assert np.array_equal(cell.precipitation_mm, cube.precipitation_mm[:, 1, 0])
    with pytest.raises(DatasetNotFoundError):
        await climate.describe(cube_dataset_id("sorriso", 2, 0))


async def test_export_evidence_returns_the_set_bytes_and_keeps_the_request() -> None:
    climate = FakeClimateFacade()
    dataset = climate.add_series(builders.daily_series())
    request = evidence_request(dataset.dataset_id)

    default = await climate.export_evidence(request)
    climate.set_evidence(b"netcdf-bytes-of-the-test")
    chosen = await climate.export_evidence(request)

    assert default == DEFAULT_EVIDENCE
    assert chosen == b"netcdf-bytes-of-the-test"
    assert climate.evidence_requests == [request, request]


async def test_fail_with_scripts_an_error_until_it_is_cleared() -> None:
    climate = FakeClimateFacade()
    climate.add_series(builders.daily_series())
    error = WeatherSourceUnavailableError()

    climate.fail_with(error)
    with pytest.raises(WeatherSourceUnavailableError) as raised:
        await climate.ensure_history(LAT, LON)
    with pytest.raises(WeatherSourceUnavailableError):
        await climate.resolve_location(None, LAT, LON)
    climate.fail_with(None)

    assert raised.value is error
    assert (await climate.ensure_history(LAT, LON)).kind == "point"
    assert len(climate.calls) == 3  # failed calls are recorded too


async def test_calls_lists_what_was_received_in_order() -> None:
    climate = FakeClimateFacade()
    climate.add_series(builders.daily_series())

    await climate.resolve_location(None, LAT, LON)
    await climate.ensure_history(LAT, LON)

    assert climate.calls == [
        ("resolve_location", (None, LAT, LON)),
        ("ensure_history", (LAT, LON)),
    ]
