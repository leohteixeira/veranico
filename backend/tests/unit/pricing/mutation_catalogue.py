"""Hand-written mutants of `pricing/domain` (SPEC 16.4), read by `scripts/mutation_proof.py`.

Each entry names one rule and breaks it with one textual change: `find` must occur exactly
once in `file` (a path under `pricing/domain`), and is replaced by `replace`. The proof
applies each mutant to a temporary copy of the sources and expects the pricing unit tests
to fail. A mutant that survives is fixed by adding the missing hand-computed test, never
by deleting the entry.

This file is data, not a test module: pytest does not collect it.
"""

from typing import NamedTuple


class Mutant(NamedTuple):
    name: str
    file: str  # relative to pricing/domain
    find: str
    replace: str
    rule: str


CATALOGUE: tuple[Mutant, ...] = (
    # --- payout (SPEC 5.3) ---------------------------------------------------------------
    Mutant(
        name="payout_rainfall_direction_flipped",
        file="payout.py",
        find="raw = (trigger - values) / (trigger - exit)",
        replace="raw = (values - trigger) / (trigger - exit)",
        rule="5.3 rainfall_below pays below the trigger",
    ),
    Mutant(
        name="payout_dry_spell_direction_flipped",
        file="payout.py",
        find="raw = (values - trigger) / (exit - trigger)",
        replace="raw = (trigger - values) / (exit - trigger)",
        rule="5.3 dry_spell_above pays above the trigger",
    ),
    Mutant(
        name="payout_upper_clamp_removed",
        file="payout.py",
        find="return np.minimum(floored, 1.0)",
        replace="return floored",
        rule="5.3 capped at the limit",
    ),
    Mutant(
        name="payout_lower_clamp_removed",
        file="payout.py",
        find="floored = np.maximum(raw, 0.0)",
        replace="floored = raw",
        rule="5.3 no negative payout",
    ),
    Mutant(
        name="payout_step_instead_of_linear",
        file="payout.py",
        find="floored = np.maximum(raw, 0.0)",
        replace="floored = np.where(raw > 0, 1.0, 0.0)",
        rule="5.3 linear between trigger and exit",
    ),
    Mutant(
        name="payout_amount_ignores_limit",
        file="payout.py",
        find="return limit_cents * payout_fraction(index_type, index_values, trigger, exit)",
        replace="return payout_fraction(index_type, index_values, trigger, exit)",
        rule="5.3 payout is the limit times the fraction",
    ),
    # --- windows and seasons (SPEC 5.1) --------------------------------------------------
    Mutant(
        name="window_end_exclusive",
        file="seasons.py",
        find="stops.append(stop)",
        replace="stops.append(stop - 1)",
        rule="5.1 the last day of the window is included",
    ),
    Mutant(
        name="window_start_exclusive",
        file="seasons.py",
        find="starts.append(start)",
        replace="starts.append(start + 1)",
        rule="5.1 the first day of the window is included",
    ),
    Mutant(
        name="season_labelled_by_end_year",
        file="seasons.py",
        find="label = year",
        replace="label = end_year",
        rule="5.1 a season is labelled by its start year",
    ),
    Mutant(
        name="crossing_window_not_wrapped",
        file="seasons.py",
        find="end_year = year + 1 if window.crosses_year else year",
        replace="end_year = year",
        rule="5.1 a window may cross the year boundary",
    ),
    Mutant(
        name="incomplete_season_included",
        file="seasons.py",
        find="usable = stop - start == window_days",
        replace="usable = stop > start",
        rule="5.1 seasons with incomplete data are excluded",
    ),
    Mutant(
        name="missing_day_season_included",
        file="seasons.py",
        find="usable = not bool(missing[start:stop].any())",
        replace="usable = True",
        rule="5.1 a missing day excludes its season",
    ),
    # --- index values (SPEC 5.2) ---------------------------------------------------------
    Mutant(
        name="dry_day_threshold_inclusive",
        file="index.py",
        find="dry = window_mm < DRY_DAY_MM",
        replace="dry = window_mm <= DRY_DAY_MM",
        rule="5.2 a dry day is under 1 mm",
    ),
    Mutant(
        name="dry_spell_total_dry_days",
        file="index.py",
        find="longest = np.maximum(longest, run)",
        replace="longest = longest + dry_today",
        rule="5.2 the longest run, not the number of dry days",
    ),
    Mutant(
        name="rainfall_mean_instead_of_total",
        file="index.py",
        find="window_mm.sum(axis=0)",
        replace="window_mm.mean(axis=0)",
        rule="5.2 total precipitation in the window",
    ),
    # --- backtest (SPEC 5.4) -------------------------------------------------------------
    Mutant(
        name="trigger_boundary_pays",
        file="backtest.py",
        find="np.asarray(beyond > 0, dtype=np.bool_)",
        replace="np.asarray(beyond >= 0, dtype=np.bool_)",
        rule="5.2, 5.4 paying means strictly beyond the trigger",
    ),
    Mutant(
        name="burn_cost_median",
        file="backtest.py",
        find="burn_cost=float(payouts.mean()),",
        replace="burn_cost=float(np.median(payouts)),",
        rule="5.4 burn cost is the average payout",
    ),
    Mutant(
        name="frequency_counts_excluded_seasons",
        file="backtest.py",
        find="trigger_frequency=seasons_paying / seasons_used,",
        replace="trigger_frequency=seasons_paying / (seasons_used + len(season_index.excluded)),",
        rule="5.4 frequency over the usable seasons only",
    ),
    Mutant(
        name="trend_slope_per_year",
        file="backtest.py",
        find="slope_per_decade=float(fit.slope) * YEARS_PER_DECADE,",
        replace="slope_per_decade=float(fit.slope),",
        rule="5.4 slope per decade",
    ),
    Mutant(
        name="trend_significance_at_ten_percent",
        file="backtest.py",
        find="SIGNIFICANCE_LEVEL = 0.05",
        replace="SIGNIFICANCE_LEVEL = 0.10",
        rule="5.4 significant at 5%",
    ),
    # --- boundary rounding (SPEC 5.7) ----------------------------------------------------
    Mutant(
        name="rounding_half_up",
        file="rounding.py",
        find="return round(x)",
        replace="return math.floor(x + 0.5)",
        rule="5.7 half to even",
    ),
    Mutant(
        name="rounding_truncates",
        file="rounding.py",
        find="return round(x)",
        replace="return int(x)",
        rule="5.7 rounded, not truncated",
    ),
    Mutant(
        name="rate_five_decimals",
        file="rounding.py",
        find="RATE_DECIMALS = 6",
        replace="RATE_DECIMALS = 5",
        rule="5.7 six decimal places",
    ),
    Mutant(
        name="gap_sign_flipped",
        file="rounding.py",
        find="return minuend_cents - subtrahend_cents",
        replace="return subtrahend_cents - minuend_cents",
        rule="5.5 gap is simulated minus historical",
    ),
    # --- premium (SPEC 5.6) --------------------------------------------------------------
    Mutant(
        name="premium_risk_load_dropped",
        file="premium.py",
        find="amount = expected_loss + risk_load * std_dev + expense_load * expected_loss",
        replace="amount = expected_loss + expense_load * expected_loss",
        rule="5.6 risk load on the standard deviation",
    ),
    Mutant(
        name="premium_expense_load_on_std_dev",
        file="premium.py",
        find="amount = expected_loss + risk_load * std_dev + expense_load * expected_loss",
        replace="amount = expected_loss + risk_load * std_dev + expense_load * std_dev",
        rule="5.6 expense load on the expected loss",
    ),
    Mutant(
        name="rate_on_line_uses_expected_loss",
        file="premium.py",
        find="rate_on_line=amount / limit_cents",
        replace="rate_on_line=expected_loss / limit_cents",
        rule="5.6 rate on line is premium over limit",
    ),
    # --- simulation (SPEC 5.5) -----------------------------------------------------------
    Mutant(
        name="simulation_seed_ignored",
        file="simulation.py",
        find="generator = np.random.default_rng(seed)",
        replace="generator = np.random.default_rng()",
        rule="5.5 deterministic for a fixed seed",
    ),
    Mutant(
        name="one_in_100_uses_90th_percentile",
        file="simulation.py",
        find="ONE_IN_100_PERCENTILE = 99.0",
        replace="ONE_IN_100_PERCENTILE = 90.0",
        rule="5.5 1-in-100 payout",
    ),
    # --- extreme seasons (SPEC 9.4, contracts section 4) ---------------------------------
    Mutant(
        name="return_period_n_over_rank",
        file="extremes.py",
        find="return_period_years=(n + 1) / rank,",
        replace="return_period_years=n / rank,",
        rule="contracts 4: return period (n + 1) / rank",
    ),
    Mutant(
        name="extremes_best_first",
        file="extremes.py",
        find="key=lambda item: (item[1] if lowest_is_worst else -item[1], item[0]),",
        replace="key=lambda item: (-item[1] if lowest_is_worst else item[1], item[0]),",
        rule="9.4 worst seasons first",
    ),
)
