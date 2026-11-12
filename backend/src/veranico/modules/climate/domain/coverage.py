"""Which years of history are wanted and which a store still lacks (SPEC 4, 4.2)."""

from datetime import date


def last_complete_year(today: date) -> int:
    """The last year whose every day is in the past: never the current year."""
    return today.year - 1


def missing_years(
    first_have: int | None, last_have: int | None, first_want: int, last_want: int
) -> list[int]:
    """Wanted years outside the stored range, ascending. An empty store has `None` bounds.

    A store holds whole, contiguous years, so its range is all that is needed.
    """
    if first_have is None or last_have is None:
        return list(range(first_want, last_want + 1))
    return [
        year for year in range(first_want, last_want + 1) if not first_have <= year <= last_have
    ]
