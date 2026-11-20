"""Stage 3: suppliers, ingredients and recipes through the API and the Excel import."""

import io
from datetime import date, timedelta

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.main import app
from app.purchasing.importer import (
    ING_SHEET,
    REC_SHEET,
    SUP_SHEET,
    analyze,
    parse_days,
    template_xlsx,
)
from app.purchasing.models import Ingredient, Supplier
from app.purchasing.service import PurchasingService
from app.schemas.catalog import CatalogItem

T = "acme"


def _client(env):
    from app import deps
    ps = PurchasingService(env["tmp"])
    app.dependency_overrides.update({
        deps.get_crm: lambda: env["crm"], deps.get_repo: lambda: env["repo"],
        deps.get_settings_service: lambda: env["settings"],
        deps.get_catalog_service: lambda: env["catalog"],
        deps.get_purchasing: lambda: ps,
        deps.get_tenant_loader: lambda: (lambda tid: env["tenant"]),
    })
    return TestClient(app), {"X-Tenant-ID": T}, ps


def test_suppliers_ingredients_and_recipes_api(env):
    c, h, ps = _client(env)
    try:
        assert len(c.get("/suppliers", headers=h).json()) >= 3   # demo data before any edit
        r = c.put("/suppliers/NEW", headers=h, json={"code": "NEW", "name": "ספק חדש",
                  "phone": "050-9999999", "lead_days": 2, "delivery_days": [6, 1],
                  "order_cutoff": "09:30"})
        assert r.status_code == 200 and r.json()["delivery_days"] == [1, 6]
        bad = c.put("/ingredients/X1", headers=h, json={"code": "X1", "name_he": "x",
                    "unit": "kg", "supplier": "NOPE"})
        assert bad.status_code == 422 and "NOPE" in bad.json()["detail"]
        ok = c.put("/ingredients/X1", headers=h, json={"code": "X1", "name_he": "בשר מיוחד",
                   "unit": "kg", "kashrut": "meat", "supplier": "NEW", "price": 50}).json()
        assert ok["price_updated_at"]
        # a meat ingredient in a pareve salad: refused with the reason
        r = c.patch("/catalog/SAL-ISR", headers=h, json={"recipe": [
            {"ingredient": "X1", "quantity": 1}]})
        assert r.status_code == 422 and "לא יכול להיות במנה" in r.json()["detail"]
        r = c.patch("/catalog/MAIN-KEBAB", headers=h, json={"recipe": [
            {"ingredient": "X1", "quantity": 0.2}], "station": "גריל", "prep_days": 1})
        assert r.status_code == 200 and r.json()["item"]["prep_days"] == 1
        row = next(i for i in c.get("/catalog", headers=h).json() if i["sku"] == "MAIN-KEBAB")
        assert row["recipe_cost"] == 10.0 and row["recipe_missing"] == []
        # can't delete an ingredient that a recipe uses
        assert c.delete("/ingredients/X1", headers=h).status_code == 409
        # deleting a supplier keeps its ingredients, without a supplier
        assert c.delete("/suppliers/NEW", headers=h).status_code == 204
        assert next(i for i in ps.ingredients(T) if i.code == "X1").supplier is None
    finally:
        app.dependency_overrides.clear()


def test_purchase_list_kitchen_and_schedule_endpoints(env):
    from tests.test_business import make_quote
    env["settings"].update(T, {"deposit_rate": 0})
    q, deal = make_quote(env, guests=80, days=4)
    env["portal"].accept(q.public_token, "recommended")
    c, h, _ = _client(env)
    try:
        day = date.today() + timedelta(days=4)
        k = c.get("/kitchen", headers=h, params={"day": day.isoformat()}).json()
        assert [s["kashrut"] for s in k["sections"]] == ["meat"]
        pl = c.get("/purchasing/list", headers=h, params={
            "start": date.today().isoformat(), "end": day.isoformat()}).json()
        assert pl["suppliers"] and all(b["items"] for o in pl["suppliers"] for b in o["batches"])
        assert any(o["code"] == "MEAT" for o in pl["suppliers"])
        x = c.get("/purchasing/list.xlsx", headers=h, params={"end": day.isoformat()})
        assert x.status_code == 200
        ws = load_workbook(io.BytesIO(x.content)).active
        assert ws["A1"].value == "ספק" and ws.max_row > 1
        sch = c.get("/production/schedule", headers=h, params={"end": day.isoformat()}).json()
        assert sch and any(t["deal_id"] == deal.id for d in sch for t in d["tasks"])
        bad = c.get("/purchasing/list", headers=h, params={"start": "2026-01-10",
                                                          "end": "2026-01-01"})
        assert bad.status_code == 422
    finally:
        app.dependency_overrides.clear()


