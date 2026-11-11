"""Simulation (SPEC 5.5), by analytical expectation rather than by seeded golden values.

NumPy does not promise the same stream from `Generator` methods across versions, so no
test here asserts a figure that only one NumPy version would produce.
"""

from dataclasses import replace

import numpy as np
import pytest

from veranico.modules.pricing.domain.simulation import SimulationFigures, fit_gamma, simulate

LIMIT_CENTS = 30_000_000
N = 100_000
SEED = 42


def dry_spell(history: list[float], *, n: int = N, seed: int = SEED) -> SimulationFigures:
    """dry_spell_above, trigger 10 days, exit 25 days."""
    return simulate("dry_spell_above", np.array(history), 10.0, 25.0, LIMIT_CENTS, n, seed)


def rainfall(history: list[float], *, n: int = N, seed: int = SEED) -> SimulationFigures:
    """rainfall_below, trigger 100 mm, exit 40 mm."""
    return simulate("rainfall_below", np.array(history), 100.0, 40.0, LIMIT_CENTS, n, seed)


@pytest.mark.req("R-5.5-4")
def test_history_entirely_on_the_non_paying_side_never_pays() -> None:
    for figures in (
        dry_spell([3.0, 5.0, 8.0, 10.0]),  # at most the trigger
        rainfall([1000.0, 1001.0, 1002.0, 1003.0, 1004.0]),  # a tight gamma far above 100 mm
    ):
        assert figures.expected_loss == 0.0
        assert figures.std_dev == 0.0
        assert figures.probability_of_payout == 0.0
        assert figures.payout_1_in_10 == 0.0
        assert figures.payout_1_in_100 == 0.0


@pytest.mark.req("R-5.5-4")
def test_history_entirely_beyond_the_exit_always_pays_the_limit() -> None:
    for figures in (
        dry_spell([25.0, 30.0, 41.0]),
        rainfall([10.0, 10.5, 11.0, 11.5, 12.0]),  # a tight gamma far below 40 mm
    ):
        assert figures.expected_loss == pytest.approx(LIMIT_CENTS, abs=1e-6)
        assert figures.std_dev == pytest.approx(0.0, abs=1e-6)
        assert figures.probability_of_payout == 1.0
        assert figures.payout_1_in_10 == pytest.approx(LIMIT_CENTS, abs=1e-6)
        assert figures.payout_1_in_100 == pytest.approx(LIMIT_CENTS, abs=1e-6)


@pytest.mark.req("R-5.5-2")
@pytest.mark.req("R-5.5-4")
def test_bootstrap_over_one_paying_and_one_dry_value_pays_half_the_time() -> None:
    figures = dry_spell([30.0, 5.0])

    assert figures.method == "bootstrap"
    assert figures.probability_of_payout == pytest.approx(0.5, abs=0.01)
    assert figures.expected_loss == pytest.approx(0.5 * LIMIT_CENTS, rel=0.02)
    # population standard deviation of a fair coin paying the limit: limit / 2
    assert figures.std_dev == pytest.approx(0.5 * LIMIT_CENTS, rel=0.01)


@pytest.mark.req("R-5.5-4")
def test_expected_loss_is_the_mean_payout_including_partial_payouts() -> None:
    # 16 days pays 12,000,000 (two fifths of the limit); the other value pays nothing
    figures = dry_spell([16.0, 5.0])

    assert figures.expected_loss == pytest.approx(6_000_000, rel=0.02)
    assert figures.std_dev == pytest.approx(6_000_000, rel=0.02)


@pytest.mark.req("R-5.5-4")
def test_tails_are_the_90th_and_99th_percentiles_of_simulated_payouts() -> None:
    # one of twenty historical values pays the full limit: probability 0.05
    figures = dry_spell([5.0] * 19 + [30.0])

    assert figures.probability_of_payout == pytest.approx(0.05, abs=0.005)
    assert figures.payout_1_in_10 == 0.0
    assert figures.payout_1_in_100 == pytest.approx(LIMIT_CENTS, abs=1e-6)


