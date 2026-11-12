"""Measure two chunk layouts of a region's cube, the evidence for ADR 0016 (SPEC 4.1).

Layout A is the one the store writes: the whole time axis by 10 by 10 cells, so the series
of one cell is one chunk object. Layout B is one field per time step: every day is a chunk
object holding the whole grid. The cube is written once in each layout to a working
directory on the local disk, and for each layout this records the size, the write time and
two reads: the full series of the centre cell, and the whole array.

Each read repetition runs in a new process, so nothing decoded earlier is reused; the time
is taken inside that process around opening the store and reading, and excludes starting
the interpreter and importing the libraries. The operating system's page cache is NOT
dropped between repetitions: after the write the files are in memory, so the reads measure
decoding and file handling, not a cold disk. The output says so.

Run as a module, this file is the reader of one repetition.
"""

import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from veranico.modules.climate.infrastructure import zarr_io

THIS_MODULE = "veranico.modules.climate.infrastructure.chunk_measure"
REPETITIONS = 5
POINT_READ = "point"
CUBE_READ = "cube"
PAGE_CACHE_NOTE = (
    "page cache not dropped: reads follow the write on the same machine and measure "
    "decoding and file handling, not a cold disk"
)
TIMING_NOTE = (
    "each read repetition is a new process; seconds are taken inside it around opening "
    "the store and reading, excluding interpreter start and imports"
)


def layouts(days: int, ny: int, nx: int) -> dict[str, tuple[int, int, int]]:
    return {
        "A: time=-1, lat=10, lon=10": zarr_io.cube_chunks(days, ny, nx),
        "B: time=1, whole grid": (1, ny, nx),
    }


def measure(
    region_id: str,
    source: str,
    dates: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    precipitation_mm: np.ndarray,
    work_dir: Path,
    *,
    commit: str,
    measured_at: datetime,
    repetitions: int = REPETITIONS,
) -> dict[str, Any]:
    """Write the cube in both layouts under `work_dir`, measure, and remove the copies."""
    days, ny, nx = precipitation_mm.shape
    centre = (ny // 2, nx // 2)
    results: dict[str, Any] = {}
    for name, chunks in layouts(days, ny, nx).items():
        target = work_dir / f"layout-{name[0].lower()}.zarr"
        shutil.rmtree(target, ignore_errors=True)
        try:
            started = time.perf_counter()
            zarr_io.write_cube(
                target, dates, latitudes, longitudes, precipitation_mm, chunks=chunks
            )
            write_seconds = time.perf_counter() - started
            array = target / zarr_io.PRECIPITATION
            files = [path for path in target.rglob("*") if path.is_file()]
            results[name] = {
                "chunks": {"time": chunks[0], "lat": chunks[1], "lon": chunks[2]},
                "store_bytes": sum(path.stat().st_size for path in files),
                "chunk_objects": sum(1 for path in (array / "c").rglob("*") if path.is_file()),
                "write_seconds": write_seconds,
                "point_read_seconds": _repeat(target, POINT_READ, centre, repetitions),
                "cube_read_seconds": _repeat(target, CUBE_READ, centre, repetitions),
                "compressor": _codecs(array),
            }
        finally:
            shutil.rmtree(target, ignore_errors=True)
    return {
        "region_id": region_id,
        "source": source,
        "shape": {"days": days, "ny": ny, "nx": nx},
        "first_date": str(dates[0]),
        "last_date": str(dates[-1]),
        "centre_cell": {"row": centre[0], "col": centre[1]},
        "repetitions": repetitions,
        "layouts": results,
        "versions": {
            "python": platform.python_version(),
            "xarray": version("xarray"),
            "zarr": version("zarr"),
            "numpy": version("numpy"),
        },
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
            "cpus": os.cpu_count() or 0,
            "storage": "local filesystem, working directory of the build",
        },
        "commit": commit,
        "measured_at": measured_at.isoformat(),
        "notes": [PAGE_CACHE_NOTE, TIMING_NOTE],
    }


def markdown_table(report: Mapping[str, Any]) -> str:
    """The report as a Markdown table, one column per layout."""
    names = list(report["layouts"])
    rows: list[tuple[str, Callable[[Mapping[str, Any]], str]]] = [
        ("chunk shape (time, lat, lon)", lambda r: "{time}, {lat}, {lon}".format(**r["chunks"])),
        ("store size", lambda r: f"{r['store_bytes'] / 1e6:.1f} MB"),
        ("chunk objects", lambda r: f"{r['chunk_objects']}"),
        ("write time", lambda r: f"{r['write_seconds']:.2f} s"),
        ("point read, median (min to max)", lambda r: _spread(r["point_read_seconds"])),
        ("cube read, median (min to max)", lambda r: _spread(r["cube_read_seconds"])),
        ("compressor", lambda r: r["compressor"]),
    ]
    shape = report["shape"]
    lines = [
        f"Chunk layouts of `{report['region_id']}`, source `{report['source']}`: "
        f"{shape['days']} days by {shape['ny']} by {shape['nx']} cells, "
        f"{report['repetitions']} repetitions, {report['commit']}, {report['measured_at']}.",
        "",
        "| Measure | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    lines += [
        f"| {label} | " + " | ".join(cell(report["layouts"][name]) for name in names) + " |"
        for label, cell in rows
    ]
    versions = report["versions"]
    lines += [
        "",
        f"xarray {versions['xarray']}, zarr {versions['zarr']}, numpy {versions['numpy']}, "
        f"Python {versions['python']}; {report['machine']['platform']}, "
        f"{report['machine']['cpus']} CPUs.",
        *(f"Note: {note}." for note in report["notes"]),
    ]
    return "\n".join(lines)


def _spread(seconds: Mapping[str, float]) -> str:
    return (
        f"{seconds['median'] * 1000:.1f} ms "
        f"({seconds['min'] * 1000:.1f} to {seconds['max'] * 1000:.1f})"
    )


def _repeat(target: Path, kind: str, cell: tuple[int, int], repetitions: int) -> dict[str, float]:
    seconds = [_read_in_new_process(target, kind, cell) for _ in range(repetitions)]
    return {"median": statistics.median(seconds), "min": min(seconds), "max": max(seconds)}


def _read_in_new_process(target: Path, kind: str, cell: tuple[int, int]) -> float:
    completed = subprocess.run(
        [sys.executable, "-m", THIS_MODULE, kind, str(target), str(cell[0]), str(cell[1])],
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    )
    return float(json.loads(completed.stdout)["seconds"])


def _codecs(array: Path) -> str:
    """The codecs of the stored array, as its metadata names them."""
    metadata = json.loads((array / "zarr.json").read_text(encoding="utf-8"))
    parts = []
    for codec in metadata["codecs"]:
        configuration = codec.get("configuration") or {}
        settings = ", ".join(f"{key}={value}" for key, value in sorted(configuration.items()))
        parts.append(f"{codec['name']}({settings})" if settings else codec["name"])
    return " + ".join(parts)


def _read_once(kind: str, target: Path, row: int, col: int) -> dict[str, Any]:
    started = time.perf_counter()
    if kind == POINT_READ:
        _, values = zarr_io.read_cell(target, row, col)
    else:
        _, values = zarr_io.read_cube(target)
    seconds = time.perf_counter() - started
    return {"seconds": seconds, "values": int(values.size)}


if __name__ == "__main__":
    print(
        json.dumps(_read_once(sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])))
    )
