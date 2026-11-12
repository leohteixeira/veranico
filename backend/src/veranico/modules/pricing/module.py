"""Wiring of `pricing`. Only `bootstrap.py` imports this file."""

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import APIRouter

from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.pricing.application.service import PricingService
from veranico.modules.pricing.contracts import PricingFacade
from veranico.modules.pricing.http.router import build_router
from veranico.shared.infrastructure.settings import Settings


@dataclass(frozen=True, kw_only=True)
class PricingDeps:
    settings: Settings
    climate: ClimateFacade


@dataclass(frozen=True, kw_only=True)
class PricingModule:
    facade: PricingFacade
    routers: Sequence[APIRouter]


def build(deps: PricingDeps) -> PricingModule:
    facade = PricingService(climate=deps.climate, settings=deps.settings.pricing)
    return PricingModule(facade=facade, routers=(build_router(facade, deps.climate),))
