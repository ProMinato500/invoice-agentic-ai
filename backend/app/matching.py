from sqlalchemy import select

from backend.app.ai import structured
from backend.app.core.config import settings
from backend.app.models import Line, Match
from backend.app.normalization import identifier
from backend.app.retrieval import candidates
from backend.app.schemas import SemanticDecision


def match_lines(db, run, emit):
    po = list(
        db.scalars(
            select(Line).where(
                Line.document_id == run.po_id,
                Line.organization_id == run.organization_id,
            )
        )
    )
    invoices = list(
        db.scalars(
            select(Line)
            .where(
                Line.document_id.in_(run.invoice_ids),
                Line.organization_id == run.organization_id,
            )
            .order_by(Line.line_no)
        )
    )
    existing = {
        m.invoice_line_id: m for m in db.scalars(select(Match).where(Match.run_id == run.id))
    }
    calls = 0
    for index, inv in enumerate(invoices):
        match = existing.get(inv.id)
        if match and match.reviewed:
            continue
        group = candidates(db, inv, po, run.organization_id, run.po_id)
        exact = [p for p in po if inv.sku and identifier(inv.sku) == identifier(p.sku)]
        selected = None
        status = "UNCERTAIN"
        rationale = "Evidence is insufficient for an automatic correspondence decision."
        if len(exact) == 1:
            selected = exact[0].id
            status = "SAME_PRODUCT"
            rationale = (
                "Unique exact SKU in the selected PO. Specifications are evaluated independently."
            )
        elif len(exact) > 1:
            rationale = (
                "More than one PO line has this identifier; a reviewer must choose the allocation."
            )
        else:
            identical = [
                p
                for p in po
                if p.description.casefold().strip() == inv.description.casefold().strip()
                and (not inv.sku or not p.sku)
            ]
            if len(identical) == 1:
                selected = identical[0].id
                status = "SAME_PRODUCT"
                rationale = "Unique identical description with no contradictory SKU."
            elif not group or group[0]["score"] < 0.45:
                status = "NO_MATCH"
                rationale = (
                    "No candidate has adequate retrieval evidence; no assignment was forced."
                )
            elif settings.ai_configured and calls < settings.max_agent_tool_calls:
                calls += 1
                try:
                    result = structured(
                        "compare_candidates",
                        {
                            "invoice": {
                                "id": inv.id,
                                "description": inv.description,
                                "sku": inv.sku,
                                "attributes": inv.attributes,
                                "evidence": inv.evidence,
                            },
                            "candidates": group,
                            "instruction": "Determine product correspondence separately from configuration compliance. Contradictory identifiers require uncertainty unless source evidence proves equivalence. NO_MATCH is allowed.",
                        },
                        SemanticDecision,
                        emit,
                    )
                    allowed = {c["po_line_id"] for c in group}
                    evidence_ids = {e["element_id"] for e in inv.evidence}
                    for candidate in group:
                        evidence_ids.update(e["element_id"] for e in candidate["evidence"])
                    if result.po_line_id is not None and result.po_line_id not in allowed:
                        raise ValueError(
                            "Model returned a candidate outside the authorized candidate set"
                        )
                    if any(e not in evidence_ids for e in result.evidence_ids):
                        raise ValueError("Model returned invalid evidence ID")
                    if result.correspondence == "SAME_PRODUCT" and not result.evidence_ids:
                        raise ValueError("Model claimed correspondence without source evidence")
                    selected = result.po_line_id
                    status = result.correspondence
                    rationale = result.rationale
                except Exception as exc:
                    emit(
                        "WARNING",
                        "Semantic comparison failed; human review required",
                        {"error": type(exc).__name__, "reason": str(exc)[:400]},
                    )
            else:
                rationale = "AI_CONFIGURATION_REQUIRED or bounded AI budget exhausted; review the retrieved candidates."
        if status in ("DIFFERENT", "NO_MATCH"):
            selected = None
        if not match:
            match = Match(
                organization_id=run.organization_id,
                run_id=run.id,
                invoice_line_id=inv.id,
                identity_status=status,
            )
            db.add(match)
        match.po_line_id = selected
        match.identity_status = status
        match.rationale = rationale
        match.candidates = group
        match.score = next(
            (c["score"] for c in group if c["po_line_id"] == selected),
            group[0]["score"] if group else 0,
        )
        db.commit()
        if index % 20 == 0 or index == len(invoices) - 1:
            emit(
                "PROGRESS",
                "Matched invoice lines",
                {"processed": index + 1, "total": len(invoices), "ai_calls": calls},
            )
