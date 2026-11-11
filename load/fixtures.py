"""The schedule of one load run, built from a seed (SPEC 16.5).

    cd backend && uv run python ../load/fixtures.py --run-id <id> --out <fixtures.json>

The output is every request k6 sends, in the order it sends them:

    {"run_id", "seed",
     "quotes": [{"index", "key_index", "key", "body"}],
     "cells":  [{"index", "path"}]}

Nothing here is random at run time: the same run id, seed and profile give the same file,
so the oracle can check the evidence of a run against the schedule it was given.

Quotes. `distinct_keys` idempotency keys named `<run_id>:q:<n>`, each sent
`sends_per_key` times with one and the same body. The first two sends of a key are
adjacent, so with several virtual users they are in flight together and race; the other
sends come later, mixed with other keys. A body is a `CreateQuote` (contracts section 5):
`location`, `cover` and `simulation`, and no `dataset_id`, because the service resolves the
grid cell and the dataset itself. Limits are integer centavos.

Cells. The per-cell metric route with the flat query parameters of SPEC 11.2. A small set
of distinct requests is repeated, so both the computing path and the cache path are used.

This file imports nothing from the service: the campaign reads the service only through
its HTTP interface.
"""

import argparse
import json
import random
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

PROFILE = Path(__file__).resolve().parent / "profile.json"

# The three showcase regions: north-west corner of a 20 by 20 grid of 0.1 degree cells.
# `load/tests/test_fixtures.py` checks these against the service's own definitions.
REGIONS: tuple[tuple[str, float, float], ...] = (
    ("sul-de-minas", -20.45, -46.55),
    ("sorriso", -11.55, -56.75),
    ("ribeirao-preto", -20.15, -48.85),
)
STEP_DEG = 0.1
# Rows and columns used for quote locations: well inside the grid, away from its edge.
INNER_CELLS = range(4, 16)

# Index definitions, both types. Millimetres for `rainfall_below`, days for `dry_spell_above`.
INDEXES: tuple[dict[str, Any], ...] = (
    {
        "index_type": "rainfall_below",
        "start": "09-01",
        "end": "10-31",
        "trigger": 100.0,
        "exit": 20.0,
    },
    {
        "index_type": "dry_spell_above",
        "start": "06-01",
        "end": "08-31",
        "trigger": 30.0,
        "exit": 60.0,
    },
    {
        "index_type": "rainfall_below",
        "start": "09-01",
        "end": "10-31",
        "trigger": 150.0,
        "exit": 75.0,
    },
    {
        "index_type": "dry_spell_above",
        "start": "05-01",
        "end": "09-30",
        "trigger": 40.0,
        "exit": 80.0,
    },
)
METRICS = ("trigger_frequency", "season_anomaly")
ANOMALY_SEASON = 2015  # `season_anomaly` needs a season; `trigger_frequency` takes none
SIMULATION = {"n": 100_000, "seed": 42}  # the defaults of the interface
BASE_LIMIT_CENTS = 10_000_000  # R$ 100,000.00
LIMIT_STEP_CENTS = 250_000  # R$ 2,500.00 more per key, so no two keys share a body


def build(run_id: str, seed: int, profile: dict[str, Any]) -> dict[str, Any]:
    quotes = profile["scenarios"]["quotes"]
    cells = profile["scenarios"]["cells"]
    return {
        "run_id": run_id,
        "seed": seed,
        "quotes": _quotes(run_id, seed, quotes["distinct_keys"], quotes["sends_per_key"]),
        "cells": _cells(cells["requests"]),
    }


def quote_body(key_index: int) -> dict[str, Any]:
    region_id, north, west = REGIONS[key_index % len(REGIONS)]
    index = INDEXES[key_index % len(INDEXES)]
    row = INNER_CELLS[(key_index // len(REGIONS)) % len(INNER_CELLS)]
    col = INNER_CELLS[(key_index // 7) % len(INNER_CELLS)]
    return {
        "location": {
            # The centre of the cell (row, col), counted from the north-west corner.
            "lat": round(north - (row + 0.5) * STEP_DEG, 6),
            "lon": round(west + (col + 0.5) * STEP_DEG, 6),
            "label": f"Load farm {key_index} ({region_id})",
        },
        "cover": {
            "index": {
                "index_type": index["index_type"],
                "window": {"start": index["start"], "end": index["end"]},
                "trigger": index["trigger"],
                "exit": index["exit"],
            },
            "limit": {
                "amount_cents": BASE_LIMIT_CENTS + key_index * LIMIT_STEP_CENTS,
                "currency": "BRL",
            },
        },
        "simulation": dict(SIMULATION),
    }


def _quotes(run_id: str, seed: int, distinct_keys: int, sends_per_key: int) -> list[dict[str, Any]]:
    if sends_per_key < 2:
        raise ValueError("a key must be sent at least twice: the first two sends race")
    rng = random.Random(seed)  # a reproducible order, not a secret
    order: list[int] = []
    later: list[int] = []  # sends still owed to keys whose first two are already scheduled
    for key_index in range(distinct_keys):
        order += [key_index, key_index]
        later += [key_index] * (sends_per_key - 2)
        for _ in range(min(2, len(later))):
            order.append(later.pop(rng.randrange(len(later))))
    rng.shuffle(later)
    order += later
    return [
        {
            "index": index,
            "key_index": key_index,
            "key": f"{run_id}:q:{key_index}",
            "body": quote_body(key_index),
        }
        for index, key_index in enumerate(order)
    ]


def _cells(requests: int) -> list[dict[str, Any]]:
    distinct = [
        _cells_path(region_id, metric, index)
        for index in INDEXES
        for metric in METRICS
        for region_id, _, _ in REGIONS
    ]
    return [{"index": index, "path": distinct[index % len(distinct)]} for index in range(requests)]


def _cells_path(region_id: str, metric: str, index: dict[str, Any]) -> str:
    query: dict[str, Any] = {"metric": metric}
    if metric == "season_anomaly":
        query["season"] = ANOMALY_SEASON
    query |= {
        "index_type": index["index_type"],
        "window_start": index["start"],
        "window_end": index["end"],
        "trigger": index["trigger"],
        "exit": index["exit"],
    }
    return f"/api/v1/regions/{region_id}/cells?{urlencode(query)}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--profile", type=Path, default=PROFILE)
    parser.add_argument("--seed", type=int, default=None, help="default: the seed of the profile")
    arguments = parser.parse_args()

    profile = json.loads(arguments.profile.read_text(encoding="utf-8"))
    seed = profile["seed"] if arguments.seed is None else arguments.seed
    fixtures = build(arguments.run_id, seed, profile)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(fixtures, indent=1) + "\n", encoding="utf-8")
    print(f"{len(fixtures['quotes'])} quote sends and {len(fixtures['cells'])} cell requests")


if __name__ == "__main__":
    main()
