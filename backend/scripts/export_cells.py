"""Write the cell grids of the recorded happy path as a frontend test fixture.

    uv run python scripts/export_cells.py

The Playwright flow and the unit tests play the recorded conversation
(`modules/assistant/replays/*.jsonl`). The recording carries no per-cell grid, so the map's
bodies are computed here by the `pricing` use case the API serves, from the same cube the
recording was made on: the region as `GET /regions` answers it, the trigger frequency of the
recorded cover and the anomaly of every usable season (`GET /regions/{id}/cells`). The script
refuses to write when the installed cube is not the one named in the recording's header.

It reads the local weather store (`backend/.data/weather`, built by `make build-cube` after human
gate H1) and needs no network, account or key. The output is
`frontend/src/test/fixtures/recorded-cells.json`.
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx

from veranico.modules.climate.module import assemble, weather_store
from veranico.modules.pricing.application.service import PricingService
from veranico.modules.pricing.contracts import CellMetricRequest, IndexDefinition
from veranico.shared.infrastructure.settings import ClimateSettings, PricingSettings
from veranico.shared.kernel.clock import SystemClock

BACKEND = Path(__file__).resolve().parents[1]
REPLAY = BACKEND / "src/veranico/modules/assistant/replays/en.jsonl"
STORE = BACKEND / ".data/weather"
OUTPUT = BACKEND.parent / "frontend/src/test/fixtures/recorded-cells.json"


def recorded() -> tuple[dict[str, object], dict[str, object], str]:
    """The recording's header, the cover of its backtest and the region of its history."""
    lines = [json.loads(line) for line in REPLAY.read_text(encoding="utf-8").splitlines() if line]
    header = lines[0]
    results = {
        event["data"]["tool"]: event["data"]["result"]
        for event in lines[1:]
        if event.get("event") == "tool_finished"
    }
    return header, results["backtest_index"]["cover"], results["get_weather_history"]["region_id"]


async def export() -> int:
    header, cover, region_id = recorded()
    manifest = json.loads((STORE / "climate/cubes" / region_id / "manifest.json").read_text())
    if manifest.get("checksum") != header.get("cube_checksum"):
        print(
            f"the installed cube of {region_id} is not the one the recording used", file=sys.stderr
        )
        return 1
    settings = ClimateSettings(store_root=STORE)
    clock = SystemClock()
    async with httpx.AsyncClient() as http:  # never called: the cubes are local
        climate = assemble(settings, clock, http, weather_store(settings, clock))
        pricing = PricingService(climate=climate, settings=PricingSettings())
        region = next(r for r in await climate.regions() if r.region_id == region_id)
        index = IndexDefinition.model_validate(cover["index"])
        frequency = await pricing.cell_metrics(
            CellMetricRequest(region_id=region_id, metric="trigger_frequency", index=index)
        )
        anomalies = {}
        for season in frequency.seasons:
            grid = await pricing.cell_metrics(
                CellMetricRequest(
                    region_id=region_id, metric="season_anomaly", index=index, season=season
                )
            )
            anomalies[str(season)] = {
                "values": grid.values,
                "breaks": grid.breaks,
                "cells_paying": grid.cells_paying,
            }
    body = {
        "source": {"cube_checksum": header["cube_checksum"], "replay": "en.jsonl"},
        "region": region.model_dump(mode="json"),
        "index": index.model_dump(mode="json"),
        "trigger_frequency": frequency.model_dump(mode="json"),
        "season_anomaly": anomalies,
    }
    OUTPUT.write_text(json.dumps(body, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(BACKEND.parent)}: {len(anomalies)} seasons")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(export()))
