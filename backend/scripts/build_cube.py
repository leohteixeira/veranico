"""Build and install the precipitation cube of one showcase region (plan 01).

    make build-cube REGION=<id> [SYNTHETIC=1 SEED=<n>] [MEASURE=1]
    uv run --group cube python scripts/build_cube.py --region <id> [--synthetic --seed <n>]
        [--measure]

Without `--synthetic` the cube is real ERA5-Land from the Copernicus Climate Data Store
(ADR 0018). That needs the personal access token in `CDS_API_KEY`; without it the script
says that human gate H1 is open and exits 3. Yearly files are kept under
`.cache/cds/<region>/`, so a rerun downloads only the missing years.

With `--synthetic` a seeded, generated cube is installed and labelled synthetic: the region
then answers `synthetic = true`, and every cell reports the source `synthetic`.

The cube covers the first year of the settings (1950) through the last complete year, and
goes to the weather store the `VERANICO_CLIMATE__*` variables name.

Exit codes: 0 built, 1 failed, 2 not implemented (`--measure`), 3 no CDS key or no network
(reported as open by `gate.py`).
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from veranico.modules.climate.application.build_cube import (
    BuildCube,
    BuildReport,
    InstallSyntheticCube,
)
from veranico.modules.climate.application.ports import WeatherStore
from veranico.modules.climate.domain.coverage import last_complete_year
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import REGIONS, RegionDef, region_by_id
from veranico.modules.climate.infrastructure.cds_download import (
    CdsRefusedError,
    CdsUnreachableError,
    CdsYearlySource,
    cdsapi_retrieve,
)
from veranico.modules.climate.infrastructure.cube_build import convert_to_arrays, file_checksum
from veranico.modules.climate.infrastructure.synthetic import (
    GENERATOR,
    generate_cube,
    generator_parameters,
)
from veranico.modules.climate.module import StoreSettings, store_from_environment
from veranico.shared.kernel.clock import SystemClock

EXIT_OK, EXIT_FAILED, EXIT_NOT_IMPLEMENTED, EXIT_OPEN = 0, 1, 2, 3
CDS_KEY_VARIABLE = "CDS_API_KEY"
CDS_CACHE = Path(".cache/cds")
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
    key: str,
    cache_root: Path,
) -> BuildReport:
    build = BuildCube(
        store, CdsYearlySource(cdsapi_retrieve(key)), convert_to_arrays, file_checksum, cache_root
    )
    return await build(region, first_year, last_year)


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
    if arguments.measure:
        print("build_cube: --measure is not implemented in this milestone", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED

    settings = StoreSettings()
    clock = SystemClock()
    first_year = settings.climate.first_year
    last_year = last_complete_year(clock.now().date())
    key = os.environ.get(CDS_KEY_VARIABLE, "").strip()
    if not arguments.synthetic and not key:
        print(
            f"build_cube: open, {CDS_KEY_VARIABLE} is not set: the real cube needs a Copernicus "
            "account (human gate H1). Use --synthetic for a seeded cube labelled synthetic.",
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
            report = asyncio.run(build_real(store, region, first_year, last_year, key, CDS_CACHE))
    except CdsUnreachableError:
        print("build_cube: open, no answer from the Climate Data Store", file=sys.stderr)
        return EXIT_OPEN
    except CdsRefusedError as error:
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
