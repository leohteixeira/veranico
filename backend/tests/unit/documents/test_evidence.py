"""`evidence`: the NetCDF slice of the quote, asked from `climate` once and stored (SPEC 8)."""

from pathlib import Path

import pytest

from tests.fakes.climate import FakeClimateFacade
from tests.fakes.quoting import FakeQuotingFacade
from tests.unit.documents import fixtures
from tests.unit.documents.doubles import (
    CountingRenderer,
    api_key,
    browser,
    climate_with_dataset_of,
    documents_facade,
)
from veranico.modules.climate.contracts import EvidenceRequest
from veranico.modules.documents.application.evidence import evidence_request
from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.quoting.contracts import QuoteView
from veranico.shared.infrastructure.blobs import LocalBlobStore
from veranico.shared.kernel.errors import (
    DatasetNotFoundError,
    NotFoundError,
    WeatherSourceUnavailableError,
)
from veranico.shared.kernel.ids import DatasetId, QuoteId

NETCDF = b"\x89HDF\r\n\x1a\nfake evidence of Q-7K2M9P"
PATH = "documents/ws-rain/Q-7K2M9P/evidence.nc"
# The provenance attributes `climate` writes itself and refuses from a caller
# (`climate/application/export_evidence.py`).
RESERVED_BY_CLIMATE = {
    "dataset_id",
    "grid_point_lat",
    "grid_point_lon",
    "source",
    "request",
    "manifest_checksum",
    "window_start",
    "window_end",
    "first_season",
    "last_season",
}


class Scene:
    def __init__(self, root: Path) -> None:
        self.quote: QuoteView = fixtures.rainfall_quote()  # workspace `ws-rain`
        self.quoting = FakeQuotingFacade()
        self.quoting.seed_quote(self.quote)
        self.climate: FakeClimateFacade = climate_with_dataset_of(self.quote)
        self.climate.set_evidence(NETCDF)
        self.blobs = LocalBlobStore(root)
        self.facade: DocumentsFacade = documents_facade(
            quoting=self.quoting,
            blobs=self.blobs,
            renderer=CountingRenderer(),
            climate=self.climate,
        )


@pytest.fixture
def scene(tmp_path: Path) -> Scene:
    return Scene(tmp_path)


@pytest.mark.req("R-8-4")
async def test_the_request_is_the_window_of_the_quote_over_the_seasons_of_its_backtest(
    scene: Scene,
) -> None:
    await scene.facade.evidence(browser("ws-rain"), scene.quote.quote_id)

    assert scene.climate.evidence_requests == [
        EvidenceRequest(
            dataset_id=DatasetId("point:86a8100c7ffffff"),
            window_start="11-15",
            window_end="02-15",
            first_season=1950,
            last_season=2024,
            attributes={
                "quote_id": "Q-7K2M9P",
                "quote_created_at": "2026-11-10T14:30:00+00:00",
                "index_type": "rainfall_below",
                "index_window_start": "11-15",
                "index_window_end": "02-15",
                "index_trigger": "350.0",
                "index_exit": "142.5",
            },
        )
    ]


@pytest.mark.req("R-8-4")
def test_the_seasons_are_the_smallest_and_the_largest_of_the_backtest_in_any_order() -> None:
    quote = fixtures.dry_spell_quote()
    backtest = quote.priced.backtest
    kept = [result for result in reversed(backtest.seasons) if 1961 <= result.season <= 2019]
    shuffled = backtest.model_copy(update={"seasons": [kept[5], *kept[:5], *kept[6:]]})
    priced = quote.priced.model_copy(update={"backtest": shuffled})

    request = evidence_request(quote.model_copy(update={"priced": priced}))

    assert (request.first_season, request.last_season) == (1961, 2019)
    assert request.dataset_id == "cube:sorriso:5:2"
    assert request.attributes["index_type"] == "dry_spell_above"
    assert request.attributes["index_trigger"] == "12.0"
    assert request.attributes["index_exit"] == "25.0"
    assert request.attributes["quote_created_at"] == "2027-01-02T09:00:00+00:00"


@pytest.mark.req("R-8-4")
def test_no_attribute_collides_with_the_provenance_climate_writes() -> None:
    attributes = evidence_request(fixtures.rainfall_quote()).attributes

    assert set(attributes) == {
        "quote_id",
        "quote_created_at",
        "index_type",
        "index_window_start",
        "index_window_end",
        "index_trigger",
        "index_exit",
    }
    assert set(attributes) & RESERVED_BY_CLIMATE == set()
    assert all(isinstance(value, str) for value in attributes.values())


@pytest.mark.req("R-8-4", "R-8-5", "R-14-2", "R-11.1-4")
async def test_the_bytes_of_climate_are_returned_and_stored_at_the_evidence_path(
    scene: Scene,
) -> None:
    data = await scene.facade.evidence(browser("ws-rain"), scene.quote.quote_id)

    assert data == NETCDF
    assert await scene.blobs.list("") == [PATH]
    assert (await scene.blobs.get(PATH)).data == NETCDF


@pytest.mark.req("R-8-5")
async def test_a_second_call_returns_the_stored_bytes_without_calling_climate(
    scene: Scene,
) -> None:
    first = await scene.facade.evidence(browser("ws-rain"), scene.quote.quote_id)
    scene.climate.set_evidence(b"another export would differ")

    second = await scene.facade.evidence(api_key("ws-rain"), scene.quote.quote_id)

    assert second == first == NETCDF
    assert len(scene.climate.evidence_requests) == 1
    assert (await scene.blobs.get(PATH)).generation == 1


async def test_the_evidence_adds_no_audit_entry(scene: Scene) -> None:
    before = scene.quoting.audit_actions(scene.quote.quote_id)

    await scene.facade.evidence(browser("ws-rain"), scene.quote.quote_id)

    assert scene.quoting.audit_actions(scene.quote.quote_id) == before
    assert [name for name, _ in scene.quoting.calls] == ["get_quote"]


@pytest.mark.req("R-10.1-2")
async def test_a_quote_of_another_workspace_is_not_found_and_nothing_is_called(
    scene: Scene,
) -> None:
    await scene.facade.evidence(browser("ws-rain"), scene.quote.quote_id)  # stored for its owner

    for principal in (browser("ws-other"), api_key("ws-other")):
        with pytest.raises(NotFoundError):
            await scene.facade.evidence(principal, scene.quote.quote_id)
    with pytest.raises(NotFoundError):
        await scene.facade.evidence(browser("ws-rain"), QuoteId("Q-000000"))

    assert len(scene.climate.calls) == 1
    assert await scene.blobs.list("") == [PATH]


@pytest.mark.parametrize("error", [DatasetNotFoundError, WeatherSourceUnavailableError])
async def test_an_error_of_climate_propagates_and_stores_nothing(
    scene: Scene, error: type[Exception]
) -> None:
    scene.climate.fail_with(error())  # type: ignore[arg-type]  # both are domain errors

    with pytest.raises(error):
        await scene.facade.evidence(browser("ws-rain"), scene.quote.quote_id)

    assert await scene.blobs.list("") == []
    # Once the source answers again, the same call succeeds.
    scene.climate.fail_with(None)
    assert await scene.facade.evidence(browser("ws-rain"), scene.quote.quote_id) == NETCDF
