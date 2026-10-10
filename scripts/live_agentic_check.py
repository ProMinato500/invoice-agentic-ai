"""Live local acceptance: actual worker, configured provider, Docling and saved traces."""

import json
import time
import uuid

import httpx
from reportlab.pdfgen import canvas

from backend.app.core.config import settings
from backend.app.db import Session
from backend.app.models import Run

BASE = "http://127.0.0.1:8010"
TERMINAL = {
    "COMPLETED",
    "COMPLETED_WITH_DISCREPANCIES",
    "WAITING_FOR_REVIEW",
    "FAILED",
    "CANCELLED",
}
headers = {"Authorization": "Bearer " + settings.api_token} if settings.api_token else {}


def wait(client, run_id):
    deadline = time.time() + 700
    while time.time() < deadline:
        result = client.get(f"/api/reconciliations/{run_id}").json()
        if result["status"] in TERMINAL:
            assert result["status"] != "FAILED", result.get("error")
            return result
        time.sleep(2)
    raise TimeoutError("Live acceptance run did not finish")


def new_run(client, po, inv):
    result = client.post(
        "/api/reconciliations",
        json={"po_id": po, "invoice_ids": [inv], "idempotency_key": str(uuid.uuid4())},
    )
    result.raise_for_status()
    run_id = result.json()["id"]
    with Session() as db:
        run = db.get(Run, run_id)
        run.policy = {**run.policy, "evaluation_id": "live-agentic-acceptance"}
        db.commit()
    return run_id


def main():
    results = []
    with httpx.Client(base_url=BASE, headers=headers, timeout=30) as client:
        loaded = client.post("/api/synthetic/scenarios/semantic_alias/load").json()
        alias_id = new_run(client, loaded["po"]["id"], loaded["invoice"]["id"])
        alias = wait(client, alias_id)
        events = client.get(f"/api/reconciliations/{alias_id}/events").json()["items"]
        roles = {e["data"].get("role") for e in events if e["status"] == "TOOL_COMPLETED"}
        assert "matching" in roles, roles
        assert "exception" in roles, roles
        assert any(e["status"] == "ALLOCATION_SOLVED" for e in events)
        results.append(
            {
                "case": "semantic_alias",
                "run_id": alias_id,
                "outcome": alias["outcome"],
                "tool_roles": sorted(r for r in roles if r),
            }
        )
        folder = settings.storage / "agentic-fixtures"
        folder.mkdir(exist_ok=True)
        suffix = uuid.uuid4().hex[:8]
        ids = []
        for kind in ("po", "invoice"):
            path = folder / (kind + "-" + suffix + ".pdf")
            pdf = canvas.Canvas(str(path))
            text = pdf.beginText(50, 790)
            text.setFont("Helvetica", 11)
            lines = [
                "Purchase Order Number: PO-" + suffix
                if kind == "po"
                else "Invoice Number: INV-" + suffix,
                "PO Reference: PO-" + suffix,
                "Supplier: Demo Source Ltd",
                "Buyer: Demo Buyer Ltd",
                "Currency: USD",
                "Product description: Model Z120 laptop 16GB RAM"
                + (" 3 years warranty" if kind == "po" else ""),
                "Part number: Z120",
                "Quantity ordered: 2" if kind == "po" else "Quantity billed: 2",
                "Unit: EA",
                "Unit price: 100.00",
                "Extended amount: 200.00",
                "Subtotal: 200.00",
                "Tax: 0.00",
                "Grand Total: 200.00",
            ]
            for line in lines:
                text.textLine(line)
                text.moveCursor(0, 5)
            pdf.drawText(text)
            pdf.save()
            upload = client.post(
                "/api/documents/upload",
                data={"kind": kind},
                files={"file": (path.name, path.read_bytes(), "application/pdf")},
            )
            upload.raise_for_status()
            ids.append(upload.json()["id"])
        recovery_id = new_run(client, *ids)
        recovered = wait(client, recovery_id)
        events = client.get(f"/api/reconciliations/{recovery_id}/events").json()["items"]
        roles = {e["data"].get("role") for e in events if e["status"] == "TOOL_COMPLETED"}
        assert "extraction_recovery" in roles, roles
        matches = client.get(f"/api/reconciliations/{recovery_id}/matches").json()["items"]
        assert len(matches) == 1, matches
        ocr = next(e for e in events if e["status"] == "OCR_RESULT")
        trace = client.get(f"/api/reconciliations/{recovery_id}/events/{ocr['id']}/trace").json()
        assert trace["data"]["snapshot"]["elements"]
        results.append(
            {
                "case": "unruled_layout_recovery",
                "run_id": recovery_id,
                "outcome": recovered["outcome"],
                "tool_roles": sorted(r for r in roles if r),
                "extracted_lines": len(matches),
            }
        )
        vision = client.post(
            f"/api/reconciliations/{recovery_id}/reinspect",
            json={"version": recovered["version"], "document_id": ids[1], "page": 1},
        )
        vision.raise_for_status()
        viewed = wait(client, recovery_id)
        events = client.get(f"/api/reconciliations/{recovery_id}/events").json()["items"]
        assert any(e["status"] == "VISION_RESULT" for e in events), events
        results.append(
            {
                "case": "actual_source_vision",
                "run_id": recovery_id,
                "version": viewed["version"],
                "outcome": viewed["outcome"],
                "vision_result": True,
            }
        )
    path = settings.storage / "live-agentic-acceptance.json"
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
