"""Wiring of `documents`. Only `bootstrap.py` imports this file.

Stub of the foundation milestone: plan 05 replaces the body of `build` and keeps its signature.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import APIRouter

from veranico.modules.access.contracts import AccessFacade
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.documents.contracts import DocumentRef, DocumentsFacade
from veranico.modules.quoting.contracts import Actor, QuotingFacade
from veranico.shared.infrastructure.blobs import BlobStore
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.ids import Locale, QuoteId
from veranico.shared.kernel.principal import Principal


@dataclass(frozen=True, kw_only=True)
class DocumentsDeps:
    settings: Settings
    clock: Clock
    blobs: BlobStore
    quoting: QuotingFacade
    climate: ClimateFacade
    access: AccessFacade


@dataclass(frozen=True, kw_only=True)
class DocumentsModule:
    facade: DocumentsFacade
    routers: Sequence[APIRouter]


class _StubDocumentsFacade:
    async def render_term_sheets(
        self, principal: Principal, quote_id: QuoteId, actor: Actor
    ) -> list[DocumentRef]:
        raise NotImplementedError

    async def term_sheet(self, principal: Principal, quote_id: QuoteId, locale: Locale) -> bytes:
        raise NotImplementedError

    async def evidence(self, principal: Principal, quote_id: QuoteId) -> bytes:
        raise NotImplementedError


def build(deps: DocumentsDeps) -> DocumentsModule:
    return DocumentsModule(facade=_StubDocumentsFacade(), routers=())
