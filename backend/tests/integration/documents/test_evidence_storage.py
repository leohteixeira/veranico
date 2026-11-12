"""The evidence file in Cloud Storage (SPEC 8, 14), on the emulator."""

import asyncio

import pytest

from tests.fakes.quoting import FakeQuotingFacade
from tests.unit.documents import fixtures
from tests.unit.documents.doubles import (
    CountingRenderer,
    browser,
    climate_with_dataset_of,
    documents_facade,
)
from veranico.shared.infrastructure.blobs import GcsBlobStore
from veranico.shared.kernel.ids import WorkspaceId

pytestmark = pytest.mark.integration

NETCDF = bytes(range(256)) * 8  # binary content, as a NetCDF file is


@pytest.mark.req("R-8-4", "R-8-5", "R-14-2")
async def test_the_evidence_is_stored_under_the_workspace_prefix_and_read_back_unchanged(
    blobs: GcsBlobStore, workspace_id: str
) -> None:
    quote = fixtures.rainfall_quote().model_copy(update={"workspace_id": WorkspaceId(workspace_id)})
    quoting = FakeQuotingFacade()
    quoting.seed_quote(quote)
    climate = climate_with_dataset_of(quote)
    climate.set_evidence(NETCDF)
    facade = documents_facade(
        quoting=quoting, blobs=blobs, renderer=CountingRenderer(), climate=climate
    )
    principal = browser(workspace_id)
    path = f"documents/{workspace_id}/{quote.quote_id}/evidence.nc"

    first, second = await asyncio.gather(
        facade.evidence(principal, quote.quote_id), facade.evidence(principal, quote.quote_id)
    )
    later = await facade.evidence(principal, quote.quote_id)

    assert first == second == later == NETCDF
    everything = await blobs.list("")
    assert [stored for stored in everything if workspace_id in stored] == [path]
    assert (await blobs.get(path)).data == NETCDF
    assert len(climate.evidence_requests) <= 2  # the two first calls may both ask; later ones not
