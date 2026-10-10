from sqlalchemy import select

from backend.app.ai import agent
from backend.app.core.config import settings
from backend.app.models import Line, Match
from backend.app.normalization import identifier
from backend.app.reports import serialize
from backend.app.retrieval import candidates
from backend.app.schemas import SemanticDecision
from backend.app.tools import MATCH_TOOLS, dispatch


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
            elif not group:
                status = "NO_MATCH"
                rationale = (
                    "No candidate has adequate retrieval evidence; no assignment was forced."
                )
            elif settings.ai_configured and calls < settings.max_agent_tool_calls:
                calls += 1
                try:

                    def execute(name, args):
                        result = dispatch(
                            db, run.id, name, args.record_id, run.organization_id, args, emit
                        )
                        if name == "search_po_candidates":
                            previous = {c["po_line_id"] for c in group}
                            group.extend(c for c in result if c["po_line_id"] not in previous)
                        return result

                    result = agent(
                        "matching",
                        {
                            "invoice": serialize(inv),
                            "candidates": group,
                            "instruction": "Use tools to inspect invoice and selected candidate source. A SAME_PRODUCT decision must cite evidence from BOTH invoice and the selected PO line. If retrieval wording differs, expand a search through the tool. Do not resolve bundles by forcing one product.",
                        },
                        SemanticDecision,
                        MATCH_TOOLS,
                        execute,
                        emit,
                    )
                    validate_semantic_decision(result, inv, group)
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
        emit(
            "MATCH_DECIDED",
            f"Invoice line {inv.line_no}: {status}",
            {
                "invoice_line_id": inv.id,
                "po_line_id": selected,
                "identity_status": status,
                "output": {
                    "invoice_line": serialize(inv),
                    "candidates": group,
                    "decision": serialize(match),
                },
            },
        )
        if index % 20 == 0 or index == len(invoices) - 1:
            emit(
                "PROGRESS",
                "Matched invoice lines",
                {"processed": index + 1, "total": len(invoices), "ai_calls": calls},
            )


def validate_semantic_decision(result, invoice, group):
    selected = next((c for c in group if c["po_line_id"] == result.po_line_id), None)
    invoice_ids = {e["element_id"] for e in invoice.evidence}
    selected_ids = {e["element_id"] for e in selected["evidence"]} if selected else set()
    allowed = invoice_ids | selected_ids
    if any(e not in allowed for e in result.evidence_ids):
        raise ValueError("Evidence does not belong to the invoice and selected candidate")
    if result.correspondence in ("SAME_PRODUCT", "SAME_FAMILY"):
        if (
            not selected
            or not invoice_ids.intersection(result.evidence_ids)
            or not selected_ids.intersection(result.evidence_ids)
        ):
            raise ValueError(
                "Correspondence requires selected candidate and bilateral source evidence"
            )
    if result.correspondence in ("NO_MATCH", "DIFFERENT") and result.po_line_id is not None:
        raise ValueError("Unmatched decisions cannot carry an allocation candidate")
