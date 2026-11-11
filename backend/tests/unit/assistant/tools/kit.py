"""A tool registry over the fakes of the six neighbour modules, for the tool tests."""

from dataclasses import dataclass

from tests.fakes import builders
from tests.fakes.carriers import FakeCarriersFacade
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.documents import FakeDocumentsFacade
from tests.fakes.pricing import FakePricingFacade
from tests.fakes.quoting import FakeQuotingFacade
from veranico.modules.assistant.application.tools.registry import ToolRegistry
from veranico.modules.climate.contracts import DatasetRef, Location
from veranico.shared.kernel.ids import WorkspaceId
from veranico.shared.kernel.principal import Principal

BROWSER = Principal(workspace_id=WorkspaceId("ws-1"), kind="browser")
OTHER = Principal(workspace_id=WorkspaceId("ws-2"), kind="browser")

SORRISO = Location(
    label="Sorriso",
    lat=builders.LAT,
    lon=builders.LON,
    h3_cell=builders.h3_cell_for(builders.LAT, builders.LON),
    admin_region="Mato Grosso",
    country_code="BR",
)

# A valid rainfall cover as the model sends it: flat fields, the limit in centavos.
INDEX_ARGUMENTS: dict[str, object] = {
    "index_type": "rainfall_below",
    "window_start": "11-15",
    "window_end": "02-15",
    "trigger": 400.0,
    "exit": 200.0,
}
LIMIT_CENTS = 30_000_000


@dataclass
class Kit:
    climate: FakeClimateFacade
    pricing: FakePricingFacade
    quoting: FakeQuotingFacade
    documents: FakeDocumentsFacade
    carriers: FakeCarriersFacade
    registry: ToolRegistry
    dataset: DatasetRef

    def price_arguments(self) -> dict[str, object]:
        return {
            "lat": SORRISO.lat,
            "lon": SORRISO.lon,
            "label": SORRISO.label,
            "admin_region": SORRISO.admin_region,
            **INDEX_ARGUMENTS,
            "limit_cents": LIMIT_CENTS,
        }

    async def priced_quote_id(self, principal: Principal = BROWSER) -> str:
        outcome = await self.registry.execute(principal, "price_cover", self.price_arguments())
        assert outcome.result is not None, outcome.error
        quote_id = outcome.result["quote_id"]
        assert isinstance(quote_id, str)
        return quote_id


def build_kit() -> Kit:
    climate = FakeClimateFacade()
    climate.add_location("Sorriso", SORRISO)
    dataset = climate.add_series(builders.daily_series())
    pricing = FakePricingFacade(climate)
    quoting = FakeQuotingFacade()
    documents = FakeDocumentsFacade(quoting)
    carriers = FakeCarriersFacade(quoting)
    registry = ToolRegistry(
        climate=climate, pricing=pricing, quoting=quoting, documents=documents, carriers=carriers
    )
    return Kit(climate, pricing, quoting, documents, carriers, registry, dataset)
