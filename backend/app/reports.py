import csv
import json
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.models import Discrepancy, Document, Line, Match, Review


def serialize(obj):
    return {
        c.name: getattr(obj, c.name)
        for c in obj.__table__.columns
        if c.name not in ("path", "organization_id")
    }


def build_reports(db, run):
    matches = list(db.scalars(select(Match).where(Match.run_id == run.id)))
    issues = list(db.scalars(select(Discrepancy).where(Discrepancy.run_id == run.id)))
    reviews = list(db.scalars(select(Review).where(Review.run_id == run.id)))
    documents = list(
        db.scalars(
            select(Document).where(
                Document.id.in_([run.po_id] + run.invoice_ids + run.supporting_ids)
            )
        )
    )
    folder = settings.storage / "reports" / run.id / str(run.version)
    folder.mkdir(parents=True, exist_ok=True)
    run_snapshot = serialize(run)
    run_snapshot["status"] = (
        "WAITING_FOR_REVIEW"
        if run.outcome == "REVIEW_REQUIRED"
        else "COMPLETED_WITH_DISCREPANCIES"
        if run.outcome == "BLOCKED"
        else "COMPLETED"
    )
    payload = {
        "run": run_snapshot,
        "documents": [serialize(d) for d in documents],
        "matches": [serialize(m) for m in matches],
        "lines": [
            serialize(line)
            for line in db.scalars(
                select(Line).where(
                    Line.document_id.in_([run.po_id] + run.invoice_ids + run.supporting_ids)
                )
            )
        ],
        "discrepancies": [serialize(d) for d in issues],
        "reviews": [serialize(r) for r in reviews],
    }
    (folder / "report.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    with (folder / "discrepancies.csv").open("w", newline="", encoding="utf-8-sig") as out:
        writer = csv.writer(out)
        writer.writerow(["run_id", "match_id", "code", "severity", "message"])
        for d in issues:

            def safe(v):
                s = str(v or "")
                return "'" + s if s.startswith(("=", "+", "-", "@")) else s

            writer.writerow([safe(v) for v in [run.id, d.match_id, d.code, d.severity, d.message]])
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Small",
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#64748b"),
        )
    )
    document = SimpleDocTemplate(
        str(folder / "report.pdf"),
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    story = [
        Paragraph("ReconcileAI - Reconciliation Report", styles["Title"]),
        Spacer(1, 12),
        Paragraph(escape(run.id), styles["Normal"]),
        Paragraph(f"Outcome: {run.outcome}", styles["Heading2"]),
        Paragraph(
            f"Policy version: {run.summary.get('policy_version', 1)} | Result version: {run.version}",
            styles["Normal"],
        ),
        Spacer(1, 10),
    ]
    for d in documents:
        h = d.extraction.get("header", {})
        story.append(
            Paragraph(
                escape(
                    f"{d.kind.upper()}: {d.name} | {h.get('number') or 'identity not extracted'} | {d.sha256[:16]}"
                ),
                styles["Normal"],
            )
        )
    story.append(Spacer(1, 14))
    story.append(
        Paragraph(
            escape(
                f"{len(matches)} invoice lines; {run.summary.get('matched', 0)} mapped; {len(issues)} discrepancies."
            ),
            styles["Normal"],
        )
    )
    for m in matches:
        inv = db.get(Line, m.invoice_line_id)
        po = db.get(Line, m.po_line_id) if m.po_line_id else None
        story += [
            Spacer(1, 10),
            Paragraph(
                escape(f"Invoice line {inv.line_no}: {inv.description}"),
                styles["Heading3"],
            ),
            Paragraph(escape(f"PO: {po.description if po else 'Unmatched'}"), styles["Normal"]),
            Paragraph(
                escape(
                    f"Identity {m.identity_status}; specifications {m.spec_status}; quantity {m.quantity_status}; price {m.price_status}"
                ),
                styles["Normal"],
            ),
            Paragraph(escape(m.rationale), styles["Normal"]),
        ]
        for evidence in inv.evidence[:2] + (po.evidence[:2] if po else []):
            story.append(
                Paragraph(
                    escape(
                        f"Source {evidence['document_id']}, page {evidence['page']}, rectangle {evidence['bbox']}: {evidence['raw_text']}"
                    ),
                    styles["Small"],
                )
            )
    if issues:
        story += [Spacer(1, 16), Paragraph("Discrepancies", styles["Heading2"])]
        for d in issues:
            story.append(
                Paragraph(escape(f"{d.code} ({d.severity}): {d.message}"), styles["Normal"])
            )
    if reviews:
        story += [
            Spacer(1, 16),
            Paragraph("Audited reviewer actions", styles["Heading2"]),
        ]
        for r in reviews:
            story.append(
                Paragraph(
                    escape(f"{r.created_at} | {r.actor} | {r.action}: {r.note}"),
                    styles["Normal"],
                )
            )
    document.build(story)
    return str(folder)
