"""The small JSON documents that make a weather store current, and its layout.

Layout under the store root, the same for the local and the Cloud Storage adapter:

    climate/points/<h3>/manifest.json         names the current build of a point store
    climate/points/<h3>/<build>.zarr/         one build; never modified after it is written
    climate/points/aliases/<requested_h3>.json  the dataset a clicked cell resolved to

A build becomes visible only when the manifest that names it is switched in, which is one
atomic step (a rename locally, a conditional upload on Cloud Storage).
"""

import hashlib
import uuid
from datetime import date, datetime
from typing import Literal

import numpy as np
from pydantic import BaseModel

from veranico.modules.climate.contracts import DatasetRef, GridPoint
from veranico.shared.kernel.ids import DatasetId

POINTS_PREFIX = "climate/points/"
ALIASES_PREFIX = "climate/points/aliases/"
MANIFEST_NAME = "manifest.json"

Source = Literal["era5-land/cds", "era5/open-meteo", "synthetic"]


def point_manifest_path(h3_cell: str) -> str:
    return f"{POINTS_PREFIX}{h3_cell}/{MANIFEST_NAME}"


def point_build_path(h3_cell: str, build: str) -> str:
    return f"{POINTS_PREFIX}{h3_cell}/{build}.zarr"


def alias_path(requested_h3: str) -> str:
    return f"{ALIASES_PREFIX}{requested_h3}.json"


def new_build_name() -> str:
    """A name no other writer uses, so concurrent writers never share a build."""
    return f"b-{uuid.uuid4().hex}"


def series_checksum(dates: np.ndarray, precipitation_mm: np.ndarray) -> str:
    """SHA-256 over the days and the values: identical data gives an identical checksum."""
    digest = hashlib.sha256()
    digest.update(dates.astype("datetime64[D]").astype("<i8").tobytes())
    digest.update(precipitation_mm.astype("<f8").tobytes())
    return f"sha256:{digest.hexdigest()}"


class PointManifest(BaseModel, frozen=True):
    format_version: Literal[1] = 1
    dataset_id: DatasetId
    build: str
    source: Source
    grid_point: GridPoint
    first_date: date
    last_date: date
    days: int
    missing_days: int
    request: dict[str, str]  # what was asked of the source, kept as provenance
    checksum: str  # of the stored data, see `series_checksum`
    written_at: datetime

    def dataset_ref(self) -> DatasetRef:
        return DatasetRef(
            dataset_id=self.dataset_id,
            kind="point",
            region_id=None,
            grid_point=self.grid_point,
            first_year=self.first_date.year,
            last_year=self.last_date.year,
            days=self.days,
            missing_days=self.missing_days,
            source=self.source,
        )


class Alias(BaseModel, frozen=True):
    dataset_id: DatasetId
