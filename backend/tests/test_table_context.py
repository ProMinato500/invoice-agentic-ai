from types import SimpleNamespace

from backend.app.models import Element
from backend.app.recovery import recover
from backend.app.schemas import RecoveredPage
from backend.app.table_context import build_tables, recovery_chunks


def fixture(headers, rows, page=1, start=0):
    cells, elements = [], []
    for r, values in enumerate([headers, *rows]):
        for c, value in enumerate(values):
            eid = f"e-{start}-{r}-{c}"
            box = {
                "l": c * 60,
                "r": (c + 1) * 60,
                "t": r * 20 + 10,
                "b": r * 20 + 30,
                "coord_origin": "TOPLEFT",
            }
            cells.append(
                {
                    "start_row_offset_idx": r,
                    "start_col_offset_idx": c,
                    "end_row_offset_idx": r + 1,
                    "end_col_offset_idx": c + 1,
                    "text": value,
                    "bbox": box,
                    "column_header": r == 0,
                    "_evidence_id": eid,
                }
            )
            elements.append(
                Element(
                    id=eid,
                    document_id="doc",
                    organization_id="local",
                    page=page,
                    bbox=[box[k] for k in ("l", "t", "r", "b")],
                    raw_text=value,
                    method="DOCLING_CELL",
                )
            )
    return {
        "prov": [{"page_no": page}],
        "data": {"num_rows": len(rows) + 1, "num_cols": len(headers), "table_cells": cells},
    }, elements


def test_complete_rows_repeated_headers_and_no_duplicate_blocks():
    table, elements = fixture(
        ["Description", "Quantity", "Unit Price", "Amount"],
        [[f"Product {i}", "2", "10", "20"] for i in range(8)],
    )
    context = build_tables({"tables": [table]}, elements)
    elements.append(
        Element(
            id="duplicate",
            page=1,
            bbox=[0, 30, 240, 50],
            raw_text="Product 0 2 10 20",
            method="PYMUPDF_SOURCE",
        )
    )
    chunks = recovery_chunks(elements, context, limit=9)
    assert len(chunks) == 4
    header_ids = {e.id for e in elements[:4]}
    row_indexes = []
    for chunk in chunks:
        assert header_ids <= {e.id for e in chunk["elements"]}
        assert chunk["tables"][0]["columns"] == ["Description", "Quantity", "Unit Price", "Amount"]
        assert all(len(r["cells"]) == 4 for r in chunk["tables"][0]["rows"])
        row_indexes.extend(r["index"] for r in chunk["tables"][0]["rows"])
        assert "duplicate" not in {e.id for e in chunk["elements"]}
    assert row_indexes == list(range(1, 9))


def test_merged_headers_keep_hierarchy_and_spans():
    table, elements = fixture(
        ["Description", "Tax", ""], [["", "CGST", "SGST"], ["Cable", "9%", "9%"]]
    )
    cells = table["data"]["table_cells"]
    cells[1]["end_col_offset_idx"] = 3
    cells.pop(2)
    for cell in cells:
        if cell["start_row_offset_idx"] == 1:
            cell["column_header"] = True
    context = build_tables({"tables": [table]}, elements)[0]
    assert context["columns"] == ["Description", "Tax / CGST", "Tax / SGST"]
    assert context["headers"][1]["col_span"] == 2
    assert [r["index"] for r in context["rows"]] == [2]


def test_historical_cell_grounding_uses_geometry_for_repeated_values():
    table, elements = fixture(["Quantity", "Amount"], [["1", "1"], ["1", "1"]])
    for cell in table["data"]["table_cells"]:
        cell.pop("_evidence_id")
        box = cell["bbox"]
        box["t"], box["b"] = 800 - box["t"], 800 - box["b"]
        box["coord_origin"] = "BOTTOMLEFT"
    context = build_tables(
        {"pages": {"1": {"size": {"height": 800}}}, "tables": [table]}, elements
    )[0]
    assert [c["evidence_ids"] for c in context["cells"]] == [[e.id] for e in elements]


def test_missing_continuation_headers_are_suggestions_only():
    first, a = fixture(["Description", "Quantity", "Unit Price"], [["Cable", "1", "20"]])
    second, b = fixture(["Adapter", "2", "10"], [], page=2, start=1)
    for c in second["data"]["table_cells"]:
        c["column_header"] = False
    tables = build_tables({"tables": [first, second]}, a + b)
    assert tables[1]["header_basis"] == "missing"
    assert tables[1]["columns"] == ["Column 1", "Column 2", "Column 3"]
    assert tables[1]["suggested_columns"] == tables[0]["columns"]
    assert tables[1]["continuation_basis"] == "ambiguous_requires_vision_or_review"
    chunk = recovery_chunks(a + b, [tables[1]])[0]
    assert {e.id for e in a[:3]} <= {e.id for e in chunk["elements"]}


