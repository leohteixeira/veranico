"""The carrier directory: a fixed list of mock carriers (SPEC section 7).

`CarrierDirectory` satisfies the `CarrierCatalog` port that `quoting` declares. The webhook
path of an entry stays internal: `CarrierInfo` exposes the id and the name only.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from veranico.modules.quoting.contracts import CarrierInfo

_SUBMISSIONS_PATH = "/carrier/v1/submissions"


@dataclass(frozen=True, slots=True)
class CarrierEntry:
    carrier_id: str
    name: str
    webhook_path: str


# Fictional carriers. Both are served by the one mock carrier service (`APP_ROLE=carrier`).
CARRIERS: tuple[CarrierEntry, ...] = (
    CarrierEntry("carrier-1", "Seguradora Jatobá (mock)", _SUBMISSIONS_PATH),
    CarrierEntry("carrier-2", "Ipê Amarelo Re (mock)", _SUBMISSIONS_PATH),
)


class CarrierDirectory:
    def __init__(self, base_url: str, entries: Sequence[CarrierEntry] = CARRIERS) -> None:
        self._base_url = base_url.rstrip("/")
        self._entries = {entry.carrier_id: entry for entry in entries}

    def get(self, carrier_id: str) -> CarrierInfo | None:
        entry = self._entries.get(carrier_id)
        return None if entry is None else _info(entry)

    def all(self) -> list[CarrierInfo]:
        return [_info(entry) for entry in self._entries.values()]

    def webhook_url(self, carrier_id: str) -> str | None:
        """Where the webhook of this carrier is sent; `None` for an unknown carrier."""
        entry = self._entries.get(carrier_id)
        return None if entry is None else self._base_url + entry.webhook_path


def _info(entry: CarrierEntry) -> CarrierInfo:
    return CarrierInfo(carrier_id=entry.carrier_id, name=entry.name)
