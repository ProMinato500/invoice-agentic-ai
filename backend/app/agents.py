from sqlalchemy import select

from backend.app.ai import agent
from backend.app.core.config import settings
from backend.app.models import Discrepancy, Line, Match, Run
from backend.app.normalization import specs
from backend.app.reports import serialize
from backend.app.schemas import Investigation
from backend.app.tools import EXCEPTION_TOOLS, SPEC_TOOLS, dispatch


def investigate(db, run, role, context, toolset, emit):
    def execute(name, args):
        return dispatch(db, run.id, name, args.record_id, run.organization_id, args, emit)

    try:
        result = agent(role, context, Investigation, toolset, execute, emit)
        allowed = {
            e["element_id"]
            for line in db.scalars(
                select(Line).where(
                    Line.organization_id == run.organization_id,
                    Line.document_id.in_([run.po_id] + run.invoice_ids),
                )
            )
            for e in line.evidence
        }
        if any(i not in allowed for i in result.evidence_ids):
            raise ValueError("Invalid investigation evidence IDs")
        if result.status == "SUPPORTED" and not result.evidence_ids:
            raise ValueError("Unsupported investigation conclusion")
        output = result.model_dump(mode="json")
    except Exception as exc:
        output = {
            "status": "UNRESOLVED",
            "evidence_ids": [],
            "rationale": type(exc).__name__,
            "recommended_action": "Human review required; no rules overridden.",
        }
        emit("WARNING", role + " investigation unresolved", {"error": type(exc).__name__})
    emit("INVESTIGATION_COMPLETED", role + " assessment available", {"output": output})
    return output


def specification_stage(run_id, emit):
    from backend.app.db import Session

    with Session() as db:
        run = db.get(Run, run_id)
        matches = list(db.scalars(select(Match).where(Match.run_id == run.id)))
        uncertain = []
        results = []
        for match in matches:
            inv = db.get(Line, match.invoice_line_id)
            po = db.get(Line, match.po_line_id) if match.po_line_id else None
            status, findings = (
                specs(po, inv, match.review_action == "substitution") if po else ("UNKNOWN", [])
            )
            match.spec_status = status
            results.append(
                {
                    "match_id": match.id,
                    "status": status,
                    "findings": findings,
                    "po_line": serialize(po) if po else None,
                    "invoice_line": serialize(inv),
                }
            )
            if status == "UNKNOWN" and po:
                uncertain.append(results[-1])
        db.commit()
        emit(
            "SPECIFICATIONS_CHECKED",
            "Technical constraints evaluated",
            {"count": len(results), "output": results},
        )
        if settings.ai_configured and uncertain:
            enrich_specifications(db, run, uncertain[:8], emit)


def exception_stage(run_id, emit):
    from backend.app.db import Session

    with Session() as db:
        run = db.get(Run, run_id)
        findings = list(db.scalars(select(Discrepancy).where(Discrepancy.run_id == run.id)))
        if settings.ai_configured:
            assessment = investigate(
                db,
                run,
                "exception",
                {
                    "run_id": run.id,
                    "po_id": run.po_id,
                    "findings": [serialize(d) for d in findings[:12]],
                    "matches": [
                        serialize(m)
                        for m in db.scalars(select(Match).where(Match.run_id == run.id)).all()[:12]
                    ],
                    "instruction": "Investigate the findings with appropriate source/prior allocation/revision tools. Give a short evidence-based explanation and next action. If uncertainty remains, call request_human_review. Never override deterministic financial failures.",
                },
                EXCEPTION_TOOLS,
                emit,
            )
            run.policy = {**run.policy, "exception_assessment": assessment}
            db.commit()
        else:
            emit(
                "REVIEW_REQUIRED",
                "AI not configured; discrepancies remain available for human review",
                {"count": len(findings)},
            )


