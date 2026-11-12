"""Use case behind `ClimateFacade.export_evidence` (SPEC 4.4).

The evidence of a quote is the exact daily slice it used: every day of its window in the
seasons it was priced on, and nothing else, with where the values came from as global
attributes. The caller adds its own attributes (the index definition); it may not overwrite
a provenance attribute.
"""

import asyncio
import json

from veranico.modules.climate.application.ports import EncodeEvidence, WeatherStore
from veranico.modules.climate.contracts import EvidenceRequest
from veranico.modules.climate.domain.window_days import window_mask
from veranico.shared.kernel.errors import InvalidArgumentsError


class ExportEvidence:
    def __init__(self, store: WeatherStore, encode: EncodeEvidence) -> None:
        self._store = store
        self._encode = encode

    async def __call__(self, request: EvidenceRequest) -> bytes:
        # Checked before any read, so a wrong request never costs one.
        if request.first_season > request.last_season:
            raise InvalidArgumentsError("first_season is later than last_season")
        series = await self._store.read_series(request.dataset_id)
        provenance = await self._store.provenance(request.dataset_id)
        mask = window_mask(
            series.dates,
            request.window_start,
            request.window_end,
            request.first_season,
            request.last_season,
        )
        if not mask.any():
            raise InvalidArgumentsError("the dataset holds no day of these seasons")

        dataset = series.dataset
        attributes = {
            "dataset_id": dataset.dataset_id,
            "grid_point_lat": str(dataset.grid_point.lat),
            "grid_point_lon": str(dataset.grid_point.lon),
            "source": dataset.source,
            "request": json.dumps(dict(provenance.request), sort_keys=True),
            "manifest_checksum": provenance.checksum,
            "window_start": request.window_start,
            "window_end": request.window_end,
            "first_season": str(request.first_season),
            "last_season": str(request.last_season),
        }
        collisions = sorted(set(attributes) & set(request.attributes))
        if collisions:
            raise InvalidArgumentsError(
                f"attributes may not overwrite provenance: {', '.join(collisions)}"
            )
        attributes.update(request.attributes)
        # Encoding blocks, so it runs in a thread.
        return await asyncio.to_thread(
            self._encode, series.dates[mask], series.precipitation_mm[mask], attributes
        )
