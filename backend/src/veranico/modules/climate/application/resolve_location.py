"""Use case behind `ClimateFacade.resolve_location` (SPEC 4.3).

A place name goes to the geocoder; coordinates are answered locally, with no network call,
because `quoting` resolves the coordinates of every `POST /quotes` through this path.
"""

from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.application.ports import GeocodeHit, Geocoder
from veranico.modules.climate.contracts import Location, LocationCandidates
from veranico.modules.climate.domain.brazil import (
    COUNTRY_CODE,
    in_brazil_box,
    names_the_country,
    state_abbreviation,
)
from veranico.shared.kernel.errors import (
    InvalidArgumentsError,
    LocationNotFoundError,
    OutsideCoverageError,
)

MAX_CANDIDATES = 5


class ResolveLocation:
    def __init__(self, geocoder: Geocoder) -> None:
        self._geocoder = geocoder

    async def __call__(
        self, query: str | None, lat: float | None, lon: float | None
    ) -> Location | LocationCandidates:
        if query is None and lat is not None and lon is not None:
            return _from_coordinates(lat, lon)
        if query is not None and query.strip() and lat is None and lon is None:
            return await self._from_name(query)
        raise InvalidArgumentsError("give either a place name or both coordinates")

    async def _from_name(self, query: str) -> Location | LocationCandidates:
        # "Sorriso, MT": the text before the first comma is the place, the text between the
        # first and the second comma the user's own disambiguation.
        name, _, rest = query.partition(",")
        qualifier = rest.partition(",")[0].strip()
        if not name.strip():
            raise InvalidArgumentsError("the place name is empty")

        hits = [hit for hit in await self._geocoder.search(name.strip()) if _in_brazil(hit)]
        if qualifier and not names_the_country(qualifier):
            wanted = state_abbreviation(qualifier)
            hits = [
                hit
                for hit in hits
                if wanted is not None and hit.admin1 and state_abbreviation(hit.admin1) == wanted
            ]

        # One entry per label, in the geocoder's order: it lists a town and its districts
        # under one name and state, and identical candidates would not help anyone choose.
        locations: dict[str, Location] = {}
        for hit in hits:
            location = _location(hit)
            locations.setdefault(location.label, location)
        found = list(locations.values())
        if not found:
            raise LocationNotFoundError
        if len(found) == 1:
            return found[0]
        return LocationCandidates(candidates=found[:MAX_CANDIDATES])


def _in_brazil(hit: GeocodeHit) -> bool:
    return hit.country_code == COUNTRY_CODE and in_brazil_box(hit.lat, hit.lon)


def _location(hit: GeocodeHit) -> Location:
    state = state_abbreviation(hit.admin1) if hit.admin1 else None
    region = state or hit.admin1
    return Location(
        label=f"{hit.name}, {region}" if region else hit.name,
        lat=hit.lat,
        lon=hit.lon,
        h3_cell=h3_cell_of(hit.lat, hit.lon),
        admin_region=hit.admin1,
        country_code=COUNTRY_CODE,
    )


def _from_coordinates(lat: float, lon: float) -> Location:
    if not in_brazil_box(lat, lon):  # also false for NaN
        raise OutsideCoverageError("the point is outside Brazil")
    return Location(
        label=f"{lat:.4f}, {lon:.4f}",
        lat=lat,
        lon=lon,
        h3_cell=h3_cell_of(lat, lon),
        admin_region=None,
        country_code=COUNTRY_CODE,
    )
