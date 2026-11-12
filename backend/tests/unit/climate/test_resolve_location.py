"""Location resolution on recorded geocoding answers (SPEC 4.3)."""

import random

import h3
import pytest

from tests.unit.climate.replay import Replay, replaying
from veranico.modules.climate.application.ports import GeocodeHit
from veranico.modules.climate.application.resolve_location import ResolveLocation
from veranico.modules.climate.contracts import Location, LocationCandidates
from veranico.modules.climate.domain.brazil import STATES, state_abbreviation
from veranico.modules.climate.infrastructure.open_meteo_geocoding import OpenMeteoGeocoder
from veranico.shared.infrastructure.settings import ClimateSettings
from veranico.shared.kernel.errors import (
    InvalidArgumentsError,
    LocationNotFoundError,
    OutsideCoverageError,
)

RECORDINGS = (
    "geocoding/sorriso.json",
    "geocoding/bonito.json",
    "geocoding/varginha.json",
    "geocoding/ribeirao_preto.json",
    "geocoding/reykjavik.json",
)


async def no_sleep(seconds: float) -> None:
    raise AssertionError("a successful request must not wait")


def recorded() -> tuple[ResolveLocation, Replay]:
    replay = replaying(*RECORDINGS)
    geocoder = OpenMeteoGeocoder(
        replay.client(), ClimateSettings(), rng=random.Random(0), sleep=no_sleep
    )
    return ResolveLocation(geocoder), replay


class NeverCalled:
    async def search(self, name: str) -> list[GeocodeHit]:
        raise AssertionError("the coordinate path must not call the geocoder")


class Canned:
    def __init__(self, *hits: GeocodeHit) -> None:
        self._hits = list(hits)

    async def search(self, name: str) -> list[GeocodeHit]:
        return self._hits


@pytest.mark.req("R-4.3-1")
async def test_a_unique_name_resolves_to_a_location() -> None:
    resolve, replay = recorded()

    location = await resolve("Sorriso", None, None)

    # The recording also holds "Sorriso Airport", which is not a populated place.
    assert location == Location(
        label="Sorriso, MT",
        lat=-12.54528,
        lon=-55.71139,
        h3_cell=h3.latlng_to_cell(-12.54528, -55.71139, 6),
        admin_region="Mato Grosso",
        country_code="BR",
    )
    assert h3.get_resolution(location.h3_cell) == 6
    assert len(replay.calls) == 1


@pytest.mark.req("R-4.3-1")
async def test_a_name_with_accents_resolves() -> None:
    resolve, _ = recorded()

    location = await resolve("Ribeirão Preto", None, None)

    assert isinstance(location, Location)
    assert (location.label, location.admin_region) == ("Ribeirão Preto, SP", "São Paulo")


@pytest.mark.req("R-4.3-2")
async def test_the_request_is_restricted_to_brazil() -> None:
    resolve, replay = recorded()

    await resolve("Sorriso", None, None)

    assert "countryCode=BR" in replay.calls[0]
    assert "name=Sorriso" in replay.calls[0]


@pytest.mark.req("R-4.3-3")
async def test_a_name_in_several_states_returns_candidates_not_a_guess() -> None:
    resolve, _ = recorded()

    result = await resolve("Bonito", None, None)

    assert isinstance(result, LocationCandidates)
    # The first five distinct labels, in the geocoder's order.
    assert [candidate.label for candidate in result.candidates] == [
        "Bonito, PE",
        "Bonito, MS",
        "Bonito, PA",
        "Bonito, BA",
        "Bonito de Minas, MG",
    ]
    assert all(candidate.country_code == "BR" for candidate in result.candidates)


@pytest.mark.req("R-4.3-3")
@pytest.mark.parametrize("query", ["Bonito, MS", "Bonito , mato grosso do sul", "Bonito,ms,Brasil"])
async def test_the_same_name_with_a_state_qualifier_resolves(query: str) -> None:
    resolve, _ = recorded()

    location = await resolve(query, None, None)

    assert isinstance(location, Location)
    assert location.label == "Bonito, MS"
    assert (location.lat, location.lon) == (-21.12111, -56.48194)
    assert location.admin_region == "Mato Grosso do Sul"


