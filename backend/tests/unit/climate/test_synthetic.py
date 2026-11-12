"""The synthetic generators: seeded, valid, and shaped like rain."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from veranico.modules.climate.contracts import RegionCube
from veranico.modules.climate.domain.regions import RegionDef, region_by_id
from veranico.modules.climate.domain.validation import validate_daily
from veranico.modules.climate.infrastructure.synthetic import (
    generate_cube,
    write_synthetic_year,
)

SORRISO = region_by_id("sorriso")
assert SORRISO is not None
# A grid of a few cells, on the same 0.1 degree lattice.
TINY = RegionDef("tiny", "Tiny", "soybean", north=-11.55, west=-56.75, nx=3, ny=2)


@pytest.fixture(scope="module")
def cube() -> RegionCube:
    return generate_cube(SORRISO, 1990, 2009, seed=1)


def test_shape_dates_and_region(cube: RegionCube) -> None:
    assert cube.precipitation_mm.shape == (7305, 20, 20)  # 20 years, five of them leap years
    assert cube.precipitation_mm.dtype == np.float64
    assert cube.dates.dtype == np.dtype("datetime64[D]")
    assert cube.dates[0] == np.datetime64("1990-01-01")
    assert cube.dates[-1] == np.datetime64("2009-12-31")
    assert (np.diff(cube.dates).astype(np.int64) == 1).all()  # continuous
    assert cube.region.region_id == "sorriso"
    assert (cube.region.nx, cube.region.ny) == (20, 20)
    assert (cube.region.north, cube.region.south) == (-11.55, -13.55)


def test_a_synthetic_cube_says_it_is_synthetic(cube: RegionCube) -> None:
    assert cube.region.synthetic is True


def test_the_same_seed_gives_identical_arrays_and_another_seed_does_not() -> None:
    first = generate_cube(SORRISO, 2000, 2002, seed=7)
    again = generate_cube(SORRISO, 2000, 2002, seed=7)
    other = generate_cube(SORRISO, 2000, 2002, seed=8)

    assert np.array_equal(first.precipitation_mm, again.precipitation_mm)
    assert np.array_equal(first.dates, again.dates)
    assert not np.array_equal(first.precipitation_mm, other.precipitation_mm)


def test_no_negative_and_no_missing_value(cube: RegionCube) -> None:
    assert (cube.precipitation_mm >= 0).all()
    assert np.isfinite(cube.precipitation_mm).all()


@pytest.mark.req("R-4.4-1")
def test_validate_daily_accepts_every_cell(cube: RegionCube) -> None:
    for row in range(20):
        for col in range(20):
            assert validate_daily(cube.dates, cube.precipitation_mm[:, row, col]) == 0


def test_seasonal_totals_of_two_opposite_corner_cells_differ(cube: RegionCube) -> None:
    months = cube.dates.astype("datetime64[M]").astype(np.int64) % 12 + 1
    wet_season = np.isin(months, [11, 12, 1, 2, 3])
    north_east = cube.precipitation_mm[wet_season, 0, 19].sum()
    south_west = cube.precipitation_mm[wet_season, 19, 0].sum()

    # The gradient rises towards the north-east: 1.25 against 0.75 of the centre.
    assert north_east > 1.3 * south_west


def test_there_is_a_wet_and_a_dry_season(cube: RegionCube) -> None:
    months = cube.dates.astype("datetime64[M]").astype(np.int64) % 12 + 1
    january = cube.precipitation_mm[months == 1].mean()
    july = cube.precipitation_mm[months == 7].mean()
    wet_days_january = (cube.precipitation_mm[months == 1] >= 1.0).mean()
    wet_days_july = (cube.precipitation_mm[months == 7] >= 1.0).mean()

    assert january > 8 * july
    assert wet_days_january > 0.4
    assert wet_days_july < 0.1


def test_annual_totals_look_like_rain_and_vary_between_years(cube: RegionCube) -> None:
    years = cube.dates.astype("datetime64[Y]").astype(np.int64) + 1970
    totals = np.array(
        [cube.precipitation_mm[years == year].mean(axis=(1, 2)).sum() for year in range(1990, 2010)]
    )

    assert 800 < totals.mean() < 2200  # millimetres a year, averaged over the region
    assert totals.std() / totals.mean() > 0.05  # wetter and drier years


def test_neighbouring_cells_agree_mostly_but_are_not_copies(cube: RegionCube) -> None:
    centre = cube.precipitation_mm[:, 10, 10]
    neighbour = cube.precipitation_mm[:, 10, 11]
    far = cube.precipitation_mm[:, 0, 0]

    near_correlation = np.corrcoef(centre, neighbour)[0, 1]
    far_correlation = np.corrcoef(centre, far)[0, 1]
    assert not np.array_equal(centre, neighbour)
    assert 0.3 < near_correlation < 0.98
    assert far_correlation < near_correlation
    # The days on which exactly one of two neighbours is wet are what basis risk is made of.
    assert ((centre >= 1.0) != (neighbour >= 1.0)).mean() > 0.02


def test_an_empty_range_of_years_is_refused() -> None:
    with pytest.raises(ValueError, match="empty range"):
        generate_cube(SORRISO, 2001, 2000, seed=1)


def test_the_full_history_has_the_size_the_service_will_hold() -> None:
    full = generate_cube(SORRISO, 1950, 2025, seed=1)

    assert full.precipitation_mm.shape == (27759, 20, 20)
    assert full.precipitation_mm.nbytes == 27759 * 400 * 8  # about 89 MB decoded


# The yearly file in the shape the cube converter reads.


def test_a_synthetic_yearly_file_is_shaped_like_the_converter_input(tmp_path: Path) -> None:
    target = tmp_path / "tiny-2001.nc"

    write_synthetic_year(target, TINY, 2001, seed=3)

    with xr.open_dataset(target, engine="h5netcdf") as dataset:
        assert list(dataset.data_vars) == ["tp"]
        precipitation = dataset["tp"]
        assert precipitation.dims == ("valid_time", "latitude", "longitude")
        assert precipitation.attrs["units"] == "m"
        assert precipitation.shape == (365, 2, 3)
        assert dataset["latitude"].to_numpy().tolist() == [-11.6, -11.7]  # north to south
        assert dataset["longitude"].to_numpy().tolist() == [-56.7, -56.6, -56.5]
        days = dataset["valid_time"].to_numpy().astype("datetime64[D]")
        assert (days[0], days[-1]) == (np.datetime64("2001-01-01"), np.datetime64("2001-12-31"))
        values = precipitation.to_numpy()
        assert (values >= 0).all()
        assert 0.3 < values.sum(axis=0).min() < 5.0  # metres a year: the unit is not millimetres
        assert dataset.attrs["source"] == "synthetic"


def test_yearly_files_are_seeded_per_year_and_independent_of_writing_order(tmp_path: Path) -> None:
    def values(name: str) -> np.ndarray:
        with xr.open_dataset(tmp_path / name, engine="h5netcdf") as dataset:
            return dataset["tp"].to_numpy()

    write_synthetic_year(tmp_path / "a-2001.nc", TINY, 2001, seed=3)
    write_synthetic_year(tmp_path / "a-2002.nc", TINY, 2002, seed=3)
    write_synthetic_year(tmp_path / "b-2002.nc", TINY, 2002, seed=3)
    write_synthetic_year(tmp_path / "c-2002.nc", TINY, 2002, seed=4)

    assert np.array_equal(values("a-2002.nc"), values("b-2002.nc"))
    assert not np.array_equal(values("a-2002.nc"), values("c-2002.nc"))
    assert not np.array_equal(values("a-2001.nc"), values("a-2002.nc")[:365])


def test_a_file_ordered_south_to_north_holds_the_same_field(tmp_path: Path) -> None:
    write_synthetic_year(tmp_path / "north.nc", TINY, 2001, seed=3)
    write_synthetic_year(tmp_path / "south.nc", TINY, 2001, seed=3, south_to_north=True)

    with (
        xr.open_dataset(tmp_path / "north.nc", engine="h5netcdf") as north,
        xr.open_dataset(tmp_path / "south.nc", engine="h5netcdf") as south,
    ):
        assert south["latitude"].to_numpy().tolist() == [-11.7, -11.6]
        assert np.array_equal(
            south["tp"].sel(latitude=-11.6).to_numpy(), north["tp"].sel(latitude=-11.6).to_numpy()
        )
