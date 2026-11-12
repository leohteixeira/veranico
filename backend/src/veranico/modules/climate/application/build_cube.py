"""Use cases behind `scripts/build_cube.py`: install a region's cube (SPEC 4.1).

`BuildCube` is the real path: one yearly file per year from a `YearlySource`, kept in a
cache so a rerun downloads only what is missing, then converted and written as one cube.
`InstallSyntheticCube` writes a generated cube through the same store, labelled synthetic.

Neither runs inside the service: the running application never calls the Climate Data
Store.
"""

import asyncio
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from veranico.modules.climate.application.ports import CubeSource, CubeWrite, WeatherStore
from veranico.modules.climate.contracts import RegionCube
from veranico.modules.climate.domain.regions import RegionDef

REAL_SOURCE: CubeSource = "era5-land/cds"
SYNTHETIC_SOURCE: CubeSource = "synthetic"


class YearlySource(Protocol):
    def download(self, region: RegionDef, year: int, target: Path) -> None:
        """Write the yearly file of `region` and `year` (local-day sums in metres) to
        `target`. Blocks. Raises when the source's answer is not what was asked for."""
        ...

    def provenance(self, region: RegionDef) -> Mapping[str, str]:
        """What is asked of the source for this region, recorded in the cube's manifest."""
        ...


# Blocking functions the infrastructure provides.
ConvertYears = Callable[[Sequence[Path], RegionDef], tuple[np.ndarray, np.ndarray]]
FileChecksum = Callable[[Path], str]
GenerateCube = Callable[[RegionDef, int, int, int], RegionCube]


@dataclass(frozen=True, slots=True)
class BuildReport:
    region_id: str
    source: CubeSource
    first_year: int
    last_year: int
    downloaded: tuple[int, ...]  # years fetched in this run
    reused: tuple[int, ...]  # years taken from the cache


class BuildCube:
    def __init__(
        self,
        store: WeatherStore,
        source: YearlySource,
        convert: ConvertYears,
        checksum: FileChecksum,
        cache_root: Path,
    ) -> None:
        self._store = store
        self._source = source
        self._convert = convert
        self._checksum = checksum
        self._cache_root = cache_root

    async def __call__(self, region: RegionDef, first_year: int, last_year: int) -> BuildReport:
        years = range(first_year, last_year + 1)
        downloaded: list[int] = []
        checksums: dict[int, str] = {}
        for year in years:
            fetched, checksums[year] = await asyncio.to_thread(self._ensure_year, region, year)
            if fetched:
                downloaded.append(year)
        paths = [self.yearly_path(region, year) for year in years]
        dates, precipitation = await asyncio.to_thread(self._convert, paths, region)
        await self._store.write_cube(
            CubeWrite(
                region_id=region.region_id,
                source=REAL_SOURCE,
                dates=dates,
                precipitation_mm=precipitation,
                request=dict(self._source.provenance(region)),
                year_checksums=checksums,
            )
        )
        return BuildReport(
            region_id=region.region_id,
            source=REAL_SOURCE,
            first_year=first_year,
            last_year=last_year,
            downloaded=tuple(downloaded),
            reused=tuple(year for year in years if year not in downloaded),
        )

    def yearly_path(self, region: RegionDef, year: int) -> Path:
        return self._cache_root / region.region_id / f"{year}.nc"

    def _ensure_year(self, region: RegionDef, year: int) -> tuple[bool, str]:
        """Make the year's file present; return (whether it was downloaded, its checksum).

        A cached file counts only with its checksum sidecar, and only when the sidecar
        still matches it: the sidecar is written after the file, so a file without one may
        be a partial download or a file changed afterwards.
        """
        path = self.yearly_path(region, year)
        sidecar = path.with_name(f"{path.name}.sha256")
        if path.exists() and sidecar.exists():
            checksum = self._checksum(path)
            if sidecar.read_text(encoding="utf-8").strip() == checksum:
                return False, checksum
        path.parent.mkdir(parents=True, exist_ok=True)
        sidecar.unlink(missing_ok=True)
        partial = path.with_name(f"{path.name}.part")
        partial.unlink(missing_ok=True)
        try:
            self._source.download(region, year, partial)
            checksum = self._checksum(partial)
            os.replace(partial, path)
        finally:
            partial.unlink(missing_ok=True)
        sidecar.write_text(f"{checksum}\n", encoding="utf-8")
        return True, checksum


class InstallSyntheticCube:
    def __init__(
        self,
        store: WeatherStore,
        generate: GenerateCube,
        generator: str,
        parameters: Mapping[str, str],
    ) -> None:
        self._store = store
        self._generate = generate
        self._generator = generator
        self._parameters = parameters

    async def __call__(
        self, region: RegionDef, first_year: int, last_year: int, seed: int
    ) -> BuildReport:
        cube = await asyncio.to_thread(self._generate, region, first_year, last_year, seed)
        await self._store.write_cube(
            CubeWrite(
                region_id=region.region_id,
                source=SYNTHETIC_SOURCE,
                dates=cube.dates,
                precipitation_mm=cube.precipitation_mm,
                # No file was read: the manifest records how the cube was generated.
                request={
                    "generator": self._generator,
                    "seed": str(seed),
                    "first_year": str(first_year),
                    "last_year": str(last_year),
                    **self._parameters,
                },
                year_checksums={},
            )
        )
        return BuildReport(
            region_id=region.region_id,
            source=SYNTHETIC_SOURCE,
            first_year=first_year,
            last_year=last_year,
            downloaded=(),
            reused=(),
        )
