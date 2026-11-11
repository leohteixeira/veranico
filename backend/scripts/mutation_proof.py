"""Apply the mutation catalogue to `pricing/domain` and assert the tests fail (plan 02).

    make mutation-proof
    uv run python scripts/mutation_proof.py [--only <name>] [--json <path>]

No arguments runs the whole catalogue, `--only <name>` runs one mutant, `--json <path>` writes
the result. Exit code when implemented: 0 only when every mutant is killed.

Stub of plan 00: the owning plan replaces the body and keeps the command line above.
"""

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the mutation catalogue.")
    parser.add_argument("--only", metavar="NAME")
    parser.add_argument("--json", metavar="PATH", type=Path)
    parser.parse_args(argv)

    print("mutation_proof: not implemented in this milestone", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
