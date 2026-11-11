"""English catalogue of the term sheet.

Keys and placeholder names are identical in `pt_br.py` (a test compares them). A string with
placeholders is filled by `translate`; the others are read with `text`. The `assumption.*` and
`warning.*` keys are the eight codes `pricing` emits, with the parameter names it gives them.
A key `<parameter>.<value>` translates a parameter that carries an enumerated value.

Every string must be encodable in WinAnsiEncoding (cp1252), the encoding of the standard PDF
fonts the renderer uses.
"""

from typing import Final

CATALOGUE: Final[dict[str, str]] = {
    "title": "Parametric rainfall cover: indicative term sheet",
    # Section titles
    "section.quote": "Quote",
    "section.cover": "Cover definition",
    "section.backtest": "Historical backtest",
    "section.simulation": "Simulation",
    "section.premium": "Indicative premium",
    "section.assumptions": "Assumptions",
    "section.warnings": "Warnings",
    "section.data": "Data and attribution",
    "section.disclaimer": "Disclaimer",
    # Row labels
    "label.quote_id": "Quote number",
    "label.created_at": "Created on",
    "label.location": "Location",
    "label.latitude": "Latitude",
    "label.longitude": "Longitude",
    "label.admin_region": "Administrative region",
    "label.dataset_id": "Dataset",
    "label.index_type": "Index type",
    "label.window": "Coverage window",
    "label.trigger": "Trigger",
    "label.exit": "Exit",
    "label.limit": "Limit",
    "label.seasons_used": "Seasons used",
    "label.seasons_excluded": "Seasons excluded",
    "label.trigger_frequency": "Trigger frequency",
    "label.burn_cost": "Burn cost",
    "label.max_payout": "Maximum payout",
    "label.max_payout_season": "Season of the maximum payout",
    "label.trend_slope": "Index trend",
    "label.trend_p_value": "Trend p-value",
    "label.method": "Method",
    "label.n": "Simulated seasons",
    "label.seed": "Seed",
    "label.expected_loss": "Expected loss",
    "label.std_dev": "Standard deviation of the payout",
    "label.probability_of_payout": "Probability of payout",
    "label.payout_1_in_10": "1-in-10 payout",
    "label.payout_1_in_100": "1-in-100 payout",
    "label.gap_to_burn_cost": "Expected loss minus burn cost",
    "label.premium": "Premium",
    "label.rate_on_line": "Rate on line",
    "label.risk_load": "Risk load",
    "label.expense_load": "Expense load",
    # Quantities with their unit
    "unit.mm": "{value} mm",
    "unit.days": "{value} days",
    "unit.mm_per_decade": "{value} mm per decade",
    "unit.days_per_decade": "{value} days per decade",
    "value.not_available": "Not available",
    # Month names
    "month.01": "January",
    "month.02": "February",
    "month.03": "March",
    "month.04": "April",
    "month.05": "May",
    "month.06": "June",
    "month.07": "July",
    "month.08": "August",
    "month.09": "September",
    "month.10": "October",
    "month.11": "November",
    "month.12": "December",
    # Enumerated parameter values
    "index_type.rainfall_below": "total rainfall below the trigger",
    "index_type.dry_spell_above": "longest dry spell above the trigger",
    "method.gamma_mle": "gamma distribution fitted by maximum likelihood",
    "method.bootstrap": "bootstrap of the historical seasons",
    "source.era5-land/cds": ("ERA5-Land daily precipitation (Copernicus Climate Change Service)"),
    "source.era5/open-meteo": (
        "ERA5 daily precipitation (Copernicus Climate Change Service, through Open-Meteo)"
    ),
    "source.synthetic": "synthetic series generated for demonstration, not real weather history",
    "direction.increasing": "upward",
    "direction.decreasing": "downward",
    # The eight codes of `pricing`
    "warning.trend_significant": (
        "The index has a statistically significant {direction} trend ({slope_per_decade} per"
        " decade, 5% level): history may understate or overstate the current risk."
    ),
    "warning.seasons_excluded": (
        "Seasons with incomplete data were excluded from the backtest ({count}): {seasons}."
    ),
    "assumption.index_type": "Index: {index_type}.",
    "assumption.window": (
        "The index is measured from {start} to {end}; a season is named after the year it"
        " starts in."
    ),
    "assumption.seasons_used": (
        "{seasons_used} seasons with complete data were used, from {first_season} to {last_season}."
    ),
    "assumption.simulation_method": ("Simulation: {method}; {n} simulated seasons; seed {seed}."),
    "assumption.loads": (
        "Premium = expected loss + {risk_load_rate} of the standard deviation +"
        " {expense_load_rate} of the expected loss."
    ),
    "assumption.data_source": "Weather data: {source}.",
    # Data notice, attribution (SPEC 4.4, ADR 0017) and disclaimer (SPEC 1)
    "notice.synthetic": (
        "This quote was priced on synthetic weather data generated for demonstration. Its"
        " figures do not describe real weather history."
    ),
    "attribution": (
        "Regional cubes use ERA5-Land and point histories use ERA5, both reanalysis products of"
        " the Copernicus Climate Change Service. Point histories are retrieved through"
        " Open-Meteo: weather data by Open-Meteo.com (https://open-meteo.com/). Contains"
        " modified Copernicus Climate Change Service information {year}. Neither the European"
        " Commission nor ECMWF is responsible for any use that may be made of the Copernicus"
        " information or data it contains. Licence: CC BY 4.0"
        " (https://creativecommons.org/licenses/by/4.0/)."
    ),
    "disclaimer": (
        "Pricing is illustrative and is not actuarial or insurance advice. Veranico is a"
        " non-commercial demonstration."
    ),
}
