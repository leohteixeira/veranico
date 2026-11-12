"""GET with the retry policy of SPEC 4.2, shared by the Open-Meteo adapters.

At most `attempts` attempts, each with its own timeout. An attempt is retried after a 429,
a 5xx, a timeout or a connection error. Any other answer is returned to the caller at once:
a 4xx other than 429 says the request is wrong, and repeating it cannot help.

The wait before attempt n+1 is exponential with equal jitter: half of `base * 2**(n-1)`
plus a random share of the other half. The jitter spreads clients that failed together;
the fixed half keeps the delays growing. The random generator and the sleep function are
injected, so tests are deterministic and never wait.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

from veranico.shared.kernel.errors import WeatherSourceUnavailableError

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Answer:
    response: httpx.Response
    attempts: int


class RetryingGet:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        attempts: int,
        backoff_base_seconds: float,
        timeout_seconds: float,
        rng: random.Random,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._http = http
        self._attempts = attempts
        self._base = backoff_base_seconds
        self._timeout = timeout_seconds
        self._rng = rng
        self._sleep = sleep

    async def get(self, url: str, params: Mapping[str, str]) -> Answer:
        """Return the first answer that is not retryable, with the attempts it took.

        Raises `WeatherSourceUnavailableError` (retryable for the caller) when every attempt
        failed. Its cause is the transport error when the last attempt got no response at
        all, which is how a caller tells "the network is down" from "the source is failing".
        """
        failure: httpx.TransportError | None = None
        for attempt in range(1, self._attempts + 1):
            if attempt > 1:
                await self._sleep(self._delay(attempt - 1))
            try:
                response = await self._http.get(url, params=params, timeout=self._timeout)
            except httpx.TransportError as error:  # timeouts and connection errors
                failure = error
                continue
            failure = None
            if response.status_code == 429 or response.status_code >= 500:
                continue
            return Answer(response=response, attempts=attempt)
        raise WeatherSourceUnavailableError(
            f"the weather source did not answer in {self._attempts} attempts"
        ) from failure

    def _delay(self, failed_attempts: int) -> float:
        ceiling = self._base * 2.0 ** (failed_attempts - 1)
        return ceiling / 2 + self._rng.uniform(0, ceiling / 2)
