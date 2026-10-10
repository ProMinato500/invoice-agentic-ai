import pytest
from sqlalchemy import func, select

from backend.app.db import Session
from backend.app.models import Allocation, Line, Run
from backend.app.workflow import process_run
from synthetic_data.__main__ import generate


def create(client, scenario, evaluation=False):
    generate(scenario)
    loaded = client.post(f"/api/synthetic/scenarios/{scenario}/load")
    assert loaded.status_code == 200, loaded.text
    docs = loaded.json()
    payload = {
        "po_id": docs["po"]["id"],
        "invoice_ids": [docs["invoice"]["id"]],
        "idempotency_key": scenario,
    }
    response = client.post("/api/reconciliations", json=payload)
    assert response.status_code == 201, response.text
    rid = response.json()["id"]
    if evaluation:
        with Session() as db:
            run = db.get(Run, rid)
            run.policy = {**run.policy, "evaluation_id": "test"}
            db.commit()
    process_run(rid)
    return rid, docs


@pytest.mark.parametrize(
    "scenario,expected,code",
    [
        ("happy_path", "AUTO_APPROVABLE", None),
        ("specification_mismatch", "BLOCKED", "SPEC_MISMATCH"),
        ("partial_invoice", "AUTO_APPROVABLE", None),
        ("price_mismatch", "BLOCKED", "PRICE_MISMATCH"),
        ("quantity_overbilling", "BLOCKED", "QUANTITY_OVERBILL"),
        ("total_mismatch", "BLOCKED", "TOTAL_MISMATCH"),
        ("currency_mismatch", "BLOCKED", "CURRENCY_MISMATCH"),
        ("missing_specification", "REVIEW_REQUIRED", "SPEC_MISSING"),
        ("model_mismatch", "BLOCKED", "SPEC_MISMATCH"),
        ("ambiguous_match", "REVIEW_REQUIRED", "AMBIGUOUS_MATCH"),
    ],
)
def test_real_pdf_pipeline(client, scenario, expected, code):
    rid, _ = create(client, scenario)
    run = client.get(f"/api/reconciliations/{rid}").json()
    assert run["error"] is None, run["error"]
    assert run["outcome"] == expected, client.get(
        f"/api/reconciliations/{rid}/discrepancies"
    ).json()
    matches = client.get(f"/api/reconciliations/{rid}/matches").json()["items"]
    assert len(matches) > 0
    assert matches[0]["invoice_line"]["evidence"][0]["bbox"]
    events = client.get(f"/api/reconciliations/{rid}/events").json()["items"]
    assert any(e["stage"] == "EXTRACTING" and e["status"] == "COMPLETED" for e in events)
    assert len({e["sequence"] for e in events}) == len(events)
    if code:
        assert code in [
            d["code"]
            for d in client.get(f"/api/reconciliations/{rid}/discrepancies").json()["items"]
        ]
    for fmt in ["json", "csv", "pdf"]:
        report = client.get(f"/api/reconciliations/{rid}/report?format={fmt}")
        assert report.status_code == 200
        if fmt == "pdf":
            assert report.content.startswith(b"%PDF-")


def test_duplicates_and_idempotency(client):
    rid, docs = create(client, "happy_path")
    repeat = client.post(
        "/api/reconciliations",
        json={
            "po_id": docs["po"]["id"],
            "invoice_ids": [docs["invoice"]["id"]],
            "idempotency_key": "happy_path",
        },
    )
    assert repeat.json()["id"] == rid
    duplicate = client.post(
        "/api/reconciliations",
        json={"po_id": docs["po"]["id"], "invoice_ids": [docs["invoice"]["id"]]},
    )
    second = duplicate.json()["id"]
    process_run(second)
    codes = [
        d["code"]
        for d in client.get(f"/api/reconciliations/{second}/discrepancies").json()["items"]
    ]
    assert "DUPLICATE_INVOICE" in codes


def test_review_correction_recompute(client):
    rid, _ = create(client, "specification_mismatch")
    match = client.get(f"/api/reconciliations/{rid}/matches").json()["items"][0]
    review = client.post(
        f"/api/matches/{match['id']}/review",
        json={
            "action": "substitution",
            "po_line_id": match["po_line"]["id"],
            "version": match["version"],
            "note": "Authorized substitution supported by local reviewer evidence.",
        },
    )
    assert review.status_code == 200, review.text
    process_run(rid)
    run = client.get(f"/api/reconciliations/{rid}").json()
    assert run["version"] == 2 and run["outcome"] == "AUTO_APPROVABLE"
    assert len(client.get(f"/api/reconciliations/{rid}/reviews").json()["items"]) == 1
    evidence = match["invoice_line"]["evidence"][0]
    element = client.get(f"/api/elements/{evidence['element_id']}").json()
    result = client.post(
        f"/api/elements/{element['id']}/correct",
        json={
            "line_id": match["invoice_line"]["id"],
            "field": "quantity",
            "value": "12",
            "version": element["version"],
            "note": "Corrected against the printed source quantity.",
        },
    )
    assert result.status_code == 200, result.text
    process_run(rid)
    assert client.get(f"/api/reconciliations/{rid}").json()["outcome"] == "BLOCKED"
    assert client.get(f"/api/elements/{element['id']}").json()["raw_text"] == element["raw_text"]
    assert client.get(f"/api/elements/{element['id']}").json()["normalized_value"] == "12"


