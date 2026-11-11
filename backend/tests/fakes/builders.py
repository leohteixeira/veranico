"""Small seeded builders of contract objects, for the fakes and for other plans' tests.

Everything here is deterministic: the same arguments give equal objects. Built weather
data says what it is (`DatasetRef.source = "synthetic"`, `Region.synthetic = True`).

Money is built in integer centavos from the limit. The figures are canned, not computed by
the pricing rules: a test that needs real pricing uses the real `pricing` module.

The eight pricing codes and the parameters they carry here:

| Code                           | Parameters                                    |
|--------------------------------|-----------------------------------------------|
| `warning.trend_significant`    | `slope_per_decade`, `direction`               |
| `warning.seasons_excluded`     | `count`, `seasons`                            |
| `assumption.index_type`        | `index_type`                                  |
| `assumption.window`            | `start`, `end`                                |
| `assumption.seasons_used`      | `seasons_used`, `first_season`, `last_season` |
| `assumption.simulation_method` | `method`, `n`, `seed`                         |
| `assumption.loads`             | `risk_load_rate`, `expense_load_rate`         |
| `assumption.data_source`       | `source`                                      |
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

import h3
import numpy as np

from veranico.modules.climate.contracts import (
    DailySeries,
    DatasetRef,
    GridPoint,
    Region,
    RegionCube,
)
from veranico.modules.pricing.contracts import (
    BacktestResult,
    CoverDefinition,
    IndexDefinition,
    IndexType,
    Premium,
    PricedCover,
    SeasonResult,
    SimulationOptions,
    SimulationResult,
    Trend,
    Window,
)
from veranico.modules.quoting.contracts import (
    AuditEntry,
    CarrierInfo,
    QuoteLocation,
    QuoteStatus,
    QuoteView,
    Submission,
)
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import (
    DatasetId,
    QuoteId,
    WorkspaceId,
    cube_dataset_id,
    point_dataset_id,
)
from veranico.shared.kernel.money import Money

Source = Literal["era5-land/cds", "era5-land/open-meteo", "synthetic"]

LAT = -12.55  # near Sorriso, Mato Grosso
LON = -55.72
FIRST_YEAR = 1950
LAST_YEAR = 2024
SEASONS = 30
CREATED_AT = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
H3_RESOLUTION = 6
RISK_LOAD_RATE = "0.300000"
EXPENSE_LOAD_RATE = "0.150000"

CARRIERS: tuple[CarrierInfo, ...] = (
    CarrierInfo(carrier_id="carrier-1", name="Fake Carrier One"),
    CarrierInfo(carrier_id="carrier-2", name="Fake Carrier Two"),
)


def h3_cell_for(lat: float, lon: float) -> str:
    """The resolution 6 cell of the coordinates: computed, with no lookup."""
    return str(h3.latlng_to_cell(lat, lon, H3_RESOLUTION))


def point_dataset_for(lat: float, lon: float) -> DatasetId:
    return point_dataset_id(h3_cell_for(lat, lon))


def rate(numerator: int, denominator: int) -> str:
    """A non-negative `Rate` (six decimal places) by integer division."""
    millionths = numerator * 1_000_000 // denominator
    return f"{millionths // 1_000_000}.{millionths % 1_000_000:06d}"


def _dates(first_year: int, last_year: int) -> np.ndarray:
    return np.arange(f"{first_year}-01-01", f"{last_year + 1}-01-01", dtype="datetime64[D]")


def _rain(generator: np.random.Generator, shape: tuple[int, ...]) -> np.ndarray:
    """Daily rain in millimetres: dry on most days, gamma-distributed on the others."""
    wet = generator.random(shape) < 0.4
    return np.where(wet, generator.gamma(0.8, 12.0, shape), 0.0).astype(np.float64)


def daily_series(
    *,
    seed: int = 0,
    lat: float = LAT,
    lon: float = LON,
    first_year: int = FIRST_YEAR,
    last_year: int = LAST_YEAR,
    source: Source = "synthetic",
) -> DailySeries:
    """A gap-free daily series for a point, carrying only `precipitation_mm`."""
    dates = _dates(first_year, last_year)
    dataset = DatasetRef(
        dataset_id=point_dataset_for(lat, lon),
        kind="point",
        region_id=None,
        grid_point=GridPoint(lat=lat, lon=lon),
        first_year=first_year,
        last_year=last_year,
        days=len(dates),
        missing_days=0,
        source=source,
    )
    rain = _rain(np.random.default_rng(seed), (len(dates),))
    return DailySeries(dataset=dataset, dates=dates, precipitation_mm=rain)


def region(
    region_id: str = "sorriso",
    *,
    nx: int = 2,
    ny: int = 2,
    north: float = -12.0,
    west: float = -56.0,
    step_deg: float = 0.1,
) -> Region:
    return Region(
        region_id=region_id,
        name=region_id.replace("-", " ").title(),
        crop="soy",
        north=north,
        south=north - ny * step_deg,
        west=west,
        east=west + nx * step_deg,
        step_deg=step_deg,
        nx=nx,
        ny=ny,
        synthetic=True,
    )


def region_cube(
    *,
    seed: int = 0,
    region_id: str = "sorriso",
    nx: int = 2,
    ny: int = 2,
    first_year: int = FIRST_YEAR,
    last_year: int = LAST_YEAR,
) -> RegionCube:
    """A small synthetic cube, shape (time, ny, nx); row 0 is the northern edge."""
    dates = _dates(first_year, last_year)
    rain = _rain(np.random.default_rng(seed), (len(dates), ny, nx))
    return RegionCube(region=region(region_id, nx=nx, ny=ny), dates=dates, precipitation_mm=rain)


def cube_cell_ref(cube: RegionCube, row: int, col: int) -> DatasetRef:
    """The `DatasetRef` of one cell of a cube; the grid point is the cell centre."""
    area = cube.region
    years = cube.dates.astype("datetime64[Y]").astype(int) + 1970
    return DatasetRef(
        dataset_id=cube_dataset_id(area.region_id, row, col),
        kind="cube",
        region_id=area.region_id,
        grid_point=GridPoint(
            lat=area.north - (row + 0.5) * area.step_deg,
            lon=area.west + (col + 0.5) * area.step_deg,
        ),
        first_year=int(years[0]),
        last_year=int(years[-1]),
        days=len(cube.dates),
        missing_days=0,
        source="synthetic",
    )


def cover(
    *,
    index_type: IndexType = "rainfall_below",
    limit_cents: int = 10_000_000,
    start: str = "10-01",
    end: str = "03-31",
    trigger: float | None = None,
    exit: float | None = None,
) -> CoverDefinition:
    """A valid cover: the exit is on the paying side of the trigger for either index type."""
    below = index_type == "rainfall_below"
    return CoverDefinition(
        index=IndexDefinition(
            index_type=index_type,
            window=Window(start=start, end=end),
            trigger=trigger if trigger is not None else (600.0 if below else 20.0),
            exit=exit if exit is not None else (300.0 if below else 40.0),
        ),
        limit=Money(amount_cents=limit_cents),
    )


def season_results(
    index: IndexDefinition,
    limit_cents: int | None,
    *,
    first_season: int = FIRST_YEAR,
    seasons: int = SEASONS,
    seasons_excluded: Sequence[int] = (),
) -> list[SeasonResult]:
    """Canned seasons: every fifth one pays a quarter of the limit, the others pay nothing."""
    below = index.index_type == "rainfall_below"
    paying_value = (index.trigger + index.exit) / 2
    results = []
    for position in range(seasons):
        season = first_season + position
        if season in seasons_excluded:
            continue
        pays = position % 5 == 0
        step = 10.0 * (1 + position % 3)
        value = paying_value if pays else index.trigger + (step if below else -step / 10)
        payout = None
        if limit_cents is not None:
            payout = Money(amount_cents=limit_cents // 4 if pays else 0)
        results.append(
            SeasonResult(season=season, index_value=float(f"{value:.1f}"), payout=payout)
        )
    return results


def backtest_result(
    cover_definition: CoverDefinition | None = None,
    *,
    dataset_id: DatasetId | None = None,
    first_season: int = FIRST_YEAR,
    seasons: int = SEASONS,
    seasons_excluded: Sequence[int] = (),
    trend_significant: bool = False,
) -> BacktestResult:
    definition = cover_definition or cover()
    limit_cents = definition.limit.amount_cents
    results = season_results(
        definition.index,
        limit_cents,
        first_season=first_season,
        seasons=seasons,
        seasons_excluded=seasons_excluded,
    )
    paying = [result for result in results if result.payout and result.payout.amount_cents > 0]
    total_cents = len(paying) * (limit_cents // 4)
    warnings = []
    if trend_significant:
        warnings.append(
            Coded(
                code="warning.trend_significant",
                params={"slope_per_decade": -12.5, "direction": "decreasing"},
            )
        )
    if seasons_excluded:
        excluded = ", ".join(str(season) for season in sorted(seasons_excluded))
        warnings.append(
            Coded(
                code="warning.seasons_excluded",
                params={"count": len(seasons_excluded), "seasons": excluded},
            )
        )
    return BacktestResult(
        dataset_id=dataset_id or point_dataset_for(LAT, LON),
        cover=definition,
        seasons=results,
        seasons_used=len(results),
        seasons_excluded=sorted(seasons_excluded),
        trigger_frequency=rate(len(paying), len(results)),
        burn_cost=Money(amount_cents=total_cents // len(results)),
        max_payout=Money(amount_cents=limit_cents // 4 if paying else 0),
        max_payout_season=paying[0].season if paying else None,
        trend=Trend(
            slope_per_decade=-12.5 if trend_significant else -1.5,
            p_value="0.010000" if trend_significant else "0.400000",
            significant=trend_significant,
        ),
        warnings=warnings,
    )


def priced_cover(
    cover_definition: CoverDefinition | None = None,
    *,
    dataset_id: DatasetId | None = None,
    options: SimulationOptions | None = None,
    first_season: int = FIRST_YEAR,
    seasons: int = SEASONS,
    seasons_excluded: Sequence[int] = (),
    trend_significant: bool = False,
    source: Source = "synthetic",
    gap_to_burn_cost_cents: int | None = None,
) -> PricedCover:
    """A priced cover with canned figures in integer centavos, derived from the limit.

    `gap_to_burn_cost_cents` sets the difference between the simulated expected loss and
    the historical burn cost; it may be negative. The default is 0.5% of the limit.
    """
    simulation_options = options or SimulationOptions()
    backtest = backtest_result(
        cover_definition,
        dataset_id=dataset_id,
        first_season=first_season,
        seasons=seasons,
        seasons_excluded=seasons_excluded,
        trend_significant=trend_significant,
    )
    index = backtest.cover.index
    limit_cents = backtest.cover.limit.amount_cents
    gap_cents = limit_cents // 200 if gap_to_burn_cost_cents is None else gap_to_burn_cost_cents
    expected_cents = backtest.burn_cost.amount_cents + gap_cents
    std_dev_cents = limit_cents // 10
    # Canned loads: 30% of the standard deviation on top, then a 15% expense share.
    premium_cents = (expected_cents + std_dev_cents * 3 // 10) * 100 // 85
    paying = [season for season in backtest.seasons if season.payout and season.payout.amount_cents]
    method: Literal["gamma_mle", "bootstrap"] = (
        "gamma_mle" if index.index_type == "rainfall_below" else "bootstrap"
    )
    return PricedCover(
        backtest=backtest,
        simulation=SimulationResult(
            method=method,
            n=simulation_options.n,
            seed=simulation_options.seed,
            expected_loss=Money(amount_cents=expected_cents),
            std_dev=Money(amount_cents=std_dev_cents),
            probability_of_payout=rate(len(paying), backtest.seasons_used),
            payout_1_in_10=Money(amount_cents=limit_cents // 4),
            payout_1_in_100=Money(amount_cents=limit_cents // 2),
            gap_to_burn_cost=Money(amount_cents=gap_cents),
        ),
        premium=Premium(
            premium=Money(amount_cents=premium_cents),
            rate_on_line=rate(premium_cents, limit_cents),
            risk_load=RISK_LOAD_RATE,
            expense_load=EXPENSE_LOAD_RATE,
        ),
        assumptions=[
            Coded(code="assumption.index_type", params={"index_type": index.index_type}),
            Coded(
                code="assumption.window",
                params={"start": index.window.start, "end": index.window.end},
            ),
            Coded(
                code="assumption.seasons_used",
                params={
                    "seasons_used": backtest.seasons_used,
                    "first_season": backtest.seasons[0].season,
                    "last_season": backtest.seasons[-1].season,
                },
            ),
            Coded(
                code="assumption.simulation_method",
                params={
                    "method": method,
                    "n": simulation_options.n,
                    "seed": simulation_options.seed,
                },
            ),
            Coded(
                code="assumption.loads",
                params={"risk_load_rate": RISK_LOAD_RATE, "expense_load_rate": EXPENSE_LOAD_RATE},
            ),
            Coded(code="assumption.data_source", params={"source": source}),
        ],
    )


def quote_location(lat: float = LAT, lon: float = LON, label: str | None = None) -> QuoteLocation:
    return QuoteLocation(
        label=label if label is not None else f"{lat:.4f}, {lon:.4f}",
        lat=lat,
        lon=lon,
        h3_cell=h3_cell_for(lat, lon),
        admin_region=None,
    )


def quote_view(
    *,
    quote_id: str = "Q-000001",
    workspace_id: str = "ws-1",
    status: QuoteStatus = "draft",
    cover_definition: CoverDefinition | None = None,
    priced: PricedCover | None = None,
    lat: float = LAT,
    lon: float = LON,
    label: str | None = None,
    submission: Submission | None = None,
    audit: Sequence[AuditEntry] | None = None,
    created_at: datetime = CREATED_AT,
) -> QuoteView:
    """A stored quote. The dataset id and the cell come from the coordinates."""
    dataset_id = point_dataset_for(lat, lon)
    priced_result = priced or priced_cover(cover_definition, dataset_id=dataset_id)
    entries = (
        list(audit)
        if audit is not None
        else [
            AuditEntry(at=created_at, actor="api_client", action=Coded(code="audit.quote_created"))
        ]
    )
    return QuoteView(
        quote_id=QuoteId(quote_id),
        workspace_id=WorkspaceId(workspace_id),
        created_at=created_at,
        status=status,
        location=quote_location(lat, lon, label),
        dataset_id=dataset_id,
        cover=priced_result.backtest.cover,
        priced=priced_result,
        submission=submission,
        audit=entries,
    )
