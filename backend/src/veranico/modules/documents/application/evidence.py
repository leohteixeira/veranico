"""The evidence file of a quote: the daily weather slice it was priced on, as NetCDF (SPEC 4.4).

`climate` owns the slice and the dataset side of the provenance; this module asks for the
quote's window over the seasons of its backtest and adds the quote side as attributes. The
file is stored once and served from storage afterwards. Contracts section 5 lists no audit
action for the evidence, so none is recorded.
"""

from veranico.modules.climate.contracts import ClimateFacade, EvidenceRequest
from veranico.modules.documents.application.term_sheets import document_prefix
from veranico.modules.quoting.contracts import QuoteView, QuotingFacade
from veranico.shared.infrastructure.blobs import (
    BlobNotFoundError,
    BlobPreconditionError,
    BlobStore,
)
from veranico.shared.kernel.ids import QuoteId
from veranico.shared.kernel.principal import Principal

NETCDF_CONTENT_TYPE = "application/x-netcdf"


def evidence_blob_path(quote: QuoteView) -> str:
    return f"{document_prefix(quote)}evidence.nc"


def evidence_request(quote: QuoteView) -> EvidenceRequest:
    """The slice of the quote: its window, from the first to the last season of its backtest.

    The attribute names are distinct from the provenance attributes `climate` writes itself
    (`dataset_id`, `window_start`, ...), which a caller may not overwrite.
    """
    index = quote.cover.index
    seasons = [result.season for result in quote.priced.backtest.seasons]
    return EvidenceRequest(
        dataset_id=quote.dataset_id,
        window_start=index.window.start,
        window_end=index.window.end,
        first_season=min(seasons),
        last_season=max(seasons),
        attributes={
            "quote_id": quote.quote_id,
            "quote_created_at": quote.created_at.isoformat(),
            "index_type": index.index_type,
            "index_window_start": index.window.start,
            "index_window_end": index.window.end,
            "index_trigger": str(index.trigger),
            "index_exit": str(index.exit),
        },
    )


class Evidence:
    def __init__(self, *, quoting: QuotingFacade, climate: ClimateFacade, blobs: BlobStore) -> None:
        self._quoting = quoting
        self._climate = climate
        self._blobs = blobs

    async def get(self, principal: Principal, quote_id: QuoteId) -> bytes:
        quote = await self._quoting.get_quote(principal, quote_id)  # `not_found` elsewhere
        path = evidence_blob_path(quote)
        try:
            return (await self._blobs.get(path)).data
        except BlobNotFoundError:
            pass
        data = await self._climate.export_evidence(evidence_request(quote))
        try:
            await self._blobs.put(
                path, data, content_type=NETCDF_CONTENT_TYPE, if_generation_match=0
            )
        except BlobPreconditionError:
            # A concurrent download stored the file first: every caller gets those bytes.
            return (await self._blobs.get(path)).data
        return data
