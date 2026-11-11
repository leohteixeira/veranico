"""`convert_years`: yearly files in metres to one validated cube in millimetres."""

import hashlib
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import RegionDef
from veranico.modules.climate.infrastructure.cube_build import convert_years, file_checksum
from veranico.modules.climate.infrastructure.synthetic import write_synthetic_year
from veranico.modules.climate.infrastructure.yearly_file import write_yearly_file

# Two rows by three columns on the 0.1 degree lattice: centres -11.6, -11.7 by -56.7 to -56.5.
TINY = RegionDef("tiny", "Tiny", "soybean", north=-11.55, west=-56.75, nx=3, ny=2)
LATITUDES = np.array([-11.6, -11.7])
LONGITUDES = np.array([-56.7, -56.6, -56.5])


def days_of(year: int) -> np.ndarray:
    return np.arange(f"{year}-01-01", f"{year + 1}-01-01", dtype="datetime64[D]")


def write_year(
    path: Path,
    year: int,
    metres: np.ndarray | None = None,
    *,
    days: np.ndarray | None = None,
    latitudes: np.ndarray = LATITUDES,
    longitudes: np.ndarray = LONGITUDES,
) -> Path:
    """A hand-written yearly file: 0.001 m everywhere unless `metres` is given."""
    days = days_of(year) if days is None else days
    if metres is None:
        metres = np.full((len(days), len(latitudes), len(longitudes)), 0.001)
    write_yearly_file(path, days, latitudes, longitudes, metres, {"source": "test"})
    return path


def values_of(paths: list[Path]) -> np.ndarray:
    return convert_years(paths, TINY)["precipitation_mm"].to_numpy()


@pytest.mark.req("R-4.1-2")
def test_metres_become_millimetres(tmp_path: Path) -> None:
    metres = np.zeros((365, 2, 3))
    metres[10, 1, 2] = 0.0025

    cube = convert_years([write_year(tmp_path / "2001.nc", 2001, metres)], TINY)

    values = cube["precipitation_mm"]
    assert values.dims == ("time", "lat", "lon")
    assert values.dtype == np.float64
    assert values.shape == (365, 2, 3)
    assert values.to_numpy()[10, 1, 2] == 2.5
    assert values.to_numpy().sum() == 2.5
    assert cube["lat"].to_numpy().tolist() == [-11.6, -11.7]
    assert cube["lon"].to_numpy().tolist() == [-56.7, -56.6, -56.5]
    assert cube["time"].to_numpy()[10] == np.datetime64("2001-01-11")


@pytest.mark.req("R-4.1-2")
def test_row_0_is_the_northern_edge_whatever_the_order_in_the_file(tmp_path: Path) -> None:
    write_synthetic_year(tmp_path / "north.nc", TINY, 2001, seed=3)
    write_synthetic_year(tmp_path / "south.nc", TINY, 2001, seed=3, south_to_north=True)

    north_first = values_of([tmp_path / "north.nc"])
    south_first = values_of([tmp_path / "south.nc"])

    assert np.array_equal(north_first, south_first)
    assert not np.array_equal(north_first[:, 0, :], north_first[:, 1, :])


def test_a_hand_written_file_ordered_south_to_north_is_turned(tmp_path: Path) -> None:
    metres = np.zeros((365, 2, 3))
    metres[0, 0, 0] = 0.004  # the first latitude of the file, which is the southern one
    path = write_year(tmp_path / "2001.nc", 2001, metres, latitudes=LATITUDES[::-1])

    values = values_of([path])

    assert values[0, 1, 0] == 4.0  # row 1 is the southern row
    assert values[0, 0, 0] == 0.0


def test_years_merge_in_time_order_whatever_the_order_of_the_paths(tmp_path: Path) -> None:
    for year in (2001, 2002, 2003):
        write_synthetic_year(tmp_path / f"{year}.nc", TINY, year, seed=3)
    ordered = [tmp_path / f"{year}.nc" for year in (2001, 2002, 2003)]

    cube = convert_years([ordered[2], ordered[0], ordered[1]], TINY)

    dates = cube["time"].to_numpy().astype("datetime64[D]")
    assert (dates[0], dates[-1]) == (np.datetime64("2001-01-01"), np.datetime64("2003-12-31"))
    assert len(dates) == 3 * 365
    assert np.array_equal(cube["precipitation_mm"].to_numpy(), values_of(ordered))
    assert np.array_equal(cube["precipitation_mm"].to_numpy()[365:730], values_of([ordered[1]]))


def test_a_file_wider_than_the_region_is_cut_to_its_grid(tmp_path: Path) -> None:
    latitudes = np.array([-11.5, -11.6, -11.7, -11.8])
    longitudes = np.array([-56.8, -56.7, -56.6, -56.5, -56.4])
    metres = np.zeros((365, 4, 5))
    metres[:, 1, 1] = 0.001  # the grid point -11.6, -56.7: cell (0, 0) of the region
    metres[:, 0, 0] = 0.009  # outside the region
    path = write_year(
        tmp_path / "2001.nc", 2001, metres, latitudes=latitudes, longitudes=longitudes
    )

    values = values_of([path])

    assert values.shape == (365, 2, 3)
    assert (values[:, 0, 0] == 1.0).all()
    assert values[:, 1:, :].sum() == 0.0


