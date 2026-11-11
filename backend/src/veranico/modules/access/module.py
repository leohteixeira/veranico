"""Wiring of `access`. Only `bootstrap.py` imports this file."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from fastapi import APIRouter
from google.cloud.firestore import AsyncClient

from veranico.modules.access.application.allowances import Allowances
from veranico.modules.access.application.api_keys import ApiKeys
from veranico.modules.access.application.facade import Access
from veranico.modules.access.application.rate_limit import RateLimiter
from veranico.modules.access.application.spend import Spend
from veranico.modules.access.application.workspaces import Workspaces
from veranico.modules.access.contracts import AccessFacade
from veranico.modules.access.domain.allowance import Limits
from veranico.modules.access.domain.cost import TokenPrices, prices_for
from veranico.modules.access.http.router import build_router
from veranico.modules.access.infrastructure.firestore_allowances import FirestoreAllowanceStore
from veranico.modules.access.infrastructure.firestore_api_keys import FirestoreApiKeyStore
from veranico.modules.access.infrastructure.firestore_spend import FirestoreSpendStore
from veranico.modules.access.infrastructure.firestore_workspaces import FirestoreWorkspaceStore
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.clock import Clock


@dataclass(frozen=True, kw_only=True)
class AccessDeps:
    settings: Settings
    clock: Clock
    firestore: AsyncClient


@dataclass(frozen=True, kw_only=True)
class AccessModule:
    facade: AccessFacade
    routers: Sequence[APIRouter]


def build(deps: AccessDeps) -> AccessModule:
    settings, clock, firestore = deps.settings, deps.clock, deps.firestore
    access = settings.access
    # The settings require both secrets on the API role, the only role that builds `access`.
    if settings.cookie_signing_secret is None or access.ip_hash_salt is None:
        raise ValueError("access needs the cookie signing secret and the IP hash salt")
    prices = {
        model: TokenPrices(
            input=price.input,
            output=price.output,
            cache_read=price.cache_read,
            cache_write=price.cache_write,
        )
        for model, price in access.model_prices.items()
    }
    # A missing price is a configuration error, raised here and never charged as zero.
    prices_for(prices, settings.agent_model)

    workspace_store = FirestoreWorkspaceStore(firestore)
    spend = Spend(
        FirestoreSpendStore(firestore),
        clock,
        prices=prices,
        day_ceiling_usd_micros=access.day_ceiling_usd_micros,
        month_ceiling_usd_micros=access.month_ceiling_usd_micros,
    )
    facade = Access(
        workspaces=Workspaces(
            workspace_store,
            clock,
            signing_secret=settings.cookie_signing_secret.get_secret_value(),
            lifetime=timedelta(days=access.workspace_ttl_days),
        ),
        api_keys=ApiKeys(FirestoreApiKeyStore(firestore), workspace_store, clock),
        rate_limiter=RateLimiter(clock, per_minute=access.api_key_rate_per_minute),
        allowances=Allowances(
            FirestoreAllowanceStore(firestore),
            spend,
            clock,
            limits=Limits(
                conversations=access.allowance_conversations, messages=access.allowance_messages
            ),
            boosted_limits=Limits(
                conversations=access.boosted_conversations, messages=access.boosted_messages
            ),
        ),
        spend=spend,
        ip_hash_salt=access.ip_hash_salt.get_secret_value(),
        allowance_code=(
            access.allowance_code.get_secret_value() if access.allowance_code is not None else None
        ),
    )
    return AccessModule(facade=facade, routers=(build_router(facade),))
