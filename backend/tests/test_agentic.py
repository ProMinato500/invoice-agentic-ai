import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.app import ai
from backend.app.core.config import settings
from backend.app.db import Session
from backend.app.matching import validate_semantic_decision
from backend.app.models import Document, Element, Event, Line, Run
from backend.app.optimization import solve_allocations
from backend.app.recovery import quality_gate, validate_field
from backend.app.schemas import GroundedField, Investigation, SemanticDecision
from backend.app.tools import render_region
from backend.tests.test_pipeline import create


def test_real_function_dispatch_loop_and_trace(monkeypatch):
    invocation = []
    calls = [
        SimpleNamespace(
            type="function_call",
            name="get_source_evidence",
            call_id="call-1",
            arguments=json.dumps(
                {"record_id": "source-1", "page": None, "bbox": None, "query": None}
            ),
        )
    ]
    final = Investigation(
        status="SUPPORTED",
        evidence_ids=["source-1"],
        rationale="Printed source",
        recommended_action="Inspect",
    )
    responses = iter(
        [
            SimpleNamespace(output=calls, output_parsed=None, usage=None, id="response-1"),
            SimpleNamespace(output=[], output_parsed=final, usage=None, id="response-2"),
        ]
    )

    def parse(**kwargs):
        invocation.append(kwargs)
        return next(responses)

    monkeypatch.setattr(
        ai, "client", lambda: SimpleNamespace(responses=SimpleNamespace(parse=parse))
    )
    trace = []
    executed = []
    result = ai.agent(
        "specification",
        {"source": "source-1"},
        Investigation,
        {"get_source_evidence": "Read source"},
        lambda name, args: executed.append(args.record_id) or {"text": "verified"},
        lambda status, message, data: trace.append((status, data)),
    )
    assert result == final and executed == ["source-1"]
    assert invocation[0]["tool_choice"] == "required"
    assert any(
        m.get("type") == "function_call_output" and m["call_id"] == "call-1"
        for m in invocation[1]["input"]
        if isinstance(m, dict)
    )
    assert [s for s, d in trace] == [
        "AI_REQUESTED",
        "AI_COMPLETED",
        "TOOL_STARTED",
        "TOOL_COMPLETED",
        "AI_REQUESTED",
        "AI_COMPLETED",
    ]


def test_agent_rejects_hallucinated_tool(monkeypatch):
    bad = SimpleNamespace(type="function_call", name="execute_sql", call_id="bad", arguments="{}")
    final = Investigation(
        status="UNRESOLVED", evidence_ids=[], rationale="Rejected", recommended_action="Review"
    )
    responses = iter(
        [
            SimpleNamespace(output=[bad], output_parsed=None, usage=None, id="r1"),
            SimpleNamespace(output=[], output_parsed=final, usage=None, id="r2"),
        ]
    )
    monkeypatch.setattr(
        ai,
        "client",
        lambda: SimpleNamespace(responses=SimpleNamespace(parse=lambda **kw: next(responses))),
    )
    executed = []
    logs = []
    ai.agent(
        "exception",
        {},
        Investigation,
        {"get_source_evidence": "Read"},
        lambda *a: executed.append(a),
        lambda s, m, d: logs.append(s),
    )
    assert not executed and "TOOL_FAILED" in logs


def test_bilateral_grounding_and_wrong_candidate():
    invoice = SimpleNamespace(evidence=[{"element_id": "inv"}])
    group = [
        {"po_line_id": "p1", "evidence": [{"element_id": "po1"}]},
        {"po_line_id": "p2", "evidence": [{"element_id": "po2"}]},
    ]

    def decision(ids):
        return SemanticDecision(
            po_line_id="p1", correspondence="SAME_PRODUCT", evidence_ids=ids, rationale="Test"
        )

    validate_semantic_decision(decision(["inv", "po1"]), invoice, group)
    for ids in (["inv"], ["po1"], ["inv", "po2"], ["invented"]):
        with pytest.raises(ValueError):
            validate_semantic_decision(decision(ids), invoice, group)


def test_completeness_detects_partial_page_and_amount():
    doc = Document(id="doc", organization_id="local", page_count=2)
    elements = [
        Element(id="one", page=1, raw_text="one row", method="DOCLING_CELL"),
        Element(
            id="two",
            page=2,
            raw_text="Description Quantity Amount missing row",
            method="DOCLING_TEXT",
        ),
    ]
    from backend.app.schemas import CanonicalLine

    row = CanonicalLine(
        line_no=1,
        description="one",
        quantity="1",
        unit_price="10",
        amount="10",
        evidence_ids=["one"],
    )
    quality = quality_gate(
        doc,
        [row],
        elements,
        {
            "number": "PO1",
            "supplier": "A",
            "buyer": "B",
            "currency": "USD",
            "total": "30",
            "subtotal": "30",
        },
        [],
    )
    assert quality["recovery_required"] and 2 in quality["suspect_pages"]
    assert "SUBTOTAL_COVERAGE_MISMATCH" in quality["reasons"]


