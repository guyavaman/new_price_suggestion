import pytest

from app.catalog.loader import load_catalog
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan
from app.security import limiter
from app.services.pricing import PricingEngine


@pytest.fixture(scope="session")
def catalog():
    return load_catalog()


@pytest.fixture
def engine(catalog):
    return PricingEngine(catalog, vat_rate=0.18)


@pytest.fixture
def bar_mitzvah_req():
    return ExtractedRequest.model_validate({
        "language": "he", "event_type": "bar_bat_mitzvah", "guest_count": 120,
        "event_date": "2026-12-03", "location": "אולם בראשון לציון", "kashrut": "kosher",
        "meal_type": "meat", "dietary_requirements": [{"tag": "vegan", "guest_count": 8}],
        "service": {"waiters": True, "bar": True},
    })


@pytest.fixture
def bar_mitzvah_plan():
    return MenuPlan(lines=[
        MenuLine(sku="PKG-MEAT-STD", for_guests=112, source="suggested", confidence="high"),
        MenuLine(sku="PKG-VEGAN", for_guests=8, source="suggested", confidence="high"),
        MenuLine(sku="CAN-SKEWER-CHICK", for_guests=120, source="suggested", confidence="medium"),
        MenuLine(sku="BAR-OPEN", for_guests=120, source="requested", confidence="high"),
        MenuLine(sku="DRK-SOFT", for_guests=120, source="suggested", confidence="high"),
    ])


@pytest.fixture
def env(tmp_path):
    """A whole tenant on disk: settings, CRM, catalog, quotes, sync to the built-in CRM, portal.
    Tenant id "acme"."""
    from app.business.settings import SettingsService
    from app.catalog.service import CatalogService
    from app.crm.service import CrmService
    from app.integrations.adapters.internal import InternalCrmAdapter
    from app.integrations.config import IntegrationConfig, TenantConfig
    from app.integrations.sync import SyncLog, SyncService
    from app.repositories.quotes import JsonQuoteRepository
    from app.services.portal import CustomerPortal
    T = "acme"
    settings = SettingsService(tmp_path)
    crm = CrmService(tmp_path, settings)
    catalog = CatalogService(tmp_path)
    repo = JsonQuoteRepository(tmp_path / "quotes.json")
    tenant = TenantConfig(tenant_id=T, name="Acme",
                          integrations=[IntegrationConfig(id="crm", type="internal")])
    sync = SyncService(SyncLog(tmp_path / "sync.json"),
                       lambda cfg: InternalCrmAdapter(cfg, crm=crm))
    portal = CustomerPortal(repo, crm, catalog, settings, sync,
                            lambda tid: tenant if tid == T else None)
    return {"settings": settings, "crm": crm, "catalog": catalog, "repo": repo,
            "sync": sync, "tenant": tenant, "portal": portal, "tmp": tmp_path}




@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    limiter.reset()
    yield
