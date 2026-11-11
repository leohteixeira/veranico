"""A showcase region as the module serves it."""

from veranico.modules.climate.application.ports import CubeSource
from veranico.modules.climate.contracts import Region
from veranico.modules.climate.domain.regions import RegionDef

REAL_CUBE_SOURCE = "era5-land/cds"


def served_region(definition: RegionDef, cube_source: CubeSource | None) -> Region:
    """The region with `synthetic` set from the source of its installed cube.

    A region with a synthetic cube and a region with no cube at all both answer
    `synthetic = True`: neither shows real weather history (human gate H1).
    """
    return Region(
        region_id=definition.region_id,
        name=definition.name,
        crop=definition.crop,
        north=definition.north,
        south=definition.south,
        west=definition.west,
        east=definition.east,
        step_deg=definition.step_deg,
        nx=definition.nx,
        ny=definition.ny,
        synthetic=cube_source != REAL_CUBE_SOURCE,
    )
