import base64
import math

import pymupdf as fitz
from sqlalchemy import select

from backend.app.models import Allocation, Discrepancy, Document, Element, Line, Match, Run
from backend.app.normalization import attributes, identifier, specs, unit
from backend.app.reports import serialize
from backend.app.schemas import AgentArguments, ToolRequest

MATCH_TOOLS = {
    "get_invoice_line": "Read the authorized invoice line by ID.",
    "get_po_line": "Read a candidate PO line and its source evidence by ID.",
    "search_po_candidates": "Search the selected PO for an invoice line; query optionally expands terminology.",
    "get_source_evidence": "Read source evidence for a line, match, element or discrepancy.",
    "get_previous_allocations": "Read prior billed quantities for a PO line.",
    "request_human_review": "Persist an unresolved review request. query is the reason.",
}
SPEC_TOOLS = {
    k: v
    for k, v in MATCH_TOOLS.items()
    if k in {"get_po_line", "get_invoice_line", "get_source_evidence", "request_human_review"}
}
SPEC_TOOLS.update(
    compare_constraints="Run deterministic unit/spec constraints for a match ID.",
    check_approved_substitution="Check actual reviewer substitution authorization for a match ID.",
    check_standard="Read explicitly printed standard identifiers; never invent equivalence.",
)
EXCEPTION_TOOLS = dict(
    MATCH_TOOLS,
    check_po_revision="Inspect the selected PO identity and competing stored revisions.",
    retrieve_alternative_match="Retrieve alternative PO candidates for an invoice line.",
    compare_constraints="Run deterministic specification checks for a match ID.",
)


def render_region(document, page_no, bbox=None):
    if not 1 <= page_no <= document.page_count:
        raise ValueError("Unauthorized page")
    with fitz.open(document.path) as pdf:
        page = pdf[page_no - 1]
        rect = page.rect
        if bbox is not None:
            if len(bbox) != 4 or not all(
                isinstance(v, (int, float)) and math.isfinite(v) for v in bbox
            ):
                raise ValueError("Invalid crop rectangle")
            requested = fitz.Rect(bbox)
            if requested.is_empty or not rect.contains(requested):
                raise ValueError("Crop must stay inside the source page")
            rect = requested
        image = page.get_pixmap(
            matrix=fitz.Matrix(
                min(2, 1800 / max(rect.width, rect.height)),
                min(2, 1800 / max(rect.width, rect.height)),
            ),
            clip=rect,
        )
        return "data:image/png;base64," + base64.b64encode(image.tobytes("png")).decode()


