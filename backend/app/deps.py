"""Shared FastAPI dependencies. Override them in tests with app.dependency_overrides."""

import hmac
import os
from functools import lru_cache

from fastapi import Depends, Header, HTTPException

from app.agent.sales import SalesAgent
from app.catalog.loader import load_catalog
from app.crm.service import CrmService
from app.integrations.config import TenantConfig, load_tenant
from app.integrations.sync import SyncLog, SyncService
from app.repositories.quotes import JsonQuoteRepository
from app.schemas.catalog import CatalogItem
from app.services.corrections import CorrectionStore
from app.services.editing import EditService
from app.services.extraction import ExtractionService
from app.services.menu import MenuPlanner
from app.services.pricing import PricingEngine


@lru_cache
def get_catalog() -> list[CatalogItem]:
    return load_catalog()


@lru_cache
def get_corrections() -> CorrectionStore:
    return CorrectionStore()


@lru_cache
def get_repo() -> JsonQuoteRepository:
    return JsonQuoteRepository()


@lru_cache
def get_sync() -> SyncService:
    return SyncService(SyncLog())


def get_tenant_loader():
    return load_tenant


def get_extraction_service() -> ExtractionService:
    return ExtractionService()


def get_menu_planner() -> MenuPlanner:
    return MenuPlanner(get_catalog(), corrections=get_corrections())


def get_engine() -> PricingEngine:
    return PricingEngine(get_catalog())


def get_edit_service() -> EditService:
    return EditService(get_catalog())


def get_tenant(
    x_tenant_id: str = Header("demo"),
    x_api_key: str | None = Header(None),
    loader=Depends(get_tenant_loader),
) -> TenantConfig:
    tenant = loader(x_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Unknown tenant '{x_tenant_id}'")
    if tenant.api_key_env:
        expected = os.environ.get(tenant.api_key_env, "")
        if not expected or not x_api_key or not hmac.compare_digest(expected, x_api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return tenant




@lru_cache
def get_crm() -> CrmService:
    return CrmService()


def get_public_tenant(x_tenant_id: str = Header("demo"),
                      loader=Depends(get_tenant_loader)) -> TenantConfig:
    """For the public chat widget: tenant only, no API key (it runs in the browser)."""
    tenant = loader(x_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Unknown tenant '{x_tenant_id}'")
    return tenant


def get_sales_agent() -> SalesAgent:
    planner = get_menu_planner()
    return SalesAgent(get_crm(), get_catalog(), get_engine(), get_repo(),
                      planner=lambda req: planner.plan(req)[0])
