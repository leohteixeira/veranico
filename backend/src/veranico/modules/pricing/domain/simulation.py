"""Simulation of seasonal index values and the payout statistics they give (SPEC 5.5).

`rainfall_below`: a gamma distribution fitted to the seasonal totals by maximum likelihood,
location fixed at zero. Maximum likelihood is undefined when a total is zero and can fail
to converge (a constant history); the simulation then bootstraps the history and says so
through `method`. `dry_spell_above`: always the bootstrap of the historical values.

One generator per call, seeded, with a single draw of `n` values. Money is float centavos.
"""

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
from scipy import stats

from veranico.modules.pricing.domain.backtest import paying
from veranico.modules.pricing.domain.index import IndexType
from veranico.modules.pricing.domain.payout import payout_fraction

SimulationMethod = Literal["gamma_mle", "bootstrap"]

ONE_IN_10_PERCENTILE = 90.0
ONE_IN_100_PERCENTILE = 99.0
# The empirical quantile: always a simulated payout, never a value interpolated between two.
PERCENTILE_METHOD: Literal["inverted_cdf"] = "inverted_cdf"


@dataclass(frozen=True, slots=True)
class GammaFit:
    shape: float
    scale: float

    @property
    def mean(self) -> float:
        return self.shape * self.scale


@dataclass(frozen=True, slots=True)
class SimulationFigures:
    method: SimulationMethod
    n: int
    seed: int
    expected_loss: float  # centavos: mean simulated payout
    std_dev: float  # centavos: population standard deviation of the simulated payouts
    probability_of_payout: float
    payout_1_in_10: float  # centavos: 90th percentile
    payout_1_in_100: float  # centavos: 99th percentile


def fit_gamma(values: npt.NDArray[np.float64]) -> GammaFit | None:
    """Maximum-likelihood gamma with location zero, or `None` when it is undefined."""
    if values.size < 2 or bool(np.any(values <= 0)):
        return None
    if bool(np.all(values == values[0])):
        return None  # a constant history: the likelihood grows without bound, no maximum
    try:
        shape, _, scale = stats.gamma.fit(values, floc=0)
    except ValueError:  # SciPy's solver did not converge
        return None
    if not (math.isfinite(shape) and math.isfinite(scale) and shape > 0 and scale > 0):
        return None
    return GammaFit(shape=float(shape), scale=float(scale))


def simulate(
    index_type: IndexType,
    index_values: npt.NDArray[np.float64],
    trigger: float,
    exit: float,
    limit_cents: float,
    n: int,
    seed: int,
) -> SimulationFigures:
    """Simulate `n` seasons from the history `index_values`. The cover must be valid."""
    if n < 1:
        raise ValueError("the simulation needs at least one draw")
    history = np.asarray(index_values, dtype=np.float64)
    if history.size == 0:
        raise ValueError("the simulation needs at least one historical season")
    generator = np.random.default_rng(seed)
    fit = fit_gamma(history) if index_type == "rainfall_below" else None
    method: SimulationMethod
    if fit is not None:
        method = "gamma_mle"
        simulated = generator.gamma(fit.shape, fit.scale, n)
    else:
        method = "bootstrap"
        simulated = generator.choice(history, size=n, replace=True)
    payouts = limit_cents * payout_fraction(index_type, simulated, trigger, exit)
    seasons_paying = int(np.count_nonzero(paying(index_type, simulated, trigger)))
    return SimulationFigures(
        method=method,
        n=n,
        seed=seed,
        expected_loss=float(payouts.mean()),
        std_dev=float(payouts.std(ddof=0)),
        probability_of_payout=seasons_paying / n,
        payout_1_in_10=float(
            np.percentile(payouts, ONE_IN_10_PERCENTILE, method=PERCENTILE_METHOD)
        ),
        payout_1_in_100=float(
            np.percentile(payouts, ONE_IN_100_PERCENTILE, method=PERCENTILE_METHOD)
        ),
    )
