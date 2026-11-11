"""The three showcase regions and the cell geometry of their grids (SPEC 4.1).

Grid convention. ERA5-Land is delivered on a regular 0.1 degree grid whose points are
multiples of 0.1 degree (the grid starts at longitude 0, latitude 90). A cell is the
0.1 degree square centred on a grid point, so the edges of a box sit on the 0.05 marks and
every cell centre is a grid point. Row 0 is the northern edge and column 0 the western edge.
A cell owns its northern and western edges; a box therefore excludes its southern and
eastern edges.

The definitions hold geometry only. Whether a region currently runs on synthetic data
depends on the installed cube and is decided by the application layer.
"""

import math
from dataclasses import dataclass
from typing import Protocol

STEP_DEG = 0.1
CELLS_PER_SIDE = 20

# The geometry is computed in whole micro-degrees (about 0.1 m), so a point on an edge such
# as -20.55 is not moved across it by float error and a centre comes out as -20.5 exactly.
_MICRO = 1_000_000


def _micro(degrees: float) -> int:
    return math.floor(degrees * _MICRO + 0.5)


class Grid(Protocol):
    """What the geometry needs; satisfied by `RegionDef` and by the contract `Region`."""

    @property
    def north(self) -> float: ...
    @property
    def west(self) -> float: ...
    @property
    def step_deg(self) -> float: ...
    @property
    def nx(self) -> int: ...
    @property
    def ny(self) -> int: ...


@dataclass(frozen=True, slots=True)
class RegionDef:
    region_id: str
    name: str
    crop: str
    north: float
    west: float
    step_deg: float = STEP_DEG
    nx: int = CELLS_PER_SIDE
    ny: int = CELLS_PER_SIDE

    @property
    def south(self) -> float:
        return (_micro(self.north) - self.ny * _micro(self.step_deg)) / _MICRO

    @property
    def east(self) -> float:
        return (_micro(self.west) + self.nx * _micro(self.step_deg)) / _MICRO


# Each box is 2 by 2 degrees around the place that names it.
REGIONS: tuple[RegionDef, ...] = (
    # Varginha, Alfenas, Tres Pontas, Lavras: cell centres -20.5 to -22.4, -46.5 to -44.6.
    RegionDef("sul-de-minas", "Sul de Minas", "coffee", north=-20.45, west=-46.55),
    # Sorriso, Sinop, Lucas do Rio Verde: cell centres -11.6 to -13.5, -56.7 to -54.8.
    RegionDef("sorriso", "Sorriso", "soybean", north=-11.55, west=-56.75),
    # Ribeirao Preto, Sertaozinho, Jaboticabal: cell centres -20.2 to -22.1, -48.8 to -46.9.
    RegionDef("ribeirao-preto", "Ribeirão Preto", "sugarcane", north=-20.15, west=-48.85),
)


def region_by_id(region_id: str) -> RegionDef | None:
    return next((region for region in REGIONS if region.region_id == region_id), None)


def region_containing(lat: float, lon: float) -> RegionDef | None:
    """The showcase region whose box holds the point; the boxes do not overlap."""
    return next((region for region in REGIONS if _index(region, lat, lon) is not None), None)


def cell_of(grid: Grid, lat: float, lon: float) -> tuple[int, int]:
    """(row, col) of the cell holding the point. Raises `ValueError` outside the grid."""
    index = _index(grid, lat, lon)
    if index is None:
        raise ValueError(f"({lat}, {lon}) is outside the grid")
    return index


def cell_centre(grid: Grid, row: int, col: int) -> tuple[float, float]:
    """(lat, lon) of a cell's centre, which is an ERA5-Land grid point."""
    if not (0 <= row < grid.ny and 0 <= col < grid.nx):
        raise ValueError(f"cell ({row}, {col}) is outside the grid")
    step = _micro(grid.step_deg)
    return (
        (_micro(grid.north) - (2 * row + 1) * step // 2) / _MICRO,
        (_micro(grid.west) + (2 * col + 1) * step // 2) / _MICRO,
    )


def _index(grid: Grid, lat: float, lon: float) -> tuple[int, int] | None:
    step = _micro(grid.step_deg)
    row = (_micro(grid.north) - _micro(lat)) // step
    col = (_micro(lon) - _micro(grid.west)) // step
    if 0 <= row < grid.ny and 0 <= col < grid.nx:
        return row, col
    return None