def test_field_grounding_vision_not_independent():
    known = {
        "price": Element(id="price", raw_text="100.00", method="DOCLING_CELL"),
        "vision": Element(id="vision", raw_text="100.00", method="OPENAI_VISION_SOURCE"),
    }
    assert validate_field(
        GroundedField(name="unit_price", value="100", evidence_ids=["price"]), known
    )
    assert not validate_field(
        GroundedField(name="unit_price", value="100", evidence_ids=["vision"]), known
    )
    with pytest.raises(ValueError):
        validate_field(GroundedField(name="unit_price", value="100", evidence_ids=["bad"]), known)


def test_solver_split_capacity_and_unallocated():
    result = solve_allocations({"i": 10}, {"p1": 4, "p2": 5}, [("i", "p1", 0), ("i", "p2", 0)])
    assert result["status"] == "OPTIMAL"
    assert sum(p["micro_quantity"] for p in result["pieces"]) == 9
    assert result["unallocated"] == {"i": 1}


def test_trace_snapshot_and_cross_run_scope(client):
    rid, docs = create(client, "happy_path")
    events = client.get(f"/api/reconciliations/{rid}/events").json()["items"]
    ocr = next(e for e in events if e["status"] == "OCR_RESULT")
    trace = client.get(f"/api/reconciliations/{rid}/events/{ocr['id']}/trace")
    assert trace.status_code == 200
    snapshot = trace.json()["data"]["snapshot"]
    assert snapshot["elements"] and len(snapshot["canonical_lines"]) == 3
    second = client.post(
        "/api/reconciliations",
        json={"po_id": docs["po"]["id"], "invoice_ids": [docs["invoice"]["id"]]},
    ).json()["id"]
    assert client.get(f"/api/reconciliations/{second}/events/{ocr['id']}/trace").status_code == 404
    output = client.get(f"/api/documents/{docs['po']['id']}/extraction").json()
    assert output["metadata"]["line_count"] == 3
    assert "quality" in output["raw"]
    with Session() as db:
        doc = db.get(Document, docs["po"]["id"])
        assert render_region(doc, 1).startswith("data:image/png;base64,")
        with pytest.raises(ValueError):
            render_region(doc, 1, [-1, -1, 10, 10])


def test_durable_run_budget_survives_new_context(client, monkeypatch):
    rid, _ = create(client, "happy_path")
    from backend.app.workflow import emit

    monkeypatch.setattr(settings, "max_ai_requests_per_run", 1)
    emit(rid, "MATCHING", "AI_REQUESTED", "test", {})
    with ai.run_budget(rid):
        with pytest.raises(ValueError, match="AI_BUDGET_EXHAUSTED"):
            ai.reserve("requests")


def test_sse_drains_terminal_history(client):
    rid, _ = create(client, "happy_path")
    with Session() as db:
        last = max(e.sequence for e in db.scalars(select(Event).where(Event.run_id == rid)))
        db.add_all(
            [
                Event(
                    organization_id="local",
                    run_id=rid,
                    sequence=last + i + 1,
                    stage="TEST",
                    status="PROGRESS",
                    message="history",
                    data={},
                )
                for i in range(601)
            ]
        )
        db.commit()
    stream = client.get(f"/api/reconciliations/{rid}/stream?after={last}").text
    assert stream.count("data: {") == 602  # 601 events and terminal settled event
    assert stream.index(str(last + 601)) < stream.index("event: settled")


def test_authorized_split_rechecks_financials_and_capacity(client):
    rid, docs = create(client, "happy_path")
    matches = client.get(f"/api/reconciliations/{rid}/matches").json()["items"]
    first = matches[0]
    with Session() as db:
        po = db.get(Line, first["po_line"]["id"])
        half = po.quantity / 2
        po.quantity = half
        po.amount = po.amount / 2
        copy = Line(
            organization_id="local",
            document_id=po.document_id,
            line_no=4,
            description=po.description,
            sku=po.sku,
            quantity=half,
            unit=po.unit,
            unit_price=po.unit_price,
            amount=po.amount,
            attributes=po.attributes,
            evidence=po.evidence,
            flags=[],
        )
        db.add(copy)
        db.commit()
        second_po = copy.id
    pieces = [
        {"invoice_line_id": first["invoice_line"]["id"], "po_line_id": p, "quantity": str(half)}
        for p in (first["po_line"]["id"], second_po)
    ]
    response = client.post(
        f"/api/reconciliations/{rid}/allocation-review",
        json={
            "version": 1,
            "pieces": pieces,
            "note": "Both printed PO rows cover the same SKU; verified split.",
        },
    )
    assert response.status_code == 200, response.text
    from backend.app.workflow import process_run

    process_run(rid)
    run = client.get(f"/api/reconciliations/{rid}").json()
    assert run["outcome"] == "AUTO_APPROVABLE", client.get(
        f"/api/reconciliations/{rid}/discrepancies"
    ).json()
    from backend.app.models import Allocation

    with Session() as db:
        edges = list(
            db.scalars(
                select(Allocation).where(
                    Allocation.run_id == rid,
                    Allocation.invoice_line_id == first["invoice_line"]["id"],
                )
            )
        )
        assert len(edges) == 2 and sum(a.quantity for a in edges) == half * 2
    assert (
        client.post(
            f"/api/reconciliations/{rid}/allocation-review",
            json={"version": 1, "pieces": pieces, "note": "Stale plan."},
        ).status_code
        == 409
    )


