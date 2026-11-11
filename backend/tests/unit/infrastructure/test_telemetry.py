"""The telemetry entry points every caller relies on.

Their behaviour is covered by `tests/unit/delivery/test_telemetry.py`; this test only pins the
four names and signatures that `main.py`, `problems.py` and the modules call.
"""

import inspect

from veranico.shared.infrastructure import telemetry


def test_the_four_entry_points_keep_their_names_and_signatures() -> None:
    assert list(inspect.signature(telemetry.setup_telemetry).parameters) == ["settings", "app"]
    assert list(inspect.signature(telemetry.shutdown).parameters) == []
    assert list(inspect.signature(telemetry.current_trace_id).parameters) == []
    assert callable(telemetry.tracer)


def test_there_is_no_trace_id_outside_a_span() -> None:
    telemetry.shutdown()

    assert telemetry.current_trace_id() is None
