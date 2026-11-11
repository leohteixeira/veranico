"""Seeded synthetic precipitation: the data of the showcase regions until human gate H1.

Nothing here is weather history. A generated cube is marked `Region.synthetic = True`, and
whoever stores it records the source `synthetic`; the interface labels it from those fields.

The model is deliberately simple and only has to look like rain to the pricing engine and
the map: a wet season around January and a dry one around July, a wet or dry day decided by
a smooth random field (so neighbouring cells mostly agree and sometimes do not), gamma
amounts on wet days, a north-east to south-west gradient, and wetter and drier years.
Every number comes from `numpy.random.default_rng(seed)`: the same arguments give the same
arrays.
"""

from pathlib import Path
from statistics import NormalDist

import numpy as np

from veranico.modules.climate.application.served_region import served_region
from veranico.modules.climate.contracts import RegionCube
from veranico.modules.climate.domain.regions import Grid, RegionDef, cell_centre
from veranico.modules.climate.infrastructure.yearly_file import write_yearly_file

# Climate of the model. Days are counted from 1 January; the wet season peaks mid-January.
_WET_PEAK_DAY = 15.0
_WET_DAY_SHARE_DRY_SEASON = 0.06
_WET_DAY_SHARE_WET_SEASON = 0.62
_GAMMA_SHAPE = 0.75
_MEAN_SCALE_MM_DRY_SEASON = 5.0
_MEAN_SCALE_MM_WET_SEASON = 17.0
_GRADIENT = 0.25  # the north-east corner gets 25% more than the centre, the south-west less
_YEAR_SIGMA = 0.15  # spread of the wetter and drier years
# The latent field of a day: this share of its variance is smooth over the region, the rest
# is independent per cell.
_SMOOTH_SHARE = 0.75
_COARSE = 5  # the smooth part is drawn on a 5 by 5 grid and interpolated
_AMOUNT_JITTER = 0.25  # log-scale spread of the amount between cells of one day

# Named in a cube's manifest. Change the version whenever the model or a value above
# changes, so a stored cube says which generator made it.
GENERATOR = "veranico-synthetic/1"


def generator_parameters() -> dict[str, str]:
    """The values of the model, recorded with a generated cube as its provenance."""
    return {
        "wet_peak_day": str(_WET_PEAK_DAY),
        "wet_day_share_dry_season": str(_WET_DAY_SHARE_DRY_SEASON),
        "wet_day_share_wet_season": str(_WET_DAY_SHARE_WET_SEASON),
        "gamma_shape": str(_GAMMA_SHAPE),
        "mean_scale_mm_dry_season": str(_MEAN_SCALE_MM_DRY_SEASON),
        "mean_scale_mm_wet_season": str(_MEAN_SCALE_MM_WET_SEASON),
        "gradient": str(_GRADIENT),
        "year_sigma": str(_YEAR_SIGMA),
        "smooth_share": str(_SMOOTH_SHARE),
        "coarse_nodes": str(_COARSE),
        "amount_jitter": str(_AMOUNT_JITTER),
    }


def generate_cube(region: RegionDef, first_year: int, last_year: int, seed: int) -> RegionCube:
    """A full-size synthetic cube of `region` for the years `first_year` to `last_year`.

    Shape (days, ny, nx), row 0 at the northern edge, float64 millimetres, no missing and
    no negative value. The returned `Region` has `synthetic = True`.
    """
    if first_year > last_year:
        raise ValueError(f"empty range of years: {first_year} to {last_year}")
    rng = np.random.default_rng(seed)
    gradient = _gradient(region.ny, region.nx)
    years = [
        _year_of_rain(rng, year, region.ny, region.nx) * gradient
        for year in range(first_year, last_year + 1)
    ]
    return RegionCube(
        region=served_region(region, "synthetic"),
        dates=_days(first_year, last_year),
        precipitation_mm=np.concatenate(years),
    )


def write_synthetic_cds_year(
    path: Path, region: Grid, year: int, seed: int, *, south_to_north: bool = False
) -> None:
    """Write one synthetic yearly file in the shape the cube converter reads (metres).

    `region` is any grid, usually a few cells. The values depend on the seed and the year
    only, so the files of several years are independent of the order they are written in.
    Latitudes run north to south, as in ERA5 files, unless `south_to_north` is set: the
    converter must cope with either.
    """
    rng = np.random.default_rng([seed, year])
    rain_mm = _year_of_rain(rng, year, region.ny, region.nx) * _gradient(region.ny, region.nx)
    latitudes = np.array([cell_centre(region, row, 0)[0] for row in range(region.ny)])
    longitudes = np.array([cell_centre(region, 0, col)[1] for col in range(region.nx)])
    if south_to_north:
        latitudes, rain_mm = latitudes[::-1], rain_mm[:, ::-1, :]
    write_yearly_file(
        path,
        _days(year, year),
        latitudes,
        longitudes,
        rain_mm / 1000.0,
        {"source": "synthetic", "year": str(year), "seed": str(seed)},
    )