# ---------- import ----------

SUPS = [Supplier(code="VEG", name="ירקות")]
INGS = [Ingredient(code="TOM", name_he="עגבניות", unit="kg", supplier="VEG", price=5)]
DISHES = [CatalogItem(sku="SAL", name_he="סלט", name_en="s", category="salad", unit="tray",
                      price=80, meal_type="pareve"),
          CatalogItem(sku="CHEESE", name_he="פשטידה", name_en="c", category="main", unit="tray",
                      price=80, meal_type="dairy")]


def _book(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_parse_days():
    assert parse_days("א,ב,ג,ד,ה") == [0, 1, 2, 3, 6]
    assert parse_days("ראשון / שלישי") == [1, 6]
    assert parse_days("שמונה") is None


def test_import_preview_reports_every_error_and_applies_valid_rows():
    data = _book({
        SUP_SHEET: [["קוד ספק", "שם הספק", "טלפון", "ימים מהזמנה לאספקה", "ימי אספקה"],
                    ["DAIRY", "מחלבה", "050-1", 1, "א,ג,ה"],
                    ["BAD", "ספק", "", "x", "א"],              # lead days not a number
                    ["BAD2", "ספק", "", 1, "יום כיפור"]],      # unknown day
        ING_SHEET: [["קוד חומר גלם", "שם", "יחידה", "כשרות", "קוד ספק", "מחיר ליחידה (לפני מע\"מ)"],
                    ["MILK", "חלב", "ליטר", "חלבי", "DAIRY", 6],   # supplier from the same file
                    ["TOM", None, None, None, None, 7],           # price update only
                    ["X", "x", "שק", "פרווה", None, None],        # unknown unit
                    ["Y", "y", 'ק"ג', "פרווה", "NOPE", None]],    # unknown supplier
        REC_SHEET: [['מק"ט מנה', "קוד חומר גלם", "כמות ליחידת מנה"],
                    ["SAL", "TOM", 1.5],
                    ["CHEESE", "MILK", 2],
                    ["SAL", "MILK", 0.1],      # dairy in a pareve salad → the whole recipe refused
                    ["GHOST", "TOM", 1],
                    ["CHEESE", "TOM", None]],
    })
    rep, plan = analyze("x.xlsx", data, SUPS, INGS, DISHES)
    errs = {(e.sheet, e.row, e.column) for e in rep.errors}
    assert (SUP_SHEET, 3, "ימים מהזמנה לאספקה") in errs and (SUP_SHEET, 4, "ימי אספקה") in errs
    assert (ING_SHEET, 4, "יחידה") in errs and (ING_SHEET, 5, "קוד ספק") in errs
    assert (REC_SHEET, 5, 'מק"ט מנה') in errs and (REC_SHEET, 6, "כמות ליחידת מנה") in errs
    assert any("לא יכול להיות במנה" in e.message for e in rep.errors)
    assert [s.code for s in plan.suppliers] == ["DAIRY"]
    assert plan.suppliers[0].delivery_days == [1, 3, 6]
    assert {i.code: i.price for i in plan.ingredients} == {"MILK": 6, "TOM": 7}
    assert "SAL" not in plan.recipes                       # refused as a whole
    assert [(r.ingredient, r.quantity) for r in plan.recipes["CHEESE"]] == [("MILK", 2)]


def test_template_round_trips():
    data = template_xlsx(SUPS, INGS, DISHES)
    rep, plan = analyze("t.xlsx", data, SUPS, INGS, DISHES)
    assert not rep.errors and not rep.creates and not rep.updates
    assert load_workbook(io.BytesIO(data)).sheetnames[:4] == [SUP_SHEET, ING_SHEET, REC_SHEET,
                                                              "מנות במטבח"]