def test_conditional_certification_and_approved_equivalence():
    from backend.app.normalization import compare_constraint

    assert compare_constraint("IP65", "IP54", "NEQ") == "PASS"
    condition = {
        "when": {"field": "voltage", "value": "230 V"},
        "then": {"field": "power", "value": "1 kW", "operator": "GTE"},
    }
    assert (
        compare_constraint(condition, {"voltage": "230 V", "power": "1200 W"}, "CONDITIONAL")
        == "PASS"
    )
    assert compare_constraint(condition, {"voltage": "230 V"}, "CONDITIONAL") == "UNKNOWN"
    assert compare_constraint("ISO9001", "ISO9001", "CERTIFIED_TO") == "UNKNOWN"
    assert (
        compare_constraint(
            "ISO9001",
            {"standards": ["ISO 9001"], "certificate_evidence_ids": ["certificate-1"]},
            "CERTIFIED_TO",
        )
        == "PASS"
    )
    assert compare_constraint({"allowed": ["M2"]}, "M2", "APPROVED_EQUIVALENT") == "UNKNOWN"
    assert (
        compare_constraint(
            {"allowed": ["M2"], "authorization_evidence_ids": ["authorization-1"]},
            "M2",
            "APPROVED_EQUIVALENT",
        )
        == "PASS"
    )


def test_recovery_canonical_field_names_reject_layout_labels():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GroundedField(name="Quantity ordered", value="2", evidence_ids=["source"])


def test_verification_preserves_math_failures_and_audit(client):
    rid, docs = create(client, "happy_path")
    with Session() as db:
        line = db.scalar(select(Line).where(Line.document_id == docs["invoice"]["id"]))
        line.flags = ["AI_RECOVERY_REQUIRES_REVIEW", "UNVERIFIED_QUANTITY", "LINE_AMOUNT_MISMATCH"]
        db.commit()
    response = client.post(
        f"/api/documents/{docs['invoice']['id']}/verify-extraction",
        json={"version": 1, "note": "Checked all fields against the original source."},
    )
    assert response.status_code == 200, response.text
    with Session() as db:
        line = db.scalar(select(Line).where(Line.document_id == docs["invoice"]["id"]))
        assert line.flags == ["LINE_AMOUNT_MISMATCH"]
        assert db.get(Document, docs["invoice"]["id"]).version == 2
        assert db.get(Run, rid).version == 2
    assert client.get(f"/api/reconciliations/{rid}/reviews").json()["items"]


def test_human_interrupt_resume_cannot_overwrite_new_version(client):
    rid, _ = create(client, "missing_specification")
    result = client.post(f"/api/reconciliations/{rid}/recalculate")
    assert result.status_code == 200
    from backend.app.workflow import graph, process_run

    process_run(rid)
    events = client.get(f"/api/reconciliations/{rid}/events").json()["items"]
    assert any(e["status"] == "RESUMED" and e["data"]["version"] == 2 for e in events)
    with graph() as flow:
        previous = flow.get_state({"configurable": {"thread_id": f"{rid}:v1"}})
        assert not previous.next and not previous.interrupts
    assert client.get(f"/api/reconciliations/{rid}").json()["version"] == 2


def test_agent_allocation_tool_respects_evaluation_isolation(client):
    rid, docs = create(client, "happy_path")
    response = client.post(
        "/api/reconciliations",
        json={"po_id": docs["po"]["id"], "invoice_ids": [docs["invoice"]["id"]]},
    )
    other = response.json()["id"]
    from backend.app.tools import dispatch

    with Session() as db:
        run = db.get(Run, other)
        run.policy = {**run.policy, "evaluation_id": "isolated-agent-test"}
        db.commit()
        po = db.scalar(select(Line).where(Line.document_id == docs["po"]["id"]))
        assert (
            dispatch(db, other, "get_previous_allocations", po.id, "local", emit=lambda *a: None)
            == []
        )
        run.policy = {}
        db.commit()
        assert dispatch(db, other, "get_previous_allocations", po.id, "local", emit=lambda *a: None)