def test_delivery_rows_cannot_become_priced_items_even_if_model_returns_them(monkeypatch):
    table, elements = fixture(
        ["Material Code", "Item", "Delivery Qty", "Expected Dispatch"],
        [["ITS-FRT-9410", "Freight", "1", "14-Oct-2026"]],
    )
    context = build_tables({"tables": [table]}, elements)
    assert context[0]["type_hint"] == "delivery_schedule"
    seen = []

    def model(role, payload, schema, tools, execute, emit):
        seen.append(payload)
        assert execute("inspect_extracted_table", SimpleNamespace(record_id="doc", page=1))[
            "tables"
        ]
        return RecoveredPage(
            header=[],
            rows=[{"fields": [], "evidence_ids": [elements[-1].id]}],
            is_complete=True,
            warnings=[],
        )

    monkeypatch.setattr("backend.app.recovery.agent", model)
    canonical = []
    _, warnings = recover(
        SimpleNamespace(id="doc", kind="po"),
        canonical,
        elements,
        {},
        {"suspect_pages": [1]},
        lambda *args: None,
        tables=context,
    )
    assert "NON_ITEM_TABLE_ROW_REJECTED" in warnings and not canonical
    assert seen[0]["tables"][0]["columns"][2] == "Delivery Qty"


def test_identifier_links_preserve_table_semantics():
    priced, a = fixture(
        ["Material Code", "Description", "Quantity", "Unit Price"], [["SKU-1", "Cable", "10", "2"]]
    )
    delivery, b = fixture(
        ["Material Code", "Delivery Qty", "Expected Dispatch"],
        [["SKU-1", "5", "Tomorrow"]],
        start=1,
    )
    tables = build_tables({"tables": [priced, delivery]}, a + b)
    assert tables[0]["type_hint"] == "priced_items"
    assert tables[1]["type_hint"] == "delivery_schedule"
    link = tables[1]["related_rows"][0]
    assert link["targets"][0]["table_id"] == tables[0]["id"]
    assert link["status"] == "EXPLICIT_IDENTIFIER_HINT_REQUIRES_VERIFICATION"


def test_priced_items_with_hsn_and_tax_columns_are_not_tax_summary():
    from backend.app.table_context import table_kind

    assert (
        table_kind(
            "Purchase Order Line Items",
            ["HSN / SAC", "Qty", "Unit Price", "Taxable Value", "GST %"],
        )
        == "priced_items"
    )
    assert (
        table_kind("HSN-wise tax summary", ["HSN / SAC", "Taxable Value", "CGST Amount"])
        == "tax_summary"
    )


def test_commercial_headers_percent_discount_and_tax_exclusive_amount():
    from decimal import Decimal

    from backend.app.extraction import parse_table

    rows = [
        [
            "#",
            "Material Code",
            "Description of Goods",
            "Qty",
            "UOM",
            "Rate",
            "Disc %",
            "Taxable Value",
            "GST %",
            "CGST",
            "SGST",
            "Amount",
        ],
        [
            "1",
            "SKU-1",
            "Laptop",
            "35",
            "EA",
            "98,500.00",
            "6.00",
            "32,40,650.00",
            "18%",
            "2,91,658.50",
            "2,91,658.50",
            "38,23,967.00",
        ],
    ]
    parsed, warnings = parse_table(rows, {1: ["row-1"]}, 1)
    assert not warnings and len(parsed) == 1
    row = parsed[0]
    assert row.discount == Decimal("206850")
    assert row.amount == Decimal("3240650")
    assert row.quantity * row.unit_price - row.discount == row.amount
    assert row.tax_rate == 18


