"""Build and install the precipitation cube of one showcase region (plan 01).

    make build-cube REGION=<id> [SYNTHETIC=1 SEED=<n>] [MEASURE=1]
    uv run --group cube python scripts/build_cube.py --region <id> [--synthetic --seed <n>]
        [--measure]

Without `--synthetic` the cube is real ERA5-Land read from Google Earth Engine (ADR 0018,
ADR 0019). That needs a Cloud project registered for Earth Engine, named in
`EARTHENGINE_PROJECT`, and credentials stored once by `earthengine authenticate`; without
either the script says that human gate H1 is open, names the step to take and exits 3,
before any download. Yearly files are kept under `.cache/earth-engine/<region>/`, so a
rerun downloads only the missing years.

With `--synthetic` a seeded, generated cube is installed and labelled synthetic: the region
then answers `synthetic = true`, and every cell reports the source `synthetic`.

The cube covers the first year of the settings (1950) through the last complete year, and
goes to the weather store the `VERANICO_CLIMATE__*` variables name.

With `--measure` nothing is built: the region's installed cube is written in two chunk
layouts to a working directory under `.cache/chunking/`, measured, and the copies removed.
The numbers go to standard output as a Markdown table and to
`.cache/chunking/<region>.json`; they are the evidence for ADR 0016.

Exit codes: 0 built or measured, 1 failed (including a request Earth Engine refused), 3 no
project, no credentials or no network (reported as open by `gate.py`).
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

from veranico.modules.climate.application.build_cube import (
    BuildCube,
    BuildReport,
    InstallSyntheticCube,
)
from veranico.modules.climate.application.ports import CubeSource, WeatherStore
from veranico.modules.climate.contracts import RegionCube
from veranico.modules.climate.domain.coverage import last_complete_year
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import (
    REGIONS,
    RegionDef,
    cell_centre,
    region_by_id,
)
from veranico.modules.climate.infrastructure.chunk_measure import markdown_table, measure
from veranico.modules.climate.infrastructure.cube_build import convert_to_arrays, file_checksum
from veranico.modules.climate.infrastructure.earth_engine_download import (
    PROJECT_VARIABLE,
    EarthEngineRefusedError,
    EarthEngineSetupError,
    EarthEngineUnreachableError,
    EarthEngineYearlySource,
    Fetch,
    earth_engine_fetch,
)
from veranico.modules.climate.infrastructure.synthetic import (
    GENERATOR,
    generate_cube,
    generator_parameters,
)
from veranico.modules.climate.module import StoreSettings, store_from_environment
from veranico.shared.kernel.clock import Clock, SystemClock
from veranico.shared.kernel.errors import DatasetNotFoundError

EXIT_OK, EXIT_FAILED, EXIT_OPEN = 0, 1, 3
YEARLY_CACHE = Path(".cache/earth-engine")
MEASUREMENTS = Path(".cache/chunking")
DEFAULT_SEED = 1


async def build_synthetic(
    store: WeatherStore, region: RegionDef, first_year: int, last_year: int, seed: int
) -> BuildReport:
    install = InstallSyntheticCube(store, generate_cube, GENERATOR, generator_parameters())
    return await install(region, first_year, last_year, seed)


async def build_real(
    store: WeatherStore,
    region: RegionDef,
    first_year: int,
    last_year: int,
    fetch: Fetch,
    cache_root: Path,
) -> BuildReport:
    build = BuildCube(
        store, EarthEngineYearlySource(fetch), convert_to_arrays, file_checksum, cache_root
    )
    return await build(region, first_year, last_year)


def measure_installed(store: WeatherStore, region: RegionDef, clock: Clock) -> int:
    """Measure the two chunk layouts on the region's installed cube (for ADR 0016)."""

    async def installed() -> tuple[RegionCube, CubeSource | None]:
        return await store.read_cube(region.region_id), await store.cube_source(region.region_id)

    try:
        cube, source = asyncio.run(installed())
    except DatasetNotFoundError:
        print(
            f"build_cube: failed, no cube is installed for {region.region_id}: build it first",
            file=sys.stderr,
        )
        return EXIT_FAILED
    MEASUREMENTS.mkdir(parents=True, exist_ok=True)
    work_dir = MEASUREMENTS / f"work-{region.region_id}-{os.getpid()}"
    work_dir.mkdir()
    try:
        report = measure(
            region.region_id,
            source or "unknown",
            cube.dates,
            np.array([cell_centre(region, row, 0)[0] for row in range(region.ny)]),
            np.array([cell_centre(region, 0, col)[1] for col in range(region.nx)]),
            cube.precipitation_mm,
            work_dir,
            commit=_commit(),
            measured_at=clock.now(),
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    target = MEASUREMENTS / f"{region.region_id}.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(markdown_table(report))
    print(f"\nWritten to {target}")
    return EXIT_OK


def _commit() -> str:
    """The commit the measurement ran on, or `working tree` when files differ from it."""

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments], capture_output=True, text=True, check=True, timeout=30
        )
        return completed.stdout.strip()

    try:
        commit = git("rev-parse", "--short", "HEAD")
        dirty = bool(git("status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        return "unknown commit"
    return f"working tree on {commit}" if dirty else f"commit {commit}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the cube of one region.")
    parser.add_argument("--region", required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--measure", action="store_true")
    arguments = parser.parse_args(argv)

    region = region_by_id(arguments.region)
    if region is None:
        known = ", ".join(definition.region_id for definition in REGIONS)
        print(f"build_cube: unknown region '{arguments.region}'; known: {known}", file=sys.stderr)
        return EXIT_FAILED
    settings = StoreSettings()
    clock = SystemClock()
    if arguments.measure:
        return measure_installed(store_from_environment(settings, clock), region, clock)
    first_year = settings.climate.first_year
    last_year = last_complete_year(clock.now().date())
    project = os.environ.get(PROJECT_VARIABLE, "").strip()
    if not arguments.synthetic and not project:
        print(
            f"build_cube: open, {PROJECT_VARIABLE} is not set: the real cube needs a Cloud "
            "project registered for Earth Engine (human gate H1); put its id in .env as "
            f"{PROJECT_VARIABLE}=<project-id>. Use --synthetic for a seeded cube labelled "
            "synthetic.",
            file=sys.stderr,
        )
        return EXIT_OPEN

    store = store_from_environment(settings, clock)
    try:
        if arguments.synthetic:
            report = asyncio.run(
                build_synthetic(store, region, first_year, last_year, arguments.seed)
            )
        else:
            fetch = earth_engine_fetch(project)  # before any download
            report = asyncio.run(
                build_real(store, region, first_year, last_year, fetch, YEARLY_CACHE)
            )
    except EarthEngineSetupError as error:
        print(f"build_cube: open, {error}", file=sys.stderr)
        return EXIT_OPEN
    except EarthEngineUnreachableError:
        print("build_cube: open, no answer from Earth Engine", file=sys.stderr)
        return EXIT_OPEN
    except EarthEngineRefusedError as error:
        print(f"build_cube: failed, {error}", file=sys.stderr)
        return EXIT_FAILED
    except WeatherDataError as error:
        print(f"build_cube: failed, {error}", file=sys.stderr)
        return EXIT_FAILED
    summary = asdict(report)
    if arguments.synthetic:
        summary["seed"] = arguments.seed
    print(json.dumps(summary, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
