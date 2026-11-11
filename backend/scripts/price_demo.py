"""Backtest and price a fixture series (plan 02).

    uv run python scripts/price_demo.py

Builds the `pricing` module over the in-memory climate fake with a seeded synthetic series,
backtests and prices one cover of each index type and prints the results as JSON. The whole
demonstration runs twice. Exit code: 0 when both runs are identical, at least 20 seasons
were used and no premium is below its expected loss; 1 otherwise.

The series is synthetic (seeded random rain), so the figures show the engine working and
say nothing about real weather.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `tests.fakes` lives in backend/

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.settings import settings_for_tests
from veranico.modules.pricing.contracts import SimulationOptions
from veranico.modules.pricing.module import PricingDeps, build

SERIES_SEED = 0
MIN_SEASONS = 20
COVERS = (
    builders.cover(
        index_type="rainfall_below",
        start="10-01",
        end="03-31",
        trigger=600.0,
        exit=300.0,
        limit_cents=30_000_000,
    ),
    builders.cover(
        index_type="dry_spell_above",
        start="10-01",
        end="03-31",
        trigger=9.0,
        exit=18.0,
        limit_cents=30_000_000,
    ),
)


async def run_once() -> list[dict[str, object]]:
    """One full demonstration on a freshly built module."""
    climate = FakeClimateFacade()
    dataset = climate.add_series(builders.daily_series(seed=SERIES_SEED))
    pricing = build(PricingDeps(settings=settings_for_tests(), climate=climate)).facade
    results: list[dict[str, object]] = []
    for cover in COVERS:
        backtest = await pricing.backtest(dataset.dataset_id, cover)
        priced = await pricing.price(dataset.dataset_id, cover, SimulationOptions())
        results.append(
            {
                "dataset": dataset.model_dump(mode="json"),
                # the backtest alone and the one inside the priced cover must agree
                "backtest_matches_priced": backtest == priced.backtest,
                "priced": priced.model_dump(mode="json"),
            }
        )
    return results


def problems(results: list[dict[str, object]], repeat: list[dict[str, object]]) -> list[str]:
    found: list[str] = []
    if json.dumps(results, sort_keys=True) != json.dumps(repeat, sort_keys=True):
        found.append("the two runs differ")
    for result in results:
        priced = result["priced"]
        assert isinstance(priced, dict)
        index_type = priced["backtest"]["cover"]["index"]["index_type"]
        if not result["backtest_matches_priced"]:
            found.append(f"{index_type}: backtest and price disagree on the backtest")
        if priced["backtest"]["seasons_used"] < MIN_SEASONS:
            found.append(f"{index_type}: fewer than {MIN_SEASONS} seasons used")
        premium = priced["premium"]["premium"]["amount_cents"]
        expected_loss = priced["simulation"]["expected_loss"]["amount_cents"]
        if premium < expected_loss:
            found.append(f"{index_type}: the premium is below the expected loss")
    return found


def main() -> int:
    results = asyncio.run(run_once())
    repeat = asyncio.run(run_once())
    print(json.dumps(results, indent=2, sort_keys=True))
    found = problems(results, repeat)
    for problem in found:
        print(f"price_demo: {problem}", file=sys.stderr)
    if found:
        return 1
    print("price_demo: two identical runs, both covers priced", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
