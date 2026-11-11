"""The cube against the point series, on recorded data (SPEC 4.4).

No real cube exists before human gate H1, so this proves the mechanism end to end, not the
agreement of the two products: a recorded Open-Meteo series is converted to metres, written
as yearly files in the shape of the download step, taken through the converter and the
store, and read back from the cube cell of the recorded place. Units, time alignment and
cell indexing must survive the trip; a copy shifted by one day and the neighbouring cell
must not pass.
"""

import json
import random
from pathlib import Path

import httpx
import numpy as np
import pytest

from tests.integration.climate.store_contract import CLOCK
from veranico.modules.climate.application.ports import CubeWrite, PointFetch
from veranico.modules.climate.domain.consistency import (
    PROVISIONAL_MAX_MEAN_ABS_DAILY_DIFF_MM,
    PROVISIONAL_MAX_RELATIVE_TOTAL_DIFF,
    ConsistencyReport,
    compare_series,
    within_tolerance,
)
from veranico.modules.climate.domain.regions import RegionDef, cell_centre, cell_of, region_by_id
from veranico.modules.climate.infrastructure.cube_build import convert_to_arrays, file_checksum
from veranico.modules.climate.infrastructure.local_store import LocalWeatherStore
from veranico.modules.climate.infrastructure.open_meteo import OpenMeteoArchive
from veranico.modules.climate.infrastructure.yearly_file import write_yearly_file
from veranico.shared.infrastructure.settings import ClimateSettings
from veranico.shared.kernel.ids import cube_dataset_id

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "consistency"
YEARS = (2020, 2021)

# One recorded place inside each region, and the region whose recording fills the other
# cells of the test cube: a different place, so a wrong cell cannot pass by accident.
PLACES = {
    "sul-de-minas": ((-21.55, -45.43), "sorriso"),  # Varginha
    "sorriso": ((-12.55, -55.72), "ribeirao-preto"),  # Sorriso
    "ribeirao-preto": ((-21.18, -47.81), "sul-de-minas"),  # Ribeirao Preto
}


