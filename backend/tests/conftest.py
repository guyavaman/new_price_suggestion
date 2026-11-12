import pytest

from app.catalog.loader import load_catalog
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan
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
