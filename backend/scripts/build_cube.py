"""Download ERA5-Land from the CDS and build the regional cube (plan 01).

    make build-cube REGION=<id> [SYNTHETIC=1 SEED=<n>] [MEASURE=1]
    uv run --group cube python scripts/build_cube.py --region <id> [--synthetic --seed <n>]
        [--measure]

Exit codes when implemented: 0 built, 1 failed, 3 no CDS key or no network (reported as open
by `gate.py`).

Stub of plan 00: the owning plan replaces the body and keeps the command line above.
"""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the cube of one region.")
    parser.add_argument("--region", required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--measure", action="store_true")
    parser.parse_args(argv)

    print("build_cube: not implemented in this milestone", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