def test_saved_table_refresh_preserves_ids_adds_missing_rows_and_protects_corrections():
    import json

    from sqlalchemy import select

    from backend.app.core.config import settings
    from backend.app.db import Session
    from backend.app.extraction import refresh_saved_tables
    from backend.app.models import Document, Line

    table, elements = fixture(
        ["Material Code", "Description", "Qty", "Unit Price", "Disc %", "Taxable Value"],
        [["SKU-A", "Cable", "10", "10", "10", "90"], ["SKU-B", "Adapter", "2", "20", "0", "40"]],
    )
    settings.storage.joinpath("extractions").mkdir(parents=True, exist_ok=True)
    settings.storage.joinpath("extractions/doc.json").write_text(json.dumps({"tables": [table]}))
    with Session() as db:
        doc = Document(
            id="doc",
            name="PO.pdf",
            kind="po",
            sha256="a" * 64,
            path="unused.pdf",
            page_count=1,
            size=1,
            state="EXTRACTED",
            extraction={"line_count": 1},
        )
        db.add(doc)
        db.flush()
        db.add_all(elements)
        line = Line(
            id="stable-row",
            document_id="doc",
            line_no=1,
            sku="SKU-A",
            description="Cable",
            quantity=10,
            unit="EA",
            unit_price=10,
            discount=10,
            amount=90,
            tax_rate=0,
            evidence=[{"element_id": elements[6].id}],
            attributes={},
            flags=["LINE_AMOUNT_MISMATCH"],
        )
        db.add(line)
        db.flush()
        result = refresh_saved_tables(db, doc)
        json.dumps(result)  # Audit payload must preserve Decimal values as JSON-safe strings.
        assert result["line_count"] == 2
        assert db.get(Line, "stable-row").flags == []
        assert db.get(Line, "stable-row").discount == 10
        assert len(list(db.scalars(select(Line)))) == 2
        assert doc.version == 2
        elements[6].normalized_value = "Reviewer edit"
        line.quantity = 99
        result = refresh_saved_tables(db, doc)
        assert line.quantity == 99
        assert "TABLE_REFRESH_PRESERVED_PROTECTED_ROW:stable-row" in result["warnings"]
        assert len(list(db.scalars(select(Line)))) == 2


def test_refresh_endpoint_is_versioned_and_audited(client):
    from sqlalchemy import select

    from backend.app.db import Session
    from backend.app.models import Review
    from backend.tests.test_pipeline import create

    rid, _ = create(client, "price_mismatch")
    bad = client.post(
        f"/api/reconciliations/{rid}/refresh-tables",
        json={"version": 999, "note": "Rebuild saved tables"},
    )
    assert bad.status_code == 409
    response = client.post(
        f"/api/reconciliations/{rid}/refresh-tables",
        json={"version": 1, "note": "Rebuild saved tables"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["run"]["version"] == 2
    with Session() as db:
        assert db.scalar(
            select(Review.id).where(
                Review.run_id == rid, Review.action == "table_extraction_refresh"
            )
        )


def test_supporting_only_page_does_not_create_false_item_coverage_gap():
    from backend.app.recovery import quality_gate

    priced, a = fixture(["Description", "Quantity", "Unit Price"], [["Cable", "1", "10"]])
    delivery, b = fixture(
        ["Material Code", "Delivery Qty", "Expected Dispatch"],
        [["SKU-A", "1", "Tomorrow"]],
        page=2,
        start=1,
    )
    tables = build_tables({"tables": [priced, delivery]}, a + b)
    rows = [SimpleNamespace(evidence_ids=[a[-1].id], amount=10)]
    header = {
        "number": "PO-1",
        "supplier": "Vendor",
        "buyer": "Buyer",
        "currency": "INR",
        "total": 10,
    }
    quality = quality_gate(SimpleNamespace(page_count=2), rows, a + b, header, [], tables=tables)
    assert "PAGE_WITH_ITEM_CONTENT_NOT_COVERED:2" not in quality["reasons"]
    outside = Element(
        id="outside",
        page=2,
        bbox=[0, 300, 100, 320],
        raw_text="Description Quantity Unit Price",
        method="PYMUPDF_SOURCE",
    )
    quality = quality_gate(
        SimpleNamespace(page_count=2), rows, a + b + [outside], header, [], tables=tables
    )
    assert "PAGE_WITH_ITEM_CONTENT_NOT_COVERED:2" in quality["reasons"]
    tables[1]["type_hint"] = "unknown"
    quality = quality_gate(SimpleNamespace(page_count=2), rows, a + b, header, [], tables=tables)
    assert "PAGE_WITH_ITEM_CONTENT_NOT_COVERED:2" in quality["reasons"]


def test_chunk_boundary_does_not_split_a_merged_body_row_group():
    table, elements = fixture(
        ["Description", "Qty", "Unit Price"], [["Cable", "2", "10"], ["", "3", "12"]]
    )
    cells = table["data"]["table_cells"]
    cells[3]["end_row_offset_idx"] = 3
    cells.pop(6)
    tables = build_tables({"tables": [table]}, elements)
    chunks = recovery_chunks(elements, tables, limit=3)
    table_chunks = [c for c in chunks if c["tables"]]
    assert len(table_chunks) == 1
    assert [r["index"] for r in table_chunks[0]["tables"][0]["rows"]] == [1, 2]