def source_reinspection_stage(run_id, emit):
    from backend.app.ai import structured
    from backend.app.db import Session
    from backend.app.models import Document, Element, uid
    from backend.app.schemas import RecoveredPage
    from backend.app.tools import render_region

    with Session() as db:
        run = db.get(Run, run_id)
        request = run.policy.get("source_reinspection")
        if not request or request.get("version") != run.version:
            return
        doc = db.get(Document, request["document_id"])
        source = list(
            db.scalars(
                select(Element).where(
                    Element.document_id == doc.id,
                    Element.page == request["page"],
                    Element.organization_id == run.organization_id,
                )
            )
        )
        region_id = uid()
        reading = structured(
            "targeted_vision_recovery",
            {
                "document_id": doc.id,
                "page": request["page"],
                "region_evidence_id": region_id,
                "source_elements": [{"id": e.id, "text": e.raw_text} for e in source],
                "instruction": "Inspect the image and return printed rows/header fields with field citations. Cite source IDs or region_evidence_id. Missing values are null. This is an alternative reading for review, not an approved canonical correction.",
            },
            RecoveredPage,
            emit,
            images=[render_region(doc, request["page"], request.get("bbox"))],
        )
        allowed = {e.id for e in source} | {region_id}
        if any(i not in allowed for f in reading.header for i in f.evidence_ids) or any(
            i not in allowed
            for row in reading.rows
            for i in row.evidence_ids + [i for f in row.fields for i in f.evidence_ids]
        ):
            raise ValueError("Invalid vision source IDs")
        output = {
            "document_id": doc.id,
            "page": request["page"],
            "bbox": request.get("bbox"),
            "reading": reading.model_dump(mode="json"),
            "method": "OPENAI_VISION_ALTERNATIVE",
            "verification_status": "REVIEW_REQUIRED",
            "canonical_changed": False,
        }
        readings = list(run.policy.get("source_readings", [])) + [output]
        run.policy = {**run.policy, "source_readings": readings}
        db.commit()
        emit(
            "VISION_RESULT",
            "Source image reading available for human verification",
            {"document_id": doc.id, "output": output},
        )


def enrich_specifications(db, run, uncertain, emit):
    import re

    from backend.app.normalization import identifier
    from backend.app.schemas import SpecificationAnalysis

    selected = {row["match_id"]: row for row in uncertain}

    def execute(name, args):
        return dispatch(db, run.id, name, args.record_id, run.organization_id, args, emit)

    try:
        result = agent(
            "specification",
            {
                "matches": uncertain,
                "instruction": "Inspect the printed source using tools. Extract named technical attributes separately for each PO/invoice line, with field-level evidence IDs. Preserve original printed values. Identify comparison operators only when explicitly printed (minimum/maximum/at least/at most). Do not infer missing attributes or certificates. Never treat similar product identity as specification compliance.",
            },
            SpecificationAnalysis,
            SPEC_TOOLS,
            execute,
            emit,
        )
        updates = []
        for row in result.rows:
            if row.match_id not in selected:
                raise ValueError("Unauthorized specification match ID")
            context = selected[row.match_id]
            for key, items in (
                ("po_line", row.po_attributes),
                ("invoice_line", row.invoice_attributes),
            ):
                line = db.get(Line, context[key]["id"])
                evidence = {e["element_id"]: e["raw_text"] for e in line.evidence}
                attrs = dict(line.attributes)
                for item in items:
                    if not item.evidence_ids or any(i not in evidence for i in item.evidence_ids):
                        raise ValueError("Unauthorized specification field citation")
                    source = " ".join(evidence[i] for i in item.evidence_ids)
                    if not identifier(item.value) or identifier(item.value) not in identifier(
                        source
                    ):
                        continue
                    if item.operator in {"GTE", "GT"} and not re.search(
                        r"at least|minimum|greater than|>=|>", source, re.I
                    ):
                        continue
                    if item.operator in {"LTE", "LT"} and not re.search(
                        r"at most|maximum|less than|<=|<", source, re.I
                    ):
                        continue
                    if item.operator in {"NEQ", "MANDATORY_FEATURE"}:
                        continue  # Require a reviewed policy for negation/feature semantics.
                    # Preserve previously extracted attributes; add source-grounded missing facts.
                    if item.name not in attrs:
                        attrs[item.name] = (
                            {
                                "value": item.value,
                                "operator": item.operator,
                                "evidence_ids": item.evidence_ids,
                                "method": "AI_SOURCE_GROUNDED",
                            }
                            if key == "po_line"
                            else item.value
                        )
                        updates.append({"line_id": line.id, **item.model_dump(mode="json")})
                if attrs != line.attributes:
                    line.flags = list(
                        dict.fromkeys(line.flags + ["AI_SPECIFICATION_REQUIRES_REVIEW"])
                    )
                line.attributes = attrs
        run.policy = {
            **run.policy,
            "specification_assessment": result.model_dump(mode="json"),
            "specification_field_updates": updates,
        }
        db.commit()
        emit(
            "SPECIFICATION_ATTRIBUTES",
            "Source-grounded technical attributes extracted",
            {"output": result.model_dump(mode="json"), "updates": updates},
        )
    except Exception as exc:
        db.rollback()
        emit(
            "WARNING",
            "Specification extraction unresolved; deterministic constraints require review",
            {"error": type(exc).__name__},
        )
