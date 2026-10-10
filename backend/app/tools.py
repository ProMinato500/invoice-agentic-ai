from sqlalchemy import select

from backend.app.models import Allocation, Discrepancy, Line, Match, Run
from backend.app.reports import serialize
from backend.app.schemas import ToolRequest
from backend.app.workflow import emit


def dispatch(db, run_id, name, record_id, org):
    ToolRequest(name=name, record_id=record_id)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.organization_id == org))
    if not run:
        raise ValueError("Unauthorized run")
    if name in ("get_po_line", "get_invoice_line"):
        line = db.scalar(select(Line).where(Line.id == record_id, Line.organization_id == org))
        allowed = [run.po_id] if name == "get_po_line" else run.invoice_ids
        if not line or line.document_id not in allowed:
            raise ValueError("Unauthorized line ID")
        result = serialize(line)
    elif name == "get_source_evidence":
        match = db.scalar(
            select(Match).where(
                Match.id == record_id,
                Match.run_id == run.id,
                Match.organization_id == org,
            )
        )
        if match:
            inv = db.get(Line, match.invoice_line_id)
            po = db.get(Line, match.po_line_id) if match.po_line_id else None
            result = inv.evidence + (po.evidence if po else [])
        else:
            discrepancy = db.scalar(
                select(Discrepancy).where(
                    Discrepancy.id == record_id,
                    Discrepancy.run_id == run.id,
                    Discrepancy.organization_id == org,
                )
            )
            if not discrepancy:
                raise ValueError("Unauthorized evidence ID")
            result = discrepancy.evidence
    elif name == "get_previous_allocations":
        line = db.scalar(
            select(Line).where(
                Line.id == record_id,
                Line.document_id == run.po_id,
                Line.organization_id == org,
            )
        )
        if not line:
            raise ValueError("Unauthorized PO line")
        result = [
            serialize(a)
            for a in db.scalars(
                select(Allocation).where(
                    Allocation.po_line_id == line.id, Allocation.organization_id == org
                )
            )
        ]
    else:
        result = {"status": "REVIEW_REQUIRED", "run_id": run.id}
    emit(
        run.id,
        "INVESTIGATING_EXCEPTIONS",
        "TOOL_COMPLETED",
        name,
        {
            "tool": name,
            "record_id": record_id,
            "result_count": len(result) if isinstance(result, list) else 1,
        },
    )
    return result
