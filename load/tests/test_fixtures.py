"""The load schedule and the declared profile (`load/fixtures.py`, `load/profile.json`).

cd backend && uv run pytest ../load/tests/test_fixtures.py -q
"""

import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from veranico.modules.climate.domain.regions import REGIONS, region_containing

LOAD = Path(__file__).resolve().parents[1]
RUN_ID = "run-under-test"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"load_{name}", LOAD / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = _load("fixtures")
PROFILE: dict[str, Any] = json.loads((LOAD / "profile.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schedule() -> dict[str, Any]:
    built: dict[str, Any] = fixtures.build(RUN_ID, PROFILE["seed"], PROFILE)
    return built


def _floats(value: object) -> list[float]:
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [found for item in value.values() for found in _floats(item)]
    if isinstance(value, list):
        return [found for item in value for found in _floats(item)]
    return []


def test_the_profile_declares_the_campaign_and_the_two_latency_thresholds_of_the_spec() -> None:
    quotes, cells = PROFILE["scenarios"]["quotes"], PROFILE["scenarios"]["cells"]

    assert (quotes["distinct_keys"], quotes["sends_per_key"], quotes["virtual_users"]) == (
        200,
        5,
        20,
    )
    assert (cells["requests"], cells["virtual_users"]) == (600, 10)
    # SPEC 16.5: 95th percentile under 2 seconds for POST /quotes, under 1 second for cells.
    assert PROFILE["thresholds"] == {
        "http_req_duration{scenario:quotes}": ["p(95)<2000"],
        "http_req_duration{scenario:cells}": ["p(95)<1000"],
        "unexpected_status": ["count==0"],
        "checks": ["rate==1"],
    }


def test_the_same_seed_gives_the_same_schedule_and_another_seed_another_order(
    schedule: dict[str, Any],
) -> None:
    again = fixtures.build(RUN_ID, PROFILE["seed"], PROFILE)
    other = fixtures.build(RUN_ID, PROFILE["seed"] + 1, PROFILE)

    assert json.dumps(again) == json.dumps(schedule)
    assert [entry["key_index"] for entry in other["quotes"]] != [
        entry["key_index"] for entry in schedule["quotes"]
    ]


def test_every_key_is_sent_exactly_five_times_with_one_body(schedule: dict[str, Any]) -> None:
    quotes = schedule["quotes"]

    assert [entry["index"] for entry in quotes] == list(range(1000))
    sends = Counter(entry["key"] for entry in quotes)
    assert len(sends) == 200
    assert set(sends.values()) == {5}
    assert set(sends) == {f"{RUN_ID}:q:{n}" for n in range(200)}
    bodies: dict[str, set[str]] = {}
    for entry in quotes:
        assert entry["key"] == f"{RUN_ID}:q:{entry['key_index']}"
        bodies.setdefault(entry["key"], set()).add(json.dumps(entry["body"], sort_keys=True))
    assert all(len(found) == 1 for found in bodies.values())
    # Two keys never share a body: a shared body would hide a wrong key-to-quote mapping.
    assert len({next(iter(found)) for found in bodies.values()}) == 200


def test_the_first_two_sends_of_a_key_are_adjacent_and_the_rest_are_spread(
    schedule: dict[str, Any],
) -> None:
    positions: dict[int, list[int]] = {}
    for entry in schedule["quotes"]:
        positions.setdefault(entry["key_index"], []).append(entry["index"])

    assert all(found[1] == found[0] + 1 for found in positions.values())
    # At least one later send of nearly every key is separated from the pair by other keys.
    spread = sum(1 for found in positions.values() if found[-1] - found[1] > 1)
    assert spread >= 190


def test_every_body_is_a_create_quote_without_a_dataset(schedule: dict[str, Any]) -> None:
    for entry in schedule["quotes"]:
        body = entry["body"]
        assert set(body) == {"location", "cover", "simulation"}
        assert "dataset_id" not in json.dumps(body)
        assert set(body["location"]) == {"lat", "lon", "label"}
        assert set(body["cover"]) == {"index", "limit"}
        assert set(body["cover"]["index"]) == {"index_type", "window", "trigger", "exit"}
        assert body["simulation"] == {"n": 100_000, "seed": 42}


def test_money_is_integer_centavos_and_never_a_float(schedule: dict[str, Any]) -> None:
    for entry in schedule["quotes"]:
        limit = entry["body"]["cover"]["limit"]
        assert limit["currency"] == "BRL"
        assert type(limit["amount_cents"]) is int
        assert limit["amount_cents"] > 0
        assert _floats(limit) == []


def test_bodies_rotate_the_three_regions_and_both_index_types(schedule: dict[str, Any]) -> None:
    regions: Counter[str] = Counter()
    index_types: Counter[str] = Counter()
    for entry in schedule["quotes"]:
        location = entry["body"]["location"]
        region = region_containing(location["lat"], location["lon"])
        assert region is not None, f"outside every showcase region: {location}"
        regions[region.region_id] += 1
        index_types[entry["body"]["cover"]["index"]["index_type"]] += 1

    assert set(regions) == {region.region_id for region in REGIONS}
    assert set(index_types) == {"rainfall_below", "dry_spell_above"}
    assert min(regions.values()) >= 300  # of 1,000 sends
    assert min(index_types.values()) >= 400


def test_the_region_corners_are_the_ones_the_service_defines() -> None:
    assert (
        tuple((region.region_id, region.north, region.west) for region in REGIONS)
        == fixtures.REGIONS
    )
    assert {(region.step_deg, region.nx, region.ny) for region in REGIONS} == {
        (fixtures.STEP_DEG, 20, 20)
    }


def test_cells_requests_use_the_flat_query_of_the_spec_with_repeats(
    schedule: dict[str, Any],
) -> None:
    cells = schedule["cells"]

    assert [entry["index"] for entry in cells] == list(range(600))
    repeats = Counter(entry["path"] for entry in cells)
    assert len(repeats) == 24  # 3 regions, 2 metrics, 4 index definitions
    assert set(repeats.values()) == {25}  # the cache path is used 24 times per request
    seen_regions, seen_metrics, seen_types = set(), set(), set()
    for path in repeats:
        url = urlsplit(path)
        prefix, region_id, suffix = url.path.rsplit("/", 2)
        assert (prefix, suffix) == ("/api/v1/regions", "cells")
        query = {name: values[0] for name, values in parse_qs(url.query).items()}
        expected = {"metric", "index_type", "window_start", "window_end", "trigger", "exit"}
        if query["metric"] == "season_anomaly":
            expected.add("season")
        assert set(query) == expected
        seen_regions.add(region_id)
        seen_metrics.add(query["metric"])
        seen_types.add(query["index_type"])
    assert seen_regions == {region.region_id for region in REGIONS}
    assert seen_metrics == {"trigger_frequency", "season_anomaly"}
    assert seen_types == {"rainfall_below", "dry_spell_above"}


def test_the_command_line_writes_the_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "run" / "fixtures.json"
    monkeypatch.setattr("sys.argv", ["fixtures.py", "--run-id", RUN_ID, "--out", str(out)])

    fixtures.main()

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == fixtures.build(RUN_ID, PROFILE["seed"], PROFILE)
    assert set(written) == {"run_id", "seed", "quotes", "cells"}
