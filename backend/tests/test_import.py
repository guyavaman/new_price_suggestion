"""Stage 1: importing items, prices and costs from Excel/CSV, with a preview and error report."""

import io

from openpyxl import Workbook, load_workbook

from app.catalog.importer import COMP_SHEET, ITEMS_SHEET, analyze, template_xlsx
from app.schemas.catalog import CatalogItem, Component


def item(sku, cat="salad", price=50, cost=None, **kw):
    return CatalogItem(sku=sku, name_he=f"פריט {sku}", name_en=sku, category=cat,
                       unit="per_guest", price=price, meal_type="pareve", cost=cost, **kw)


CURRENT = [item("S1", cost=20), item("S2"), item("P1", "package", 100,
                                                  components=[Component(sku="S1")])]


def xlsx(rows, comps=None, headers=None):
    wb = Workbook()
    ws = wb.active
    ws.title = ITEMS_SHEET
    ws.append(headers or ['מק"ט', "שם", "קטגוריה", "יחידה", 'מחיר ללקוח (לפני מע"מ)',
                          'עלות ליחידה (לפני מע"מ)', "מקור העלות", "סוג", "סועדים ליחידה",
                          "פעיל"])
    for r in rows:
        ws.append(r)
    if comps:
        cs = wb.create_sheet(COMP_SHEET)
        cs.append(['מק"ט חבילה', 'מק"ט רכיב', "כמות", "לכל כמה סועדים"])
        for r in comps:
            cs.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_preview_shows_changes_and_every_error_by_row():
    data = xlsx([
        ["S1", None, None, None, None, 26, "ספק", None, None, None],      # cost update
        ["S2", None, None, None, None, "abc", None, None, None, None],    # bad number
        ["N1", "סלט חדש", "סלט", "מגש", 90, 30, None, "פרווה", 12, "כן"],  # new item
        ["N2", "חסר מחיר", "סלט", "מגש", None, None, None, "פרווה", None, None],
        ["P1", None, None, None, None, 40, None, None, None, None],       # cost on a package
        ["S1", None, None, None, 55, None, None, None, None, None],       # duplicate row
        ["N3", "x", "מרק", "מגש", 10, None, None, "פרווה", None, None],    # unknown category
    ])
    rep, items = analyze("menu.xlsx", data, CURRENT)
    assert [c.sku for c in rep.creates] == ["N1"]
    upd = {u.sku: u.fields for u in rep.updates}
    assert upd["S1"]["cost"] == [20, 26] and upd["S1"]["cost_source"] == [None, "supplier"]
    errs = {(e.row, e.column) for e in rep.errors}
    assert (3, "עלות") in errs                       # S2: "abc"
    assert (5, "מחיר") in errs                       # N2: new item without a price
    assert (6, "עלות") in errs                       # P1: package cost
    assert (7, 'מק"ט') in errs                       # duplicate S1
    assert any(e.row == 8 and "קטגוריות" in e.message for e in rep.errors)
    assert {i.sku for i, _ in items} == {"S1", "N1"}  # only valid rows would be written
    new = next(i for i, _ in items if i.sku == "N1")
    assert (new.category.value, new.unit.value, new.serves, new.cost) == ("salad", "tray", 12, 30)


def test_empty_cells_keep_existing_values_and_csv_works():
    csv_data = b'sku,price,cost\nS1,60,\n'
    rep, items = analyze("menu.csv", csv_data, CURRENT)
    s1 = items[0][0]
    assert s1.price == 60 and s1.cost == 20 and not rep.errors


def test_components_sheet_defines_packages():
    data = xlsx([], comps=[["P1", "S1", 1, 10], ["P1", "S2", 2, 1], ["P1", "XX", 1, 1],
                           ["S1", "S2", 1, 1]])
    rep, items = analyze("m.xlsx", data, CURRENT)
    p1 = next(i for i, _ in items if i.sku == "P1")
    assert [(c.sku, c.quantity, c.per_guests) for c in p1.components] == [("S1", 1, 10),
                                                                         ("S2", 2, 1)]
    msgs = [e.message for e in rep.errors]
    assert any("XX" in m for m in msgs) and any("אינו חבילה" in m for m in msgs)


def test_missing_sku_column_and_unreadable_file():
    rep, _ = analyze("m.xlsx", xlsx([["a"]], headers=["שם"]), CURRENT)
    assert rep.errors[0].column == 'מק"ט'
    rep2, _ = analyze("m.xlsx", b"not a workbook", CURRENT)
    assert "לא ניתן לקרוא" in rep2.errors[0].message


def test_template_round_trips():
    wb = load_workbook(io.BytesIO(template_xlsx(CURRENT)))
    assert wb.sheetnames == [ITEMS_SHEET, COMP_SHEET, "הסבר"]
    rep, items = analyze("t.xlsx", template_xlsx(CURRENT), CURRENT)
    assert not rep.errors and not rep.creates and not rep.updates  # unchanged menu = no-op
