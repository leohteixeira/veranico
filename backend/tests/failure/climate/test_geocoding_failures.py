"""The geocoder failing: it follows the same retry policy as the archive (SPEC 4.2, 4.3)."""

import random

import httpx
import pytest

from tests.unit.climate.replay import load
from veranico.modules.climate.infrastructure.open_meteo import SourceRejectedError
from veranico.modules.climate.infrastructure.open_meteo_geocoding import OpenMeteoGeocoder
from veranico.shared.infrastructure.settings import ClimateSettings
from veranico.shared.kernel.errors import WeatherSourceUnavailableError

pytestmark = [pytest.mark.failure, pytest.mark.req("R-4.2-3")]

[SORRISO] = load("geocoding/sorriso.json").values()


def geocoder(*statuses: int) -> tuple[OpenMeteoGeocoder, list[httpx.Request], list[float]]:
    """Answers request n with status n (the last repeats); 200 serves the recording."""
    requests: list[httpx.Request] = []
    delays: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        code = statuses[min(len(requests), len(statuses)) - 1]
        return httpx.Response(code, json=SORRISO["body"] if code == 200 else {"error": True})

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return (
        OpenMeteoGeocoder(client, ClimateSettings(), rng=random.Random(3), sleep=sleep),
        requests,
        delays,
    )


async def test_a_429_then_success_makes_two_calls() -> None:
    source, requests, delays = geocoder(429, 200)

    hits = await source.search("Sorriso")

    assert [hit.name for hit in hits] == ["Sorriso"]
    assert len(requests) == 2
    assert len(delays) == 1


async def test_a_503_on_every_attempt_makes_four_calls_and_is_unavailable() -> None:
    source, requests, delays = geocoder(503)

    with pytest.raises(WeatherSourceUnavailableError):
        await source.search("Sorriso")

    assert len(requests) == 4
    assert delays == sorted(delays)
    assert len(delays) == 3


async def test_a_400_is_not_retried() -> None:
    source, requests, delays = geocoder(400)

    with pytest.raises(SourceRejectedError):
        await source.search("Sorriso")

    assert len(requests) == 1
    assert delays == []
