"""Open-Meteo failing: 429, 5xx, timeouts and a rejected request (SPEC 4.2, 16.3)."""

import random
from collections.abc import Callable

import httpx
import numpy as np
import pytest

from tests.unit.climate.replay import load
from veranico.modules.climate.infrastructure.open_meteo import OpenMeteoArchive, SourceRejectedError
from veranico.shared.infrastructure.settings import ClimateSettings
from veranico.shared.kernel.errors import WeatherSourceUnavailableError

pytestmark = [pytest.mark.failure, pytest.mark.req("R-4.2-3", "R-16.3-1")]

[RECORDING] = load("open_meteo/brasilia_2020_2021.json").values()
REQUESTED = (-15.03, -47.93)
SETTINGS = ClimateSettings()  # 4 attempts, backoff base 0.5 s, 10 s per attempt

Step = Callable[[httpx.Request], httpx.Response]


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=RECORDING["body"])


def status(code: int) -> Step:
    return lambda request: httpx.Response(code, json={"error": True, "reason": "scripted"})


def timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("scripted timeout", request=request)


def refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("scripted connection error", request=request)


class Scripted:
    """Answers request n with step n (the last step repeats); never touches the network."""

    def __init__(self, *steps: Step, seed: int = 7) -> None:
        self._steps = steps
        self.requests: list[httpx.Request] = []
        self.delays: list[float] = []
        self.source = OpenMeteoArchive(
            httpx.AsyncClient(transport=httpx.MockTransport(self._handle)),
            SETTINGS,
            rng=random.Random(seed),
            sleep=self._sleep,
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self._steps[min(len(self.requests), len(self._steps)) - 1]
        return step(request)

    async def _sleep(self, seconds: float) -> None:
        self.delays.append(seconds)  # recorded, never waited

    async def fetch(self) -> np.ndarray:
        fetched = await self.source.fetch(*REQUESTED, 2020, 2021)
        self.attempts = fetched.attempts
        return fetched.dates


async def test_a_429_then_success_makes_two_calls() -> None:
    scripted = Scripted(status(429), ok)

    dates = await scripted.fetch()

    assert len(dates) == 731
    assert len(scripted.requests) == 2
    assert scripted.attempts == 2
    assert len(scripted.delays) == 1


async def test_a_503_then_success_makes_two_calls() -> None:
    scripted = Scripted(status(503), ok)

    await scripted.fetch()

    assert len(scripted.requests) == 2


async def test_a_503_on_every_attempt_makes_exactly_four_calls_and_is_unavailable() -> None:
    scripted = Scripted(status(503))

    with pytest.raises(WeatherSourceUnavailableError) as raised:
        await scripted.fetch()

    assert len(scripted.requests) == 4
    assert len(scripted.delays) == 3
    assert raised.value.retryable
    assert raised.value.code == "weather_source_unavailable"
    assert raised.value.__cause__ is None  # the source answered: this is not a dead network


async def test_a_timeout_on_every_attempt_makes_exactly_four_calls_and_is_unavailable() -> None:
    scripted = Scripted(timeout)

    with pytest.raises(WeatherSourceUnavailableError) as raised:
        await scripted.fetch()

    assert len(scripted.requests) == 4
    assert isinstance(raised.value.__cause__, httpx.TimeoutException)


async def test_a_connection_error_is_retried_and_reported_as_no_response() -> None:
    scripted = Scripted(refused)

    with pytest.raises(WeatherSourceUnavailableError) as raised:
        await scripted.fetch()

    assert len(scripted.requests) == 4
    assert isinstance(raised.value.__cause__, httpx.TransportError)


async def test_a_timeout_then_success_recovers() -> None:
    scripted = Scripted(timeout, timeout, ok)

    await scripted.fetch()

    assert len(scripted.requests) == 3
    assert scripted.attempts == 3


async def test_every_attempt_carries_the_configured_timeout() -> None:
    scripted = Scripted(status(500), ok)

    await scripted.fetch()

    for request in scripted.requests:
        assert request.extensions["timeout"] == {
            "connect": 10.0,
            "read": 10.0,
            "write": 10.0,
            "pool": 10.0,
        }


async def test_a_400_makes_one_call_and_is_not_retried() -> None:
    scripted = Scripted(status(400))

    with pytest.raises(SourceRejectedError):
        await scripted.fetch()

    assert len(scripted.requests) == 1
    assert scripted.delays == []


async def test_a_404_is_not_retried_either() -> None:
    scripted = Scripted(status(404))

    with pytest.raises(SourceRejectedError):
        await scripted.fetch()

    assert len(scripted.requests) == 1


async def test_the_delays_grow_and_stay_inside_the_exponential_bounds() -> None:
    scripted = Scripted(status(503))

    with pytest.raises(WeatherSourceUnavailableError):
        await scripted.fetch()

    first, second, third = scripted.delays
    # Base 0.5 s: half of 0.5, 1 and 2 seconds is fixed, the other half is jitter.
    assert 0.25 <= first <= 0.5
    assert 0.5 <= second <= 1.0
    assert 1.0 <= third <= 2.0
    assert first < second < third


async def test_the_delays_are_identical_for_the_same_seed_and_differ_for_another() -> None:
    async def delays(seed: int) -> list[float]:
        scripted = Scripted(status(503), seed=seed)
        with pytest.raises(WeatherSourceUnavailableError):
            await scripted.fetch()
        return scripted.delays

    assert await delays(7) == await delays(7)
    assert await delays(7) != await delays(8)