def test_file_security(client):
    bad = client.post(
        "/api/documents/upload",
        data={"kind": "po"},
        files={"file": ("evil.pdf", b"not a PDF", "application/pdf")},
    )
    assert bad.status_code == 415
    bad = client.post(
        "/api/documents/upload",
        data={"kind": "po"},
        files={"file": ("evil.pdf", b"%PDF-broken", "application/pdf")},
    )
    assert bad.status_code == 422
    assert client.get("/api/documents/not-a-record/file").status_code == 404
    assert client.post("/api/synthetic/scenarios/../../load").status_code in (404, 405)


def test_tenant_scope_and_tool_allowlist(client):
    from pydantic import ValidationError

    from backend.app.schemas import ToolRequest
    from backend.app.tools import dispatch

    rid, _ = create(client, "happy_path")
    with Session() as db:
        line = db.scalar(select(Line).where(Line.organization_id == "local"))
        with pytest.raises(ValueError):
            dispatch(db, rid, "get_po_line", line.id, "other")
        with pytest.raises(ValidationError):
            ToolRequest(name="execute_sql", record_id="x")
        assert db.scalar(select(func.count()).select_from(Allocation)) == 3


def test_evaluation_isolation(client):
    rid, _ = create(client, "happy_path")
    response = client.post(
        "/api/evaluations",
        json={"scenario_ids": ["happy_path", "specification_mismatch"]},
    )
    assert response.status_code == 201
    from evaluation.runner import evaluate

    evaluate(response.json()["id"])
    result = client.get("/api/evaluations/" + response.json()["id"]).json()
    assert result["status"] == "COMPLETED", result
    assert result["results"]["false_approvals"] == 0
    assert result["results"]["scenarios"][0]["outcome"] == "AUTO_APPROVABLE"
    assert result["results"]["scenarios"][1]["outcome"] == "BLOCKED"


def test_stale_reviews_and_invalid_numeric_correction(client):
    rid, _ = create(client, "happy_path")
    match = client.get(f"/api/reconciliations/{rid}/matches").json()["items"][0]
    stale = client.post(
        "/api/matches/" + match["id"] + "/review",
        json={"action": "accept", "version": 99, "note": "Must reject stale state."},
    )
    assert stale.status_code == 409
    e = match["invoice_line"]["evidence"][0]
    bad = client.post(
        "/api/elements/" + e["element_id"] + "/correct",
        json={
            "line_id": match["invoice_line"]["id"],
            "field": "quantity",
            "value": "not-a-number",
            "version": 1,
            "note": "Invalid numeric correction.",
        },
    )
    assert bad.status_code == 422
    queue = client.get("/api/reconciliations?review_only=true").json()
    assert queue["total"] == 0


def test_index_refresh_after_source_correction(client):
    from backend.app.models import SearchRecord
    from backend.app.retrieval import index_po

    rid, docs = create(client, "happy_path")
    with Session() as db:
        line = db.scalar(select(Line).where(Line.document_id == docs["po"]["id"]))
        line.description = "Verified replacement model Z99 laptop i7 16GB RAM 512GB SSD"
        db.commit()
        index_po(db, docs["po"]["id"], "local", lambda *args: None)
        record = db.scalar(select(SearchRecord).where(SearchRecord.line_id == line.id))
        assert "Z99" in record.search_text


def test_po_revision_guard(client):
    from backend.app.core.config import settings
    from backend.app.storage import store_pdf
    from synthetic_data.__main__ import render

    rid, docs = create(client, "happy_path")
    folder = settings.storage / "revision"
    folder.mkdir()
    rows = [
        {
            "sku": "NEW-001",
            "description": "Northstar model X99 laptop i7 16GB RAM 512GB SSD 3 years warranty",
            "qty": 1,
            "price": 100,
        }
    ]
    render(folder / "po.pdf", "po", rows, "revision", "clean_po")
    render(folder / "inv.pdf", "invoice", rows, "revision", "clean_invoice")
    with Session() as db:
        po, _ = store_pdf(db, (folder / "po.pdf").read_bytes(), "po.pdf", "po", "local")
        inv, _ = store_pdf(db, (folder / "inv.pdf").read_bytes(), "inv.pdf", "invoice", "local")
        run = Run(
            po_id=po.id,
            invoice_ids=[inv.id],
            policy={"price_tolerance_percent": "2", "rounding_tolerance": "0.02"},
        )
        db.add(run)
        db.commit()
        second = run.id
    process_run(second)
    codes = [
        d["code"]
        for d in client.get(f"/api/reconciliations/{second}/discrepancies").json()["items"]
    ]
    assert "PO_REVISION_REVIEW_REQUIRED" in codes


@pytest.mark.parametrize(
    "case,code",
    [
        ("discount", "DISCOUNT_MISMATCH"),
        ("freight", "FREIGHT_REVIEW_REQUIRED"),
        ("tax", "TAX_RATE_REVIEW"),
    ],
)
def test_charge_safeguards(client, case, code):
    from backend.app.models import Document
    from backend.app.validation import validate

    rid, docs = create(client, "happy_path")
    with Session() as db:
        po_line = db.scalar(
            select(Line).where(Line.document_id == docs["po"]["id"]).order_by(Line.line_no)
        )
        invoice_line = db.scalar(
            select(Line).where(Line.document_id == docs["invoice"]["id"]).order_by(Line.line_no)
        )
        if case == "discount":
            po_line.discount = 10
        elif case == "freight":
            inv = db.get(Document, docs["invoice"]["id"])
            header = dict(inv.extraction["header"])
            header["freight"] = "5"
            header["total"] = str(float(header["total"]) + 5)
            inv.extraction = {**inv.extraction, "header": header}
        else:
            invoice_line.tax_rate = 5
        db.commit()
    with Session() as db:
        validate(db, rid)
    codes = [
        d["code"] for d in client.get(f"/api/reconciliations/{rid}/discrepancies").json()["items"]
    ]
    assert code in codes