def _days(first_year: int, last_year: int) -> np.ndarray:
    return np.arange(f"{first_year}-01-01", f"{last_year + 1}-01-01", dtype="datetime64[D]")


def _gradient(ny: int, nx: int) -> np.ndarray:
    """A plane rising from the south-west corner to the north-east corner, mean 1."""
    northness = 0.5 - np.arange(ny) / max(ny - 1, 1)  # +0.5 at row 0 (north)
    eastness = np.arange(nx) / max(nx - 1, 1) - 0.5  # +0.5 at the last column (east)
    plane: np.ndarray = 1.0 + _GRADIENT * (northness[:, None] + eastness[None, :])
    return plane


def _year_of_rain(rng: np.random.Generator, year: int, ny: int, nx: int) -> np.ndarray:
    """Daily rain in millimetres for one year, shape (days, ny, nx), before the gradient."""
    days = _days(year, year)
    day_of_year = (days - days[0]).astype(np.int64)
    # 1 at the peak of the wet season, 0 at the peak of the dry season.
    wetness = 0.5 + 0.5 * np.cos(2 * np.pi * (day_of_year - _WET_PEAK_DAY) / 365.25)
    wet_share = _WET_DAY_SHARE_DRY_SEASON + wetness * (
        _WET_DAY_SHARE_WET_SEASON - _WET_DAY_SHARE_DRY_SEASON
    )
    scale = _MEAN_SCALE_MM_DRY_SEASON + wetness * (
        _MEAN_SCALE_MM_WET_SEASON - _MEAN_SCALE_MM_DRY_SEASON
    )
    year_factor = float(np.exp(rng.normal(0.0, _YEAR_SIGMA)))

    smooth = _smooth_field(rng, len(days), ny, nx)
    latent = np.sqrt(_SMOOTH_SHARE) * smooth + np.sqrt(1 - _SMOOTH_SHARE) * rng.standard_normal(
        (len(days), ny, nx)
    )
    # A day is wet where the latent field exceeds the quantile that leaves `wet_share` above.
    normal = NormalDist()
    threshold = np.array([normal.inv_cdf(1.0 - share) for share in wet_share])
    wet = latent > threshold[:, None, None]

    # The amount of a day is smooth over the region too (a gamma drawn on the coarse grid
    # and interpolated, which keeps it positive), times a small jitter per cell.
    rows, columns = _interpolation(ny), _interpolation(nx)
    coarse_amount = rng.gamma(_GAMMA_SHAPE, 1.0, size=(len(days), _COARSE, _COARSE))
    amount = np.einsum("ai,tij,bj->tab", rows, coarse_amount, columns)
    amount *= np.exp(_AMOUNT_JITTER * rng.standard_normal((len(days), ny, nx)))
    amount *= (scale * year_factor)[:, None, None]
    rain: np.ndarray = np.where(wet, amount, 0.0)
    return rain


def _smooth_field(rng: np.random.Generator, days: int, ny: int, nx: int) -> np.ndarray:
    """A unit-variance field per day that varies slowly across the grid."""
    coarse = rng.standard_normal((days, _COARSE, _COARSE))
    rows, columns = _interpolation(ny), _interpolation(nx)
    field: np.ndarray = np.einsum("ai,tij,bj->tab", rows, coarse, columns)
    # Interpolating independent normals shrinks the variance between the nodes: restore it.
    spread = np.sqrt(np.einsum("ai,bj->ab", rows**2, columns**2))
    restored: np.ndarray = field / spread
    return restored


def _interpolation(size: int) -> np.ndarray:
    """Linear interpolation weights from `_COARSE` nodes to `size` cells, shape (size, nodes)."""
    positions = np.linspace(0.0, _COARSE - 1.0, size) if size > 1 else np.array([0.0])
    lower = np.minimum(np.floor(positions).astype(np.int64), _COARSE - 2)
    share = positions - lower
    weights = np.zeros((size, _COARSE))
    weights[np.arange(size), lower] = 1.0 - share
    weights[np.arange(size), lower + 1] = share
    return weights
