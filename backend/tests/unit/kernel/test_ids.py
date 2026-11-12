import re
import time
import uuid

import pytest

from veranico.shared.kernel.errors import InvalidArgumentsError
from veranico.shared.kernel.ids import (
    QUOTE_ID_PATTERN,
    RECEIPT_ID_PATTERN,
    SUBMISSION_ID_PATTERN,
    CubeDataset,
    PointDataset,
    cube_dataset_id,
    new_event_id,
    new_quote_id,
    new_receipt_id,
    new_submission_id,
    parse_dataset_id,
    point_dataset_id,
)

# Crockford base32 leaves out I, L, O and U.
CROCKFORD_SUFFIX = "[0-9ABCDEFGHJKMNPQRSTVWXYZ]{6}"


@pytest.mark.parametrize(
    ("generate", "prefix", "exported"),
    [
        (new_quote_id, "Q", QUOTE_ID_PATTERN),
        (new_submission_id, "S", SUBMISSION_ID_PATTERN),
        (new_receipt_id, "R", RECEIPT_ID_PATTERN),
    ],
)
def test_generated_identifier_is_prefix_plus_six_crockford_characters(
    generate: object, prefix: str, exported: re.Pattern[str]
) -> None:
    assert callable(generate)
    for _ in range(200):
        value = generate()
        assert re.fullmatch(f"{prefix}-{CROCKFORD_SUFFIX}", value)
        assert exported.fullmatch(value)


@pytest.mark.parametrize("value", ["Q-ABCDEI", "Q-ABCDEL", "Q-ABCDEO", "Q-ABCDEU", "Q-abcdef"])
def test_quote_pattern_rejects_characters_outside_crockford(value: str) -> None:
    assert QUOTE_ID_PATTERN.match(value) is None


@pytest.mark.parametrize("value", ["Q-ABCDE", "Q-ABCDEFG", "S-ABCDEF", "QABCDEF", "Q-ABCDEF\n"])
def test_quote_pattern_rejects_wrong_shape(value: str) -> None:
    assert QUOTE_ID_PATTERN.match(value) is None


def test_generated_identifiers_differ() -> None:
    assert len({new_quote_id() for _ in range(50)}) > 1


def test_event_id_is_a_uuid_version_7_with_the_current_time() -> None:
    before = time.time_ns() // 1_000_000
    value = new_event_id()
    after = time.time_ns() // 1_000_000

    parsed = uuid.UUID(value)
    assert str(parsed) == value
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122
    assert before <= parsed.int >> 80 <= after


def test_event_ids_differ() -> None:
    assert len({new_event_id() for _ in range(100)}) == 100


def test_cube_dataset_id_round_trip() -> None:
    dataset_id = cube_dataset_id("sul-de-minas", 3, 17)

    assert dataset_id == "cube:sul-de-minas:3:17"
    assert parse_dataset_id(dataset_id) == CubeDataset(region_id="sul-de-minas", row=3, col=17)


def test_point_dataset_id_round_trip() -> None:
    dataset_id = point_dataset_id("86a8a899fffffff")

    assert dataset_id == "point:86a8a899fffffff"
    assert parse_dataset_id(dataset_id) == PointDataset(h3_cell="86a8a899fffffff")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "cube",
        "cube:sorriso:1",
        "cube:sorriso:1:2:3",
        "cube:sorriso:-1:2",
        "cube:sorriso:01:2",
        "cube:sorriso:a:2",
        "cube::1:2",
        "cube:Sorriso:1:2",
        "cube:sul de minas:1:2",
        "point:",
        "point:86a8a899ffffff",
        "point:86a8a899ffffffff",
        "point:86A8A899FFFFFFF",
        "point:zzzzzzzzzzzzzzz",
        "grid:86a8a899fffffff",
        "point:86a8a899fffffff\n",
        " cube:sorriso:1:2",
    ],
)
def test_malformed_dataset_id_is_rejected(value: str) -> None:
    with pytest.raises(InvalidArgumentsError):
        parse_dataset_id(value)


def test_format_helpers_reject_parts_that_would_not_parse_back() -> None:
    with pytest.raises(InvalidArgumentsError):
        cube_dataset_id("sorriso:1", 0, 0)
    with pytest.raises(InvalidArgumentsError):
        cube_dataset_id("sorriso", -1, 0)
    with pytest.raises(InvalidArgumentsError):
        point_dataset_id("not-a-cell")