@pytest.mark.req("R-5.5-4")
def test_tail_is_a_simulated_payout_never_an_interpolated_one() -> None:
    # payouts are either 0 or the limit, so every percentile is one of the two
    figures = dry_spell([5.0] * 9 + [30.0])

    assert figures.payout_1_in_10 in (0.0, pytest.approx(LIMIT_CENTS, abs=1e-6))


@pytest.mark.req("R-5.5-1")
def test_fitting_a_large_gamma_sample_recovers_its_mean() -> None:
    sample = np.random.default_rng(7).gamma(4.0, 50.0, 5000)  # mean 200

    fit = fit_gamma(sample)

    assert fit is not None
    assert fit.mean == pytest.approx(200.0, rel=0.02)
    assert fit.shape == pytest.approx(4.0, rel=0.1)


@pytest.mark.req("R-5.5-1")
def test_rainfall_simulation_samples_the_fitted_gamma() -> None:
    history = np.random.default_rng(11).gamma(4.0, 50.0, 2000)

    figures = simulate("rainfall_below", history, 100.0, 40.0, LIMIT_CENTS, N, SEED)

    assert figures.method == "gamma_mle"
    # P(X < 100) for gamma(shape 4, scale 50) is 1 - e^-2 (1 + 2 + 2 + 4/3) = 0.1429
    assert figures.probability_of_payout == pytest.approx(0.1429, abs=0.02)
    assert 0 < figures.expected_loss < LIMIT_CENTS
    assert figures.payout_1_in_10 <= figures.payout_1_in_100 <= LIMIT_CENTS


@pytest.mark.req("R-5.5-1")
def test_history_containing_a_zero_total_falls_back_to_the_bootstrap() -> None:
    figures = rainfall([0.0, 150.0, 200.0, 250.0])

    assert figures.method == "bootstrap"
    assert figures.probability_of_payout == pytest.approx(0.25, abs=0.01)
    assert fit_gamma(np.array([0.0, 150.0, 200.0])) is None


@pytest.mark.req("R-5.5-1")
def test_history_the_fit_cannot_converge_on_falls_back_to_the_bootstrap() -> None:
    figures = rainfall([50.0, 50.0, 50.0, 50.0])  # constant: the likelihood has no maximum

    assert figures.method == "bootstrap"
    # 50 mm between trigger 100 and exit 40 pays five sixths of the limit, every time
    assert figures.expected_loss == pytest.approx(25_000_000, abs=1e-3)


@pytest.mark.req("R-5.5-2")
def test_dry_spell_always_uses_the_bootstrap() -> None:
    assert dry_spell([3.0, 12.0, 7.0, 20.0, 9.0]).method == "bootstrap"


@pytest.mark.req("R-5-1")
@pytest.mark.req("R-5.5-3")
def test_same_seed_gives_identical_figures() -> None:
    history = [3.0, 12.0, 7.0, 20.0, 9.0, 16.0, 30.0]

    assert dry_spell(history) == dry_spell(history)
    assert rainfall([80.0, 150.0, 120.0, 60.0, 200.0]) == rainfall(
        [80.0, 150.0, 120.0, 60.0, 200.0]
    )


@pytest.mark.req("R-5.5-3")
def test_another_seed_gives_other_figures() -> None:
    history = [3.0, 12.0, 7.0, 20.0, 9.0, 16.0, 30.0]

    first, second = dry_spell(history, seed=42), dry_spell(history, seed=43)

    assert first.seed == 42
    assert second.seed == 43
    assert replace(first, seed=0) != replace(second, seed=0)


@pytest.mark.req("R-5.5-3")
def test_number_of_draws_is_the_one_asked_for() -> None:
    # with one draw the probability is 0 or 1 and the deviation is zero
    figures = dry_spell([30.0, 5.0], n=1)

    assert figures.n == 1
    assert figures.probability_of_payout in (0.0, 1.0)
    assert figures.std_dev == 0.0


def test_simulation_rejects_no_draws_and_an_empty_history() -> None:
    with pytest.raises(ValueError, match="draw"):
        dry_spell([30.0, 5.0], n=0)
    with pytest.raises(ValueError, match="historical"):
        dry_spell([])
