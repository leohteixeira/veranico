"""The H3 cell that keys point stores and aliases (SPEC 4.2: resolution 6)."""

import h3

H3_RESOLUTION = 6


def h3_cell_of(lat: float, lon: float) -> str:
    """The resolution 6 cell holding a point given in degrees."""
    cell: str = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
    return cell
