"""Shared FastAPI dependencies. Override them in tests with app.dependency_overrides."""

import hmac
import os
from functools import lru_cache

from fastapi import Depends, Header, HTTPException

from app.agent.sales import SalesAgent
from app.business.settings import BusinessSettings, SettingsService
from app.catalog.service import CatalogService
from app.crm.service import CrmService
from app.integrations.config import TenantConfig, load_tenant
from app.integrations.sync import SyncLog, SyncService
from app.repositories.quotes import JsonQuoteRepository
from app.schemas.catalog import CatalogItem
from app.services.corrections import CorrectionStore
from app.services.editing import EditService
from app.services.extraction import ExtractionService
from app.services.menu import MenuPlanner
from app.services.portal import CustomerPortal
from app.services.pricing import PricingEngine


@lru_cache
def get_catalog_service() -> CatalogService:
    return CatalogService()


@lru_cache
def get_settings_service() -> SettingsService:
    return SettingsService()


def get_tenant_id(x_tenant_id: str = Header("demo")) -> str:
    return x_tenant_id


def get_catalog(tenant_id: str = Depends(get_tenant_id),
                svc: CatalogService = Depends(get_catalog_service)) -> list[CatalogItem]:
    return svc.items(tenant_id)


def get_rules(tenant_id: str = Depends(get_tenant_id),
              svc: SettingsService = Depends(get_settings_service)) -> BusinessSettings:
    return svc.get(tenant_id)


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


def get_menu_planner(catalog: list[CatalogItem] = Depends(get_catalog),
                     corrections: CorrectionStore = Depends(get_corrections)) -> MenuPlanner:
    return MenuPlanner(catalog, corrections=corrections)


def get_engine(catalog: list[CatalogItem] = Depends(get_catalog),
               rules: BusinessSettings = Depends(get_rules)) -> PricingEngine:
    return PricingEngine(catalog, rules=rules)


def get_edit_service(catalog: list[CatalogItem] = Depends(get_catalog)) -> EditService:
    return EditService(catalog)


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


def get_sales_agent(crm: CrmService = Depends(get_crm),
                    catalog: list[CatalogItem] = Depends(get_catalog),
                    engine: PricingEngine = Depends(get_engine),
                    planner: MenuPlanner = Depends(get_menu_planner),
                    rules: BusinessSettings = Depends(get_rules),
                    repo=Depends(get_repo)) -> SalesAgent:
    return SalesAgent(crm, catalog, engine, repo, planner=lambda req: planner.plan(req)[0],
                      business_name=rules.business_name, rules=rules)


def get_portal(repo=Depends(get_repo), crm: CrmService = Depends(get_crm),
               catalog: CatalogService = Depends(get_catalog_service),
               settings: SettingsService = Depends(get_settings_service),
               sync: SyncService = Depends(get_sync),
               loader=Depends(get_tenant_loader)) -> CustomerPortal:
    return CustomerPortal(repo, crm, catalog, settings, sync, loader)