async def recorded(region_id: str) -> PointFetch:
    """The recording of a region's place, parsed by the real Open-Meteo client."""
    recording = json.loads((FIXTURES / f"{region_id}_2020_2021.json").read_text())

    def answer(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == recording["request"]["url"]
        return httpx.Response(recording["status"], json=recording["body"])

    (lat, lon), _ = PLACES[region_id]
    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        source = OpenMeteoArchive(http, ClimateSettings(), rng=random.Random(0))
        return await source.fetch(lat, lon, *YEARS)


def region_of(region_id: str) -> RegionDef:
    region = region_by_id(region_id)
    assert region is not None
    return region


async def install_cube_from_recordings(
    root: Path, region: RegionDef, place: PointFetch, elsewhere: PointFetch, cell: tuple[int, int]
) -> LocalWeatherStore:
    """Yearly files in metres with `place` in `cell` and `elsewhere` in every other cell,
    through the converter and into a local store."""
    latitudes = np.array([cell_centre(region, row, 0)[0] for row in range(region.ny)])
    longitudes = np.array([cell_centre(region, 0, col)[1] for col in range(region.nx)])
    paths = []
    for year in YEARS:
        in_year = place.dates.astype("datetime64[Y]") == np.datetime64(str(year))
        metres = np.empty((int(in_year.sum()), region.ny, region.nx))
        metres[:] = (elsewhere.precipitation_mm[in_year] / 1000.0)[:, None, None]
        metres[:, cell[0], cell[1]] = place.precipitation_mm[in_year] / 1000.0
        path = root / f"{region.region_id}-{year}.nc"
        write_yearly_file(
            path, place.dates[in_year], latitudes, longitudes, metres, {"source": "recorded"}
        )
        paths.append(path)
    dates, millimetres = convert_to_arrays(paths, region)
    store = LocalWeatherStore(root / "weather", CLOCK)
    await store.write_cube(
        CubeWrite(
            region_id=region.region_id,
            source="synthetic",  # recorded point data in a cube is not the real cube
            dates=dates,
            precipitation_mm=millimetres,
            request={"source": "recorded Open-Meteo series, for the consistency test"},
            year_checksums={
                year: file_checksum(path) for year, path in zip(YEARS, paths, strict=True)
            },
        )
    )
    return store


@pytest.mark.req("R-4.4-3")
@pytest.mark.parametrize("region_id", sorted(PLACES))
async def test_the_cube_cell_of_a_place_agrees_with_its_recorded_point_series(
    region_id: str, tmp_path: Path
) -> None:
    (lat, lon), other = PLACES[region_id]
    region = region_of(region_id)
    place, elsewhere = await recorded(region_id), await recorded(other)
    row, col = cell_of(region, lat, lon)
    store = await install_cube_from_recordings(tmp_path, region, place, elsewhere, (row, col))

    dataset_id = await store.locate(lat, lon)
    assert dataset_id == cube_dataset_id(region_id, row, col)
    cell = await store.read_series(dataset_id)
    report = compare_series(cell.dates, cell.precipitation_mm, place.dates, place.precipitation_mm)

    assert within_tolerance(report)
    assert report.overlap_days == 731
    # The same data went in and came out: only the rounding of millimetres to metres and
    # back may separate them. A unit or alignment mistake is orders of magnitude larger.
    assert report.mean_abs_daily_diff_mm < 1e-9
    assert report.share_of_days_over_1mm == 0.0
    assert report.relative_total_diff < 1e-12


@pytest.mark.req("R-4.4-3")
@pytest.mark.parametrize("region_id", sorted(PLACES))
async def test_a_one_day_shift_and_the_neighbouring_cell_are_out_of_tolerance(
    region_id: str, tmp_path: Path
) -> None:
    (lat, lon), other = PLACES[region_id]
    region = region_of(region_id)
    place, elsewhere = await recorded(region_id), await recorded(other)
    row, col = cell_of(region, lat, lon)
    store = await install_cube_from_recordings(tmp_path, region, place, elsewhere, (row, col))
    cell = await store.read_series(cube_dataset_id(region_id, row, col))
    neighbour = await store.read_series(cube_dataset_id(region_id, row, col + 1))

    one_day = np.timedelta64(1, "D")
    shifted = compare_series(
        cell.dates + one_day, cell.precipitation_mm, place.dates, place.precipitation_mm
    )
    wrong_cell = compare_series(
        neighbour.dates, neighbour.precipitation_mm, place.dates, place.precipitation_mm
    )

    assert not within_tolerance(shifted)
    assert shifted.overlap_days == 730
    assert shifted.mean_abs_daily_diff_mm > PROVISIONAL_MAX_MEAN_ABS_DAILY_DIFF_MM
    assert not within_tolerance(wrong_cell)
    assert wrong_cell.mean_abs_daily_diff_mm > PROVISIONAL_MAX_MEAN_ABS_DAILY_DIFF_MM


@pytest.mark.req("R-4.4-3")
async def test_values_left_in_metres_are_out_of_tolerance() -> None:
    place = await recorded("sorriso")

    report = compare_series(
        place.dates, place.precipitation_mm / 1000.0, place.dates, place.precipitation_mm
    )

    assert not within_tolerance(report)
    assert report.relative_total_diff > PROVISIONAL_MAX_RELATIVE_TOTAL_DIFF


# `compare_series` on series written by hand.


def days(first: str, count: int) -> np.ndarray:
    return np.datetime64(first) + np.arange(count)


def test_the_report_of_two_hand_written_series() -> None:
    a = np.array([0.0, 2.0, 10.0, 4.0])
    b = np.array([0.5, 2.0, 7.0, 6.5])

    report = compare_series(days("2020-01-01", 4), a, days("2020-01-01", 4), b)

    assert report == ConsistencyReport(
        overlap_days=4,
        mean_abs_daily_diff_mm=(0.5 + 0.0 + 3.0 + 2.5) / 4,
        share_of_days_over_1mm=0.5,
        relative_total_diff=0.0,  # both total 16 mm
    )
    assert within_tolerance(report)  # 1.5 mm a day on average, exactly the limit


def test_only_the_days_both_series_have_a_value_for_are_compared() -> None:
    a = np.array([1.0, np.nan, 3.0, 4.0, 5.0])  # 1 to 5 January
    b = np.array([3.0, 9.0, 4.0, np.nan, 7.0])  # 3 to 7 January

    report = compare_series(days("2020-01-01", 5), a, days("2020-01-03", 5), b)

    # 3 January: 3 against 3. 4 January: 4 against 9. 5 January: 5 against 4.
    assert report.overlap_days == 3
    assert report.mean_abs_daily_diff_mm == (0.0 + 5.0 + 1.0) / 3
    assert report.share_of_days_over_1mm == pytest.approx(1 / 3)
    assert report.relative_total_diff == pytest.approx(4.0 / 14.0)  # 12 against 16


def test_series_without_a_common_day_are_never_within_tolerance() -> None:
    rain = np.ones(3)

    report = compare_series(days("2020-01-01", 3), rain, days("2021-01-01", 3), rain)

    assert report.overlap_days == 0
    assert not within_tolerance(report)


def test_two_dry_series_agree() -> None:
    dry = np.zeros(10)

    report = compare_series(days("2020-07-01", 10), dry, days("2020-07-01", 10), dry)

    assert report.relative_total_diff == 0.0
    assert within_tolerance(report)


def test_each_limit_fails_on_its_own() -> None:
    dates = days("2020-01-01", 4)
    # The same total, redistributed: 4 mm a day apart on average.
    moved = compare_series(
        dates, np.array([8.0, 0.0, 8.0, 0.0]), dates, np.array([0.0, 8.0, 0.0, 8.0])
    )
    # Close day by day, but one series is a fifth wetter in total.
    wetter = compare_series(dates, np.full(4, 5.0), dates, np.full(4, 6.1))

    assert moved.relative_total_diff == 0.0
    assert not within_tolerance(moved)
    assert wetter.mean_abs_daily_diff_mm < PROVISIONAL_MAX_MEAN_ABS_DAILY_DIFF_MM
    assert not within_tolerance(wetter)