@pytest.mark.req("R-4.3-3")
async def test_a_state_with_several_places_of_one_name_keeps_the_first() -> None:
    resolve, _ = recorded()

    # The recording lists Varginha once in Minas Gerais and several times in other states.
    location = await resolve("Varginha, MG", None, None)

    assert isinstance(location, Location)
    assert (location.label, location.lat, location.lon) == ("Varginha, MG", -21.55139, -45.43028)


async def test_a_country_qualifier_does_not_filter() -> None:
    resolve, _ = recorded()

    location = await resolve("Sorriso, Brasil", None, None)

    assert isinstance(location, Location)
    assert location.label == "Sorriso, MT"


async def test_a_qualifier_that_matches_no_hit_is_not_found() -> None:
    resolve, _ = recorded()

    with pytest.raises(LocationNotFoundError):
        await resolve("Sorriso, SP", None, None)
    with pytest.raises(LocationNotFoundError):
        await resolve("Sorriso, Atlantis", None, None)


@pytest.mark.req("R-4.3-2")
async def test_a_name_that_exists_only_abroad_is_not_found() -> None:
    resolve, replay = recorded()

    with pytest.raises(LocationNotFoundError):
        await resolve("Reykjavik", None, None)

    assert len(replay.calls) == 1


@pytest.mark.req("R-4.3-2")
async def test_a_foreign_hit_is_dropped_even_if_the_geocoder_returns_it() -> None:
    lisbon = GeocodeHit(name="Lisboa", lat=38.72, lon=-9.13, admin1="Lisboa", country_code="PT")
    mislabelled = GeocodeHit(name="Lisboa", lat=38.72, lon=-9.13, admin1=None, country_code="BR")

    with pytest.raises(LocationNotFoundError):
        await ResolveLocation(Canned(lisbon, mislabelled))("Lisboa", None, None)


async def test_a_hit_without_a_state_is_labelled_by_its_name() -> None:
    hit = GeocodeHit(name="Vila Nova", lat=-10.0, lon=-50.0, admin1=None, country_code="BR")

    location = await ResolveLocation(Canned(hit))("Vila Nova", None, None)

    assert isinstance(location, Location)
    assert (location.label, location.admin_region) == ("Vila Nova", None)


@pytest.mark.req("R-4.3-1")
async def test_coordinates_inside_brazil_resolve_without_the_geocoder() -> None:
    location = await ResolveLocation(NeverCalled())(None, -12.5453, -55.7114)

    assert location == Location(
        label="-12.5453, -55.7114",
        lat=-12.5453,
        lon=-55.7114,
        h3_cell=h3.latlng_to_cell(-12.5453, -55.7114, 6),
        admin_region=None,
        country_code="BR",
    )


@pytest.mark.req("R-4.3-2")
@pytest.mark.parametrize(
    ("lat", "lon"),
    [(38.72, -9.13), (-34.6, -58.4), (10.5, -66.9), (-15.0, -30.0), (float("nan"), -50.0)],
)
async def test_coordinates_outside_brazil_are_outside_coverage(lat: float, lon: float) -> None:
    with pytest.raises(OutsideCoverageError):
        await ResolveLocation(NeverCalled())(None, lat, lon)


@pytest.mark.parametrize(
    ("query", "lat", "lon"),
    [
        (None, None, None),
        ("Sorriso", -12.5, -55.7),
        ("Sorriso", -12.5, None),
        (None, -12.5, None),
        (None, None, -55.7),
        ("   ", None, None),
        (", MT", None, None),
    ],
)
async def test_exactly_one_of_a_name_or_a_coordinate_pair_is_accepted(
    query: str | None, lat: float | None, lon: float | None
) -> None:
    with pytest.raises(InvalidArgumentsError):
        await ResolveLocation(NeverCalled())(query, lat, lon)


def test_the_27_federative_units_resolve_by_name_and_abbreviation() -> None:
    assert len(STATES) == 27
    for abbreviation, name in STATES.items():
        assert state_abbreviation(abbreviation.lower()) == abbreviation
        assert state_abbreviation(name) == abbreviation
    assert state_abbreviation("sao paulo") == "SP"
    assert state_abbreviation(" PARÁ ") == "PA"
    assert state_abbreviation("Para") == "PA"
    assert state_abbreviation("Paraná") == "PR"
    assert state_abbreviation("Atlantis") is None
