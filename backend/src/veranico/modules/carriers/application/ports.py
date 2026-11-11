"""Ports the delivery use case declares; the adapters live in `infrastructure/`."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

TransportFailure = Literal["timeout", "connection_error"]


@dataclass(frozen=True, slots=True)
class SendResult:
    """What one HTTP request produced: a response, or the reason there is none."""

    status_code: int | None  # None when no response arrived
    body: bytes
    failure: TransportFailure | None  # None when a response arrived

    @classmethod
    def response(cls, status_code: int, body: bytes) -> "SendResult":
        return cls(status_code=status_code, body=body, failure=None)

    @classmethod
    def failed(cls, failure: TransportFailure) -> "SendResult":
        return cls(status_code=None, body=b"", failure=failure)


class WebhookSender(Protocol):
    async def send(self, url: str, headers: Mapping[str, str], body: bytes) -> SendResult:
        """Make exactly one POST of `body`, unchanged, within a bounded time.

        Never retries and never follows a redirect: the queue is the only layer that
        retries. Transport faults are returned as a `SendResult`, not raised.
        """
        ...
