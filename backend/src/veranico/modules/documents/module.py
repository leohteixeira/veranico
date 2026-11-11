"""Wiring of `documents`. Only `bootstrap.py` imports this file.

`settings`, `clock` and `access` are part of the dependencies `bootstrap.py` passes and are
not used: nothing here is configurable, no clock is read (a stored document never depends on
when it was rendered) and the principal arrives from `http_auth`.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import APIRouter

from veranico.modules.access.contracts import AccessFacade
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.documents.application.evidence import Evidence
from veranico.modules.documents.application.facade import DocumentsService
from veranico.modules.documents.application.term_sheets import TermSheets
from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.documents.http.router import build_router
from veranico.modules.documents.infrastructure.pdf_renderer import ReportlabTermSheetRenderer
from veranico.modules.quoting.contracts import QuotingFacade
from veranico.shared.infrastructure.blobs import BlobStore
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.clock import Clock


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


def build(deps: DocumentsDeps) -> DocumentsModule:
    facade = DocumentsService(
        term_sheets=TermSheets(
            quoting=deps.quoting, blobs=deps.blobs, renderer=ReportlabTermSheetRenderer()
        ),
        evidence=Evidence(quoting=deps.quoting, climate=deps.climate, blobs=deps.blobs),
    )
    return DocumentsModule(facade=facade, routers=(build_router(facade),))
