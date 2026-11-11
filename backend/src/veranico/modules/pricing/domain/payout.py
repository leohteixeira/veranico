"""Payout structure (SPEC 5.3): linear between trigger and exit, capped at the limit.

    rainfall_below:  fraction = clamp((trigger - index) / (trigger - exit), 0, 1), exit < trigger
    dry_spell_above: fraction = clamp((index - trigger) / (exit - trigger), 0, 1), exit > trigger

The payout is the limit times the fraction.
"""

import math

import numpy as np
import numpy.typing as npt

from veranico.modules.pricing.domain.errors import InvalidCoverError
from veranico.modules.pricing.domain.index import IndexType


def validate_index(index_type: IndexType, trigger: float, exit: float) -> None:
    """Raises `invalid_cover` unless the exit lies strictly on the paying side of the trigger."""
    if not (math.isfinite(trigger) and math.isfinite(exit)):
        raise InvalidCoverError("the trigger and the exit must be finite numbers")
    if index_type == "rainfall_below":
        if not exit < trigger:
            raise InvalidCoverError("rainfall_below needs an exit below the trigger")
    elif not exit > trigger:
        raise InvalidCoverError("dry_spell_above needs an exit above the trigger")


def validate_cover(index_type: IndexType, trigger: float, exit: float, limit_cents: float) -> None:
    validate_index(index_type, trigger, exit)
    if not limit_cents > 0:
        raise InvalidCoverError("the limit must be positive")


def payout_fraction(
    index_type: IndexType,
    index_values: npt.ArrayLike,
    trigger: float,
    exit: float,
) -> npt.NDArray[np.float64]:
    """Share of the limit paid for each index value, in [0, 1]. The cover must be valid."""
    values = np.asarray(index_values, dtype=np.float64)
    if index_type == "rainfall_below":
        raw = (trigger - values) / (trigger - exit)
    else:
        raw = (values - trigger) / (exit - trigger)
    floored = np.maximum(raw, 0.0)
    return np.minimum(floored, 1.0)