def test_coordinates_stored_as_32_bit_floats_still_match(tmp_path: Path) -> None:
    path = write_year(
        tmp_path / "2001.nc",
        2001,
        latitudes=LATITUDES.astype(np.float32).astype(np.float64),
        longitudes=LONGITUDES.astype(np.float32).astype(np.float64),
    )

    cube = convert_years([path], TINY)

    assert cube["lat"].to_numpy().tolist() == [-11.6, -11.7]  # the region's own grid points


def test_missing_values_stay_missing(tmp_path: Path) -> None:
    metres = np.full((365, 2, 3), 0.001)
    metres[7, 0, 1] = np.nan

    values = values_of([write_year(tmp_path / "2001.nc", 2001, metres)])

    assert np.isnan(values[7, 0, 1])
    assert np.isnan(values).sum() == 1


# What must fail, with a message that says why.


@pytest.mark.req("R-4.4-1")
def test_a_missing_year_fails(tmp_path: Path) -> None:
    paths = [write_year(tmp_path / f"{year}.nc", year) for year in (2001, 2003, 2004)]

    with pytest.raises(WeatherDataError, match=r"missing year\(s\) 2002"):
        convert_years(paths, TINY)


def test_two_files_for_one_year_fail(tmp_path: Path) -> None:
    paths = [write_year(tmp_path / "a.nc", 2001), write_year(tmp_path / "b.nc", 2001)]

    with pytest.raises(WeatherDataError, match="more than one file for the year"):
        convert_years(paths, TINY)


@pytest.mark.req("R-4.4-1")
def test_a_duplicate_date_fails(tmp_path: Path) -> None:
    days = days_of(2001)
    days[100] = days[99]

    with pytest.raises(WeatherDataError, match="duplicate date: 2001-04-10"):
        convert_years([write_year(tmp_path / "2001.nc", 2001, days=days)], TINY)


@pytest.mark.req("R-4.4-1")
def test_a_negative_value_fails_and_names_the_cell(tmp_path: Path) -> None:
    metres = np.full((365, 2, 3), 0.001)
    metres[40, 1, 2] = -0.0001

    with pytest.raises(WeatherDataError, match=r"cell \(1, 2\): negative precipitation"):
        convert_years([write_year(tmp_path / "2001.nc", 2001, metres)], TINY)


def test_a_file_that_is_not_a_whole_year_fails(tmp_path: Path) -> None:
    path = write_year(tmp_path / "2001.nc", 2001, days=days_of(2001)[:-1])

    with pytest.raises(WeatherDataError, match="expected the whole year 2001"):
        convert_years([path], TINY)


def test_a_file_spanning_two_years_fails(tmp_path: Path) -> None:
    days = np.arange("2001-01-01", "2003-01-01", dtype="datetime64[D]")
    path = write_year(tmp_path / "2001.nc", 2001, days=days)

    with pytest.raises(WeatherDataError, match="expected the whole year 2001"):
        convert_years([path], TINY)


def test_a_file_that_does_not_cover_the_grid_fails(tmp_path: Path) -> None:
    path = write_year(tmp_path / "2001.nc", 2001, longitudes=np.array([-56.7, -56.6, -56.4]))

    with pytest.raises(WeatherDataError, match=r"no longitude for the grid point\(s\) -56.5"):
        convert_years([path], TINY)


def test_a_file_in_another_unit_fails(tmp_path: Path) -> None:
    path = write_year(tmp_path / "metres.nc", 2001)
    with xr.open_dataset(path, engine="h5netcdf") as dataset:
        loaded = dataset.load()
    loaded["tp"].attrs["units"] = "mm"
    loaded.to_netcdf(tmp_path / "millimetres.nc", engine="h5netcdf")

    with pytest.raises(WeatherDataError, match="is in 'mm', expected 'm'"):
        convert_years([tmp_path / "millimetres.nc"], TINY)


def test_a_file_without_the_variable_fails(tmp_path: Path) -> None:
    path = write_year(tmp_path / "tp.nc", 2001)
    with xr.open_dataset(path, engine="h5netcdf") as dataset:
        loaded = dataset.load()
    loaded.rename({"tp": "total_precipitation"}).to_netcdf(
        tmp_path / "renamed.nc", engine="h5netcdf"
    )

    with pytest.raises(WeatherDataError, match="no variable 'tp', found"):
        convert_years([tmp_path / "renamed.nc"], TINY)


def test_no_file_at_all_fails() -> None:
    with pytest.raises(WeatherDataError, match="no yearly file"):
        convert_years([], TINY)


def test_the_file_checksum_follows_the_bytes(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"rain")
    (tmp_path / "b").write_bytes(b"rain")
    (tmp_path / "c").write_bytes(b"rain.")

    assert file_checksum(tmp_path / "a") == file_checksum(tmp_path / "b")
    assert file_checksum(tmp_path / "a") != file_checksum(tmp_path / "c")
    assert file_checksum(tmp_path / "a") == "sha256:" + hashlib.sha256(b"rain").hexdigest()
