"""A small client for the control API of the fault proxy (Toxiproxy) and the stack the
proxy tests run on.

Addresses come only from the environment `make test-failure` exports, in the proxy's own
terms; no host or port is written here:

* `VERANICO_FAULT_PROXY_API`: the control API as this process reaches it;
* `VERANICO_FAULT_PROXY_LISTEN`: the `listen` value of the proxy the tests create;
* `VERANICO_FAULT_PROXY_UPSTREAM`: its `upstream`, a running carrier role.

The webhook is sent to the listener, reached on the control API's host at the listener's
port. The carrier role behind the proxy is a real process: it signs with
`VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET` (the same variable the recipe gives it), runs
on real time and writes its receipts to the Firestore emulator this process also reads.

Without the three proxy variables the tests are skipped. With them set, a control API that
does not answer, or a missing secret, fails the fixture.

Control API as documented in the Toxiproxy README at tag v2.13.0 (read 2026-11-11):
`POST /proxies` (`name`, `listen`, `upstream`, `enabled`), `POST /proxies/{name}` to update
(`enabled: false` takes the proxy down), `DELETE /proxies/{name}`,
`POST /proxies/{name}/toxics` (`name`, `type`, `stream`, `toxicity`, `attributes`) and
`DELETE /proxies/{name}/toxics/{toxic}`. Stream `downstream` is carrier to sender (the
response path), `upstream` is sender to carrier. Toxics used: `latency` (`latency`, ms),
`reset_peer` (`timeout`, ms), `limit_data` (`bytes`).
"""

import os
import secrets
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

API_VARIABLE = "VERANICO_FAULT_PROXY_API"
LISTEN_VARIABLE = "VERANICO_FAULT_PROXY_LISTEN"
UPSTREAM_VARIABLE = "VERANICO_FAULT_PROXY_UPSTREAM"
SECRET_VARIABLE = "VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET"

Stream = Literal["upstream", "downstream"]


@dataclass(frozen=True)
class ProxyAddresses:
    api: str
    listen: str
    upstream: str

    @classmethod
    def from_environment(cls) -> "ProxyAddresses | None":
        """The three addresses, or `None` when the campaign's environment is not set."""
        values = [
            os.environ.get(name) for name in (API_VARIABLE, LISTEN_VARIABLE, UPSTREAM_VARIABLE)
        ]
        if not all(values):
            return None
        api, listen, upstream = (str(value) for value in values)
        return cls(api=api.rstrip("/"), listen=listen, upstream=upstream)

    @property
    def listener_url(self) -> str:
        """Where the webhook is sent: the control API's host, the listener's port."""
        host = urlsplit(self.api).hostname
        port = self.listen.rsplit(":", 1)[-1]
        return f"http://{host}:{port}"


class FaultProxy:
    """One proxy of this test, under a name no other run uses."""

    def __init__(self, addresses: ProxyAddresses) -> None:
        self.addresses = addresses
        self.name = f"carriers-{secrets.token_hex(6)}"
        self._api = httpx.AsyncClient(base_url=addresses.api, timeout=5.0)

    async def create(self) -> None:
        await self._post(
            "/proxies",
            {
                "name": self.name,
                "listen": self.addresses.listen,
                "upstream": self.addresses.upstream,
                "enabled": True,
            },
        )

    async def delete(self) -> None:
        """Remove this proxy (and its toxics) and nothing else."""
        try:
            response = await self._api.delete(f"/proxies/{self.name}")
            if response.status_code != 404:
                response.raise_for_status()
        finally:
            await self._api.aclose()

    async def set_enabled(self, enabled: bool) -> None:
        await self._post(f"/proxies/{self.name}", {"enabled": enabled})

    async def add_toxic(self, kind: str, stream: Stream, **attributes: int) -> str:
        """Add a toxic to every connection of the proxy; returns its name for removal."""
        name = f"{kind}_{stream}"
        await self._post(
            f"/proxies/{self.name}/toxics",
            {
                "name": name,
                "type": kind,
                "stream": stream,
                "toxicity": 1.0,
                "attributes": attributes,
            },
        )
        return name

    async def remove_toxic(self, name: str) -> None:
        response = await self._api.delete(f"/proxies/{self.name}/toxics/{name}")
        response.raise_for_status()

    async def _post(self, path: str, body: dict[str, Any]) -> None:
        response = await self._api.post(path, json=body)
        response.raise_for_status()
