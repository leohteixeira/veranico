"""Replay of recorded HTTP answers through `httpx.MockTransport`.

A recording is a JSON file `{"request": {"method", "url"}, "status", "body"}`: the answer
is stored with the exact request URL that produced it. `replaying` answers a request only
when its URL is one of the recordings and fails the test otherwise, so a test can never
reach the network by accident. `calls` lists the URLs that were asked, in order.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@dataclass
class Replay:
    recordings: dict[str, dict[str, Any]]
    calls: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        recording = self.recordings.get(url)
        if recording is None or recording["request"]["method"] != request.method:
            raise AssertionError(f"no recording for {request.method} {url}")
        return httpx.Response(recording["status"], json=recording["body"])

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))


def load(*names: str) -> dict[str, dict[str, Any]]:
    """Recordings by request URL, from files named relative to `fixtures/`."""
    recordings = {}
    for name in names:
        recording = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        recordings[recording["request"]["url"]] = recording
    return recordings


def replaying(*names: str) -> Replay:
    return Replay(load(*names))
