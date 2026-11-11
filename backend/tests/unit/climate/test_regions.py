"""Showcase regions and the cell geometry of the 0.1 degree grid."""

import pytest

from veranico.modules.climate.domain.regions import (
    REGIONS,
    cell_centre,
    cell_of,
    region_by_id,
    region_containing,
)

SUL_DE_MINAS = region_by_id("sul-de-minas")


@pytest.mark.req("R-4.1-1")
def test_three_regions_of_twenty_by_twenty_cells_on_the_tenth_degree_grid() -> None:
    assert [region.region_id for region in REGIONS] == ["sul-de-minas", "sorriso", "ribeirao-preto"]
    for region in REGIONS:
        assert (region.nx, region.ny, region.step_deg) == (20, 20, 0.1)
        assert region.north - region.south == pytest.approx(2.0)
        assert region.east - region.west == pytest.approx(2.0)


@pytest.mark.req("R-4.1-1")
def test_cell_centres_are_era5_land_grid_points() -> None:
    # ERA5-Land grid points are multiples of 0.1 degree, so every centre has one decimal.
    for region in REGIONS:
        for index in (0, 7, 19):
            lat, lon = cell_centre(region, index, index)
            assert round(lat, 1) == lat
            assert round(lon, 1) == lon


def test_the_boxes_do_not_overlap() -> None:
    for region in REGIONS:
        for row, col in ((0, 0), (0, 19), (19, 0), (19, 19), (10, 10)):
            lat, lon = cell_centre(region, row, col)
            assert region_containing(lat, lon) is region


def test_unknown_region_id_is_none() -> None:
    assert region_by_id("pampa") is None


def test_row_zero_is_the_northern_edge_and_column_zero_the_western() -> None:
    # Sul de Minas: north -20.45, west -46.55.
    assert cell_centre(SUL_DE_MINAS, 0, 0) == (-20.5, -46.5)
    assert cell_centre(SUL_DE_MINAS, 19, 19) == (-22.4, -44.6)
    assert cell_of(SUL_DE_MINAS, -20.5, -46.5) == (0, 0)
    assert cell_of(SUL_DE_MINAS, -22.4, -44.6) == (19, 19)
    north_row, _ = cell_of(SUL_DE_MINAS, -20.6, -45.0)
    south_row, _ = cell_of(SUL_DE_MINAS, -21.6, -45.0)
    assert north_row < south_row


def test_a_point_inside_a_cell_resolves_to_that_cell() -> None:
    # Varginha, about -21.55, -45.43: 11 cells south of -20.45, 11 cells east of -46.55.
    assert cell_of(SUL_DE_MINAS, -21.55, -45.43) == (11, 11)
    assert cell_centre(SUL_DE_MINAS, 11, 11) == (-21.6, -45.4)


def test_a_point_on_a_cell_edge_belongs_to_the_cell_south_and_east_of_it() -> None:
    # -20.55 is the edge between rows 0 and 1; -46.45 the edge between columns 0 and 1.
    assert cell_of(SUL_DE_MINAS, -20.55, -46.5) == (1, 0)
    assert cell_of(SUL_DE_MINAS, -20.5, -46.45) == (0, 1)
    assert cell_of(SUL_DE_MINAS, -20.55, -46.45) == (1, 1)


def test_region_corners() -> None:
    # The box includes its northern and western edges and excludes the other two.
    assert region_containing(-20.45, -46.55) is SUL_DE_MINAS
    assert cell_of(SUL_DE_MINAS, -20.45, -46.55) == (0, 0)
    assert region_containing(-22.45, -46.55) is None
    assert region_containing(-20.45, -44.55) is None
    assert region_containing(-22.45, -44.55) is None


def test_a_point_just_outside_is_in_no_region() -> None:
    assert region_containing(-20.4499, -45.0) is None
    assert region_containing(-21.0, -46.5501) is None
    assert region_containing(-22.4501, -45.0) is None
    assert region_containing(-21.0, -44.5499) is None
    assert region_containing(-22.4499, -44.5501) is SUL_DE_MINAS


def test_cell_of_rejects_a_point_outside_the_region() -> None:
    with pytest.raises(ValueError, match="outside"):
        cell_of(SUL_DE_MINAS, -10.0, -45.0)


def test_cell_centre_rejects_an_index_outside_the_grid() -> None:
    with pytest.raises(ValueError, match="outside"):
        cell_centre(SUL_DE_MINAS, 20, 0)
    with pytest.raises(ValueError, match="outside"):
        cell_centre(SUL_DE_MINAS, 0, -1)
