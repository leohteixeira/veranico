"""`build_cube.py --measure` on a tiny synthetic cube: every field, for both layouts.

The figures of a two-year cube mean nothing; the test checks that the measurement runs and
reports everything ADR 0016 needs.
"""

import json
from pathlib import Path

import pytest
from scripts import build_cube as script

pytestmark = pytest.mark.slow

LAYOUT_A = "A: time=-1, lat=10, lon=10"
LAYOUT_B = "B: time=1, whole grid"


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A store and a measurement directory under `tmp_path`, two years of history."""
    monkeypatch.setenv("VERANICO_CLIMATE__STORE_BACKEND", "local")
    monkeypatch.setenv("VERANICO_CLIMATE__STORE_ROOT", str(tmp_path / "weather"))
    monkeypatch.setenv("VERANICO_CLIMATE__FIRST_YEAR", "2024")
    monkeypatch.setattr(script, "MEASUREMENTS", tmp_path / "chunking")
    return tmp_path


@pytest.mark.req("R-4.1-3")
def test_measure_emits_every_field_for_both_layouts(
    environment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--region", "sorriso", "--synthetic", "--seed", "4"]) == 0
    capsys.readouterr()

    assert script.main(["--region", "sorriso", "--measure"]) == 0

    table = capsys.readouterr().out
    report = json.loads((environment / "chunking" / "sorriso.json").read_text())
    days = report["shape"]["days"]
    assert report["region_id"] == "sorriso"
    assert report["source"] == "synthetic"
    assert report["shape"] == {"days": days, "ny": 20, "nx": 20}
    assert days >= 731
    assert report["first_date"] == "2024-01-01"
    assert report["centre_cell"] == {"row": 10, "col": 10}
    assert report["repetitions"] == 5
    assert set(report["versions"]) == {"python", "xarray", "zarr", "numpy"}
    assert set(report["machine"]) == {"platform", "processor", "cpus", "storage"}
    assert report["commit"].startswith(("commit ", "working tree on ", "unknown commit"))
    assert report["measured_at"]
    assert any("page cache not dropped" in note for note in report["notes"])

    assert list(report["layouts"]) == [LAYOUT_A, LAYOUT_B]
    a, b = report["layouts"][LAYOUT_A], report["layouts"][LAYOUT_B]
    assert a["chunks"] == {"time": days, "lat": 10, "lon": 10}
    assert b["chunks"] == {"time": 1, "lat": 20, "lon": 20}
    assert a["chunk_objects"] == 4
    assert b["chunk_objects"] == days
    for layout in (a, b):
        assert layout["store_bytes"] > 0
        assert layout["write_seconds"] > 0
        assert layout["compressor"]
        for read in ("point_read_seconds", "cube_read_seconds"):
            seconds = layout[read]
            assert set(seconds) == {"median", "min", "max"}
            assert 0 < seconds["min"] <= seconds["median"] <= seconds["max"]

    assert "source `synthetic`" in table
    assert f"| Measure | {LAYOUT_A} | {LAYOUT_B} |" in table
    for label in (
        "chunk shape",
        "store size",
        "chunk objects",
        "write time",
        "point read",
        "cube read",
        "compressor",
        "page cache not dropped",
    ):
        assert label in table
    # The copies are removed: only the report stays.
    assert sorted(path.name for path in (environment / "chunking").iterdir()) == ["sorriso.json"]


def test_measure_without_an_installed_cube_fails_in_one_line(
    environment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--region", "sorriso", "--measure"]) == 1

    assert capsys.readouterr().err == (
        "build_cube: failed, no cube is installed for sorriso: build it first\n"
    )
