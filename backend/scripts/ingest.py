"""Fetch and cache the point history of one location from Open-Meteo (plan 01).

    make ingest LAT=<lat> LON=<lon>
    uv run python scripts/ingest.py --lat <lat> --lon <lon>

Exit codes when implemented: 0 cached, 1 failed, 3 the network is unavailable (reported as
open by `gate.py`).

Stub of plan 00: the owning plan replaces the body and keeps the command line above.
"""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch and cache the history of one point.")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.parse_args(argv)

    print("ingest: not implemented in this milestone", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
