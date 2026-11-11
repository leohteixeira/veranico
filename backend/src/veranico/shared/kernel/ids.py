"""Identifiers of the shared kernel, their generators and the dataset id formats."""

import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Literal, NewType

from veranico.shared.kernel.errors import InvalidArgumentsError

WorkspaceId = NewType("WorkspaceId", str)
QuoteId = NewType("QuoteId", str)  # "Q-" + 6 Crockford base32 characters
SubmissionId = NewType("SubmissionId", str)  # "S-" + 6
ConversationId = NewType("ConversationId", str)
DatasetId = NewType("DatasetId", str)  # "cube:<region_id>:<row>:<col>" or "point:<h3_cell>"
EventId = NewType("EventId", str)  # UUIDv7
Locale = Literal["en", "pt-BR"]

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_SUFFIX = "[0-9A-HJKMNP-TV-Z]{6}"

# `\Z` and not `$`: `$` also matches before a trailing newline.
QUOTE_ID_PATTERN = re.compile(rf"\AQ-{_SUFFIX}\Z")
SUBMISSION_ID_PATTERN = re.compile(rf"\AS-{_SUFFIX}\Z")
RECEIPT_ID_PATTERN = re.compile(rf"\AR-{_SUFFIX}\Z")

_CUBE_DATASET = re.compile(r"\Acube:([a-z0-9]+(?:-[a-z0-9]+)*):(0|[1-9]\d*):(0|[1-9]\d*)\Z")
_POINT_DATASET = re.compile(r"\Apoint:([0-9a-f]{15})\Z")


def _suffix() -> str:
    return "".join(secrets.choice(_CROCKFORD) for _ in range(6))


def new_quote_id() -> QuoteId:
    return QuoteId(f"Q-{_suffix()}")


def new_submission_id() -> SubmissionId:
    return SubmissionId(f"S-{_suffix()}")


def new_receipt_id() -> str:
    return f"R-{_suffix()}"


def new_event_id() -> EventId:
    """UUIDv7 (RFC 9562, section 5.7): 48-bit Unix milliseconds, then random bits."""
    milliseconds = time.time_ns() // 1_000_000
    value = (
        (milliseconds & 0xFFFF_FFFF_FFFF) << 80
        | 0x7 << 76
        | secrets.randbits(12) << 64
        | 0b10 << 62
        | secrets.randbits(62)
    )
    return EventId(str(uuid.UUID(int=value)))


@dataclass(frozen=True, slots=True)
class CubeDataset:
    region_id: str
    row: int
    col: int


@dataclass(frozen=True, slots=True)
class PointDataset:
    h3_cell: str


def cube_dataset_id(region_id: str, row: int, col: int) -> DatasetId:
    return _checked(f"cube:{region_id}:{row}:{col}")


def point_dataset_id(h3_cell: str) -> DatasetId:
    return _checked(f"point:{h3_cell}")


def parse_dataset_id(value: str) -> CubeDataset | PointDataset:
    """Parse either dataset id form; a malformed id is `invalid_arguments`."""
    cube = _CUBE_DATASET.match(value)
    if cube:
        return CubeDataset(region_id=cube[1], row=int(cube[2]), col=int(cube[3]))
    point = _POINT_DATASET.match(value)
    if point:
        return PointDataset(h3_cell=point[1])
    raise InvalidArgumentsError("malformed dataset id")


def _checked(value: str) -> DatasetId:
    parse_dataset_id(value)
    return DatasetId(value)
