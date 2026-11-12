"""Input and output models of the tools (contracts section 8) and what a tool run returns.

Every input is validated by its Pydantic model before the facade is called; unknown fields are
rejected. The field descriptions below are what the model reads in the tool definitions.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from veranico.modules.assistant.contracts import ApprovalRequired, ToolError
from veranico.modules.documents.contracts import DocumentRef
from veranico.modules.pricing.contracts import (
    CoverDefinition,
    ExtremeSeason,
    IndexDefinition,
    IndexType,
    PricedCover,
    SimulationOptions,
    Window,
)
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import QuoteId
from veranico.shared.kernel.money import Money
from veranico.shared.kernel.principal import Principal

_DEFAULT_SIMULATION = SimulationOptions()

MonthDay = Annotated[
    str,
    Field(
        pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$",
        description="Month and day, MM-DD. Write it for the user as a date in words.",
    ),
]
Latitude = Annotated[float, Field(ge=-90, le=90, description="Latitude in decimal degrees.")]
Longitude = Annotated[float, Field(ge=-180, le=180, description="Longitude in decimal degrees.")]
LimitCents = Annotated[
    int,
    Field(
        gt=0,
        description=(
            "Cover limit in integer BRL centavos: R$ 300,000 is 30000000. Centavos are for this "
            "argument only: write the limit to the user in reais, never in centavos. "
            "Only a limit the user stated, never a placeholder: without one, ask the user "
            "instead of calling the tool."
        ),
    ),
]


class ToolInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ResolveLocationInput(ToolInput):
    query: str | None = Field(
        default=None,
        description=(
            "Place name whole, exactly as the user wrote it, for example a town. "
            "Do not trim or correct it."
        ),
    )
    lat: Latitude | None = None
    lon: Longitude | None = None

    @model_validator(mode="after")
    def _exactly_one_form(self) -> Self:
        has_point = self.lat is not None and self.lon is not None
        has_partial_point = (self.lat is None) != (self.lon is None)
        if has_partial_point or (self.query is None) == (not has_point):
            raise ValueError("give either query or both lat and lon")
        return self


class GetWeatherHistoryInput(ToolInput):
    lat: Latitude
    lon: Longitude


class IndexFields(ToolInput):
    index_type: IndexType = Field(
        description=(
            "rainfall_below: total rainfall in the window, pays when it falls below the trigger. "
            "dry_spell_above: longest run of dry days in the window, pays when it rises above."
        )
    )
    window_start: MonthDay
    window_end: MonthDay
    trigger: float = Field(
        description="Where payout starts: millimetres for rainfall_below, days for dry_spell_above."
    )
    exit: float = Field(
        description=(
            "Where the full limit is paid: below the trigger for rainfall_below, above it for "
            "dry_spell_above."
        )
    )

    def window(self) -> Window:
        return Window(start=self.window_start, end=self.window_end)

    def index(self) -> IndexDefinition:
        return IndexDefinition(
            index_type=self.index_type, window=self.window(), trigger=self.trigger, exit=self.exit
        )


class BacktestIndexInput(IndexFields):
    dataset_id: str = Field(description="The dataset_id returned by get_weather_history.")
    limit_cents: LimitCents

    def cover(self) -> CoverDefinition:
        return CoverDefinition(index=self.index(), limit=Money(amount_cents=self.limit_cents))


class PriceCoverInput(IndexFields):
    lat: Latitude
    lon: Longitude
    label: str | None = Field(default=None, description="The label returned by resolve_location.")
    admin_region: str | None = Field(
        default=None, description="The admin_region returned by resolve_location."
    )
    limit_cents: LimitCents
    n: int = Field(
        default=_DEFAULT_SIMULATION.n, description="Simulated seasons. Keep the default."
    )
    seed: int = Field(
        default=_DEFAULT_SIMULATION.seed, description="Random seed. Keep the default."
    )

    def cover(self) -> CoverDefinition:
        return CoverDefinition(index=self.index(), limit=Money(amount_cents=self.limit_cents))


class FindExtremeSeasonsInput(ToolInput):
    dataset_id: str = Field(description="The dataset_id returned by get_weather_history.")
    index_type: IndexType
    window_start: MonthDay
    window_end: MonthDay
    top_n: int = Field(default=5, ge=1, le=10, description="How many seasons, worst first.")


class DraftTermSheetInput(ToolInput):
    quote_id: str = Field(description="The quote_id returned by price_cover.")


class RequestSubmissionInput(ToolInput):
    quote_id: str = Field(description="The quote_id returned by price_cover.")
    carrier_id: str = Field(description="One of the carrier ids of the directory.")


class PriceCoverOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    quote_id: QuoteId
    priced: PricedCover


class ExtremeSeasonsOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    seasons: list[ExtremeSeason]


class TermSheetOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents: list[DocumentRef]


@dataclass(frozen=True, slots=True)
class ToolSuccess:
    """What a tool handler returns: its output model, the summary and an approval, if any."""

    output: BaseModel
    summary: Coded
    approval: ApprovalRequired | None = None


@dataclass(frozen=True, slots=True)
class Tool[InputT: ToolInput]:
    name: str
    description: str
    input_model: type[InputT]
    handler: Callable[[Principal, InputT], Awaitable[ToolSuccess]]
    # Replaces the schema generated from `input_model` when a tool narrows it at build time.
    input_schema: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """What the registry hands to the loop: a result or an error, never an exception."""

    summary: Coded
    result: dict[str, object] | None = None  # the output model, serialised
    error: ToolError | None = None
    approval: ApprovalRequired | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
