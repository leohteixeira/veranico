"""Errors of the climate domain that are not client-facing."""


class WeatherDataError(Exception):
    """Weather data broke a rule that must hold before a write (SPEC 4.4).

    Deliberately not a `DomainError`: the caller did nothing wrong, the source or the
    pipeline did. It surfaces as an internal failure and nothing is written.
    """
