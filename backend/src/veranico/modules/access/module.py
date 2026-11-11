"""Wiring of `access`. Only `bootstrap.py` imports this file.

Stub of the foundation milestone: plan 07 replaces the body of `build` and keeps its signature.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import APIRouter
from google.cloud.firestore import AsyncClient

from veranico.modules.access.contracts import (
    AccessFacade,
    Admission,
    Allowance,
    ApiKeyIssued,
    ModelUsage,
    SpendRecorded,
    VisitorRef,
)
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.principal import Principal


@dataclass(frozen=True, kw_only=True)
class AccessDeps:
    settings: Settings
    clock: Clock
    firestore: AsyncClient


@dataclass(frozen=True, kw_only=True)
class AccessModule:
    facade: AccessFacade
    routers: Sequence[APIRouter]


class _StubAccessFacade:
    def visitor(self, client_ip: str, code: str | None) -> VisitorRef:
        raise NotImplementedError

    async def open_workspace(self, cookie: str | None) -> tuple[Principal, str | None]:
        raise NotImplementedError

    async def authenticate_api_key(self, bearer: str) -> Principal:
        raise NotImplementedError

    async def issue_api_key(self, principal: Principal) -> ApiKeyIssued:
        raise NotImplementedError

    async def check_rate(self, principal: Principal) -> None:
        raise NotImplementedError

    async def allowance(self, visitor: VisitorRef) -> Allowance:
        raise NotImplementedError

    async def admit_message(self, visitor: VisitorRef, new_conversation: bool) -> Admission:
        raise NotImplementedError

    async def may_spend(self) -> Admission:
        raise NotImplementedError

    async def record_spend(self, usage: ModelUsage) -> SpendRecorded:
        raise NotImplementedError

    def cost_of(self, usage: ModelUsage) -> int:
        raise NotImplementedError


def build(deps: AccessDeps) -> AccessModule:
    return AccessModule(facade=_StubAccessFacade(), routers=())