def dispatch(db, run_id, name, record_id, org, args=None, emit=None):
    ToolRequest(name=name, record_id=record_id)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.organization_id == org))
    if not run:
        raise ValueError("Unauthorized run")
    args = args or AgentArguments(record_id=record_id, page=None, bbox=None, query=None)
    docs = [run.po_id] + run.invoice_ids + run.supporting_ids

    def line(id, po=False, invoice=False):
        result = db.scalar(select(Line).where(Line.id == id, Line.organization_id == org))
        allowed = [run.po_id] if po else run.invoice_ids if invoice else docs
        if not result or result.document_id not in allowed:
            raise ValueError("Unauthorized line")
        return result

    def match(id):
        result = db.scalar(
            select(Match).where(
                Match.id == id, Match.run_id == run.id, Match.organization_id == org
            )
        )
        if not result:
            raise ValueError("Unauthorized match")
        return result

    if name in (
        "get_po_line",
        "get_invoice_line",
        "get_candidate_context",
        "extract_attributes",
        "normalize_units",
        "verify_model_identifier",
    ):
        item = line(record_id, po=name == "get_po_line", invoice=name == "get_invoice_line")
        result = serialize(item)
        if name == "extract_attributes":
            result = {"attributes": attributes(item.description), "evidence": item.evidence}
        elif name == "normalize_units":
            result = {"unit": unit(item.unit), "attributes": item.attributes}
        elif name == "verify_model_identifier":
            result = {
                "identifier": identifier(item.sku),
                "attributes": item.attributes,
                "evidence": item.evidence,
            }
    elif name in (
        "search_po_candidates",
        "expand_candidate_search",
        "retrieve_alternative_match",
        "rerank_candidates",
        "lookup_identifier",
    ):
        from types import SimpleNamespace

        from backend.app.retrieval import candidates

        inv = line(record_id, invoice=True)
        po = list(
            db.scalars(
                select(Line).where(Line.document_id == run.po_id, Line.organization_id == org)
            )
        )
        query_line = SimpleNamespace(
            description=(args.query or inv.description)[:2000], sku=inv.sku
        )
        result = candidates(db, query_line, po, org, run.po_id, k=12)
    elif name == "get_source_evidence":
        item = db.scalar(
            select(Line).where(
                Line.id == record_id, Line.organization_id == org, Line.document_id.in_(docs)
            )
        )
        if item:
            result = item.evidence
        else:
            item = db.scalar(
                select(Element).where(
                    Element.id == record_id,
                    Element.organization_id == org,
                    Element.document_id.in_(docs),
                )
            )
            if item:
                result = [serialize(item)]
            else:
                item = db.scalar(
                    select(Match).where(
                        Match.id == record_id, Match.run_id == run.id, Match.organization_id == org
                    )
                )
                if item:
                    result = line(item.invoice_line_id).evidence + (
                        line(item.po_line_id).evidence if item.po_line_id else []
                    )
                else:
                    item = db.scalar(
                        select(Discrepancy).where(
                            Discrepancy.id == record_id,
                            Discrepancy.run_id == run.id,
                            Discrepancy.organization_id == org,
                        )
                    )
                    if not item:
                        raise ValueError("Unauthorized evidence ID")
                    result = item.evidence
    elif name == "get_previous_allocations":
        item = line(record_id, po=True)
        result = [
            serialize(a)
            for a in db.scalars(
                select(Allocation).where(
                    Allocation.po_line_id == item.id,
                    Allocation.organization_id == org,
                    Allocation.run_id != run.id,
                )
            )
        ]
        result = (
            []
            if run.policy.get("evaluation_id")
            else [a for a in result if not db.get(Run, a["run_id"]).policy.get("evaluation_id")]
        )
    elif name in ("compare_constraints", "check_approved_substitution", "propose_match"):
        item = match(record_id)
        if name == "check_approved_substitution":
            result = {
                "approved": bool(item.reviewed and item.review_action == "substitution"),
                "action": item.review_action,
            }
        elif item.po_line_id:
            status, findings = specs(
                line(item.po_line_id),
                line(item.invoice_line_id),
                item.review_action == "substitution",
            )
            result = {"status": status, "findings": findings}
        else:
            result = {"status": "UNKNOWN", "reason": "No verified mapping"}
    elif name in (
        "get_document_page",
        "render_page",
        "crop_region",
        "inspect_extracted_table",
        "check_standard",
        "check_po_revision",
        "propose_correction",
    ):
        doc = db.scalar(
            select(Document).where(
                Document.id == record_id, Document.id.in_(docs), Document.organization_id == org
            )
        )
        if not doc:
            # check_standard may inspect line evidence instead of a whole document.
            if name == "check_standard":
                result = {
                    "printed_source": line(record_id).evidence,
                    "equivalence": "Not established by any external standard registry",
                }
            else:
                raise ValueError("Unauthorized document")
        elif name in ("render_page", "crop_region"):
            result = {
                "document_id": doc.id,
                "page": args.page or 1,
                "image_url": render_region(doc, args.page or 1, args.bbox),
            }
        elif name == "check_po_revision":
            header = doc.extraction.get("header", {})
            related = [
                serialize(d)
                for d in db.scalars(
                    select(Document).where(Document.organization_id == org, Document.kind == "po")
                )
                if d.extraction.get("header", {}).get("number") == header.get("number")
                and d.extraction.get("header", {}).get("supplier") == header.get("supplier")
            ]
            result = {
                "selected": serialize(doc),
                "same_number_documents": related,
                "automatic_revision_authorization": False,
            }
        elif name == "propose_correction":
            result = {
                "status": "PROPOSAL_ONLY",
                "document_id": doc.id,
                "reason": args.query,
                "requires_human_verification": True,
            }
        else:
            page = args.page or 1
            if not 1 <= page <= doc.page_count:
                raise ValueError("Unauthorized page")
            result = {
                "document": serialize(doc),
                "elements": [
                    serialize(e)
                    for e in db.scalars(
                        select(Element).where(
                            Element.document_id == doc.id,
                            Element.page == page,
                            Element.organization_id == org,
                        )
                    )
                ],
            }
    else:
        authorized = record_id in [run.id] + docs
        authorized = (
            authorized
            or db.scalar(
                select(Line.id).where(
                    Line.id == record_id, Line.organization_id == org, Line.document_id.in_(docs)
                )
            )
            is not None
        )
        authorized = (
            authorized
            or db.scalar(
                select(Match.id).where(
                    Match.id == record_id, Match.organization_id == org, Match.run_id == run.id
                )
            )
            is not None
        )
        authorized = (
            authorized
            or db.scalar(
                select(Discrepancy.id).where(
                    Discrepancy.id == record_id,
                    Discrepancy.organization_id == org,
                    Discrepancy.run_id == run.id,
                )
            )
            is not None
        )
        if not authorized:
            raise ValueError("Unauthorized review record")
        requests = list(run.policy.get("agent_review_requests", []))
        item = {
            "record_id": record_id,
            "reason": (args.query or "Unresolved agent investigation")[:2000],
            "version": run.version,
        }
        if item not in requests:
            requests.append(item)
        run.policy = {**run.policy, "agent_review_requests": requests}
        db.commit()
        result = {"status": "REVIEW_REQUIRED", **item}
    if emit is None:
        from backend.app.workflow import emit as workflow_emit

        workflow_emit(
            run.id,
            "INVESTIGATING_EXCEPTIONS",
            "TOOL_COMPLETED",
            name,
            {"tool": name, "record_id": record_id, "output": result},
        )
    return result
