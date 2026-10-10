import asyncio
import json
import time
from datetime import datetime
from typing import Literal

import pymupdf as fitz
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import settings
from backend.app.db import Session
from backend.app.models import (
    Allocation,
    Discrepancy,
    Document,
    Element,
    Evaluation,
    Event,
    Line,
    Match,
    Review,
    Run,
    now,
)
from backend.app.normalization import attributes, number
from backend.app.reports import serialize
from backend.app.schemas import (
    CorrectionRequest,
    EvaluationCreate,
    ReviewRequest,
    RunCreate,
)
from backend.app.storage import store_pdf
from backend.app.workflow import TERMINAL, emit
from synthetic_data.__main__ import ROOT as SCENARIOS_ROOT


def db_session():
    with Session() as db:
        yield db


def auth(request: Request):
    if (
        settings.api_token
        and request.headers.get("authorization") != "Bearer " + settings.api_token
    ):
        raise HTTPException(401, "Bearer token required")
    return settings.organization_id


def owned(db, model, id, org):
    value = db.scalar(select(model).where(model.id == id, model.organization_id == org))
    if value is None:
        raise HTTPException(404, "Record not found")
    return value


def queue(db, run):
    if run.status in ("QUEUED", "PROCESSING"):
        raise HTTPException(409, "Run is already queued or processing")
    db.execute(delete(Allocation).where(Allocation.run_id == run.id))
    run.status = "QUEUED"
    run.outcome = "INCOMPLETE"
    run.error = None
    run.cancel_requested = 0
    run.version += 1
    run.started_at = None
    run.finished_at = None
    db.commit()
    emit(run.id, "UPLOADED", "QUEUED", "Recalculation queued", {"version": run.version})


app = FastAPI(
    title="ReconcileAI",
    version="0.1.0",
    description="Local PDF purchase order / invoice reconciliation. Real extraction, conservative matching, audited review and deterministic monetary checks.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
)


@app.middleware("http")
async def local_origin(request, call_next):
    origin = request.headers.get("origin")
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and origin
        and origin not in settings.cors_origins.split(",")
    ):
        return Response("Origin is not authorized", status_code=403)
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(db=Depends(db_session)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "Database unavailable")
    heartbeat = settings.storage / "worker-heartbeat"
    alive = (
        heartbeat.exists()
        and time.time() - heartbeat.stat().st_mtime < settings.job_timeout_seconds
    )
    return {
        "database": "connected",
        "database_backend": db.bind.dialect.name,
        "worker": "available" if alive else "not_running",
        "ai": "configured" if settings.ai_configured else "configuration_required",
        "parser": settings.parser,
        "pipeline": settings.docling_pipeline,
        "mode": "local_single_user",
        "embeddings": settings.enable_embeddings,
    }


@app.get("/api/settings")
def configuration(org=Depends(auth)):
    return {
        "mode": "Local single-user workspace",
        "database": settings.database_url.split(":")[0],
        "parser": settings.parser,
        "pipeline": settings.docling_pipeline,
        "ai_configured": settings.ai_configured,
        "provider": "Azure OpenAI"
        if settings.invoice_azure_api_key
        else "OpenAI"
        if settings.openai_api_key
        else "Unconfigured",
        "model": settings.invoice_azure_deployment or settings.openai_model,
        "max_upload_mb": settings.max_upload_mb,
        "max_pages": settings.max_pages,
        "price_tolerance_percent": settings.default_price_tolerance_percent,
        "embedding_enabled": settings.enable_embeddings,
        "api_docs": "http://127.0.0.1:8010/docs",
        "retention": "Documents retained locally until removed by the workspace owner. No automatic deletion.",
    }


@app.post("/api/documents/upload", status_code=201)
async def upload(
    file: UploadFile = File(...),
    kind: Literal["po", "invoice", "receipt", "amendment", "specification"] = Form(...),
    db=Depends(db_session),
    org=Depends(auth),
):
    # Bounded read prevents an arbitrarily large multipart body from entering memory.
    content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    doc, duplicate = store_pdf(db, content, file.filename or "document.pdf", kind, org)
    return {**serialize(doc), "duplicate": duplicate}


@app.get("/api/documents")
def documents(
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = "",
    db=Depends(db_session),
    org=Depends(auth),
):
    stmt = select(Document).where(Document.organization_id == org)
    if q:
        stmt = stmt.where(Document.name.ilike("%" + q + "%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [serialize(d) for d in rows], "total": total}


@app.get("/api/documents/{id}")
def document(id: str, db=Depends(db_session), org=Depends(auth)):
    return serialize(owned(db, Document, id, org))


@app.get("/api/documents/{id}/file")
def document_file(id: str, db=Depends(db_session), org=Depends(auth)):
    doc = owned(db, Document, id, org)
    return FileResponse(
        doc.path,
        media_type="application/pdf",
        filename=doc.name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/documents/{id}/pages")
def pages(id: str, db=Depends(db_session), org=Depends(auth)):
    doc = owned(db, Document, id, org)
    with fitz.open(doc.path) as pdf:
        return {
            "items": [
                {
                    "page": i + 1,
                    "width": p.rect.width,
                    "height": p.rect.height,
                    "rotation": p.rotation,
                }
                for i, p in enumerate(pdf)
            ]
        }


@app.get("/api/documents/{id}/pages/{page}/image")
def page_image(id: str, page: int, db=Depends(db_session), org=Depends(auth)):
    doc = owned(db, Document, id, org)
    if not 1 <= page <= doc.page_count:
        raise HTTPException(404, "Page not found")
    with fitz.open(doc.path) as pdf:
        return Response(
            pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).tobytes("png"),
            media_type="image/png",
        )


@app.get("/api/documents/{id}/elements")
def elements(
    id: str,
    page: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    org=Depends(auth),
):
    owned(db, Document, id, org)
    stmt = select(Element).where(Element.document_id == id, Element.organization_id == org)
    if page:
        stmt = stmt.where(Element.page == page)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {
        "items": [
            serialize(e)
            for e in db.scalars(
                stmt.order_by(Element.page, Element.created_at).offset(offset).limit(limit)
            )
        ],
        "total": total,
    }


@app.get("/api/documents/{id}/lines")
def doc_lines(
    id: str,
    q: str = "",
    limit: int = Query(100, ge=1, le=500),
    db=Depends(db_session),
    org=Depends(auth),
):
    owned(db, Document, id, org)
    stmt = select(Line).where(Line.document_id == id, Line.organization_id == org)
    if q:
        stmt = stmt.where(Line.description.ilike("%" + q + "%"))
    return {
        "items": [serialize(line) for line in db.scalars(stmt.order_by(Line.line_no).limit(limit))]
    }


@app.post("/api/reconciliations", status_code=201)
def create_run(body: RunCreate, db=Depends(db_session), org=Depends(auth)):
    if body.idempotency_key:
        previous = db.scalar(
            select(Run).where(
                Run.organization_id == org, Run.idempotency_key == body.idempotency_key
            )
        )
        if previous:
            return serialize(previous)
    po = owned(db, Document, body.po_id, org)
    if po.kind != "po":
        raise HTTPException(422, "Select a purchase order document")
    if len(set(body.invoice_ids)) != len(body.invoice_ids):
        raise HTTPException(422, "The same invoice cannot appear twice in one run")
    for id in body.invoice_ids:
        if owned(db, Document, id, org).kind != "invoice":
            raise HTTPException(422, "Invoice role required")
    for id in body.supporting_ids:
        owned(db, Document, id, org)
    run = Run(
        organization_id=org,
        po_id=body.po_id,
        invoice_ids=body.invoice_ids,
        supporting_ids=body.supporting_ids,
        idempotency_key=body.idempotency_key,
        policy={
            "price_tolerance_percent": str(body.price_tolerance_percent),
            "rounding_tolerance": settings.rounding_tolerance,
            "version": 1,
        },
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if body.idempotency_key:
            previous = db.scalar(
                select(Run).where(
                    Run.organization_id == org,
                    Run.idempotency_key == body.idempotency_key,
                )
            )
            if previous:
                return serialize(previous)
        raise HTTPException(
            409, "A concurrent request created this run; refresh before retrying"
        ) from exc
    emit(
        run.id,
        "UPLOADED",
        "QUEUED",
        "Documents stored; reconciliation queued",
        {"document_count": 1 + len(body.invoice_ids) + len(body.supporting_ids)},
    )
    return serialize(run)


@app.get("/api/reconciliations")
def runs(
    review_only: bool = False,
    status: str | None = None,
    q: str = "",
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    org=Depends(auth),
):
    stmt = select(Run).where(Run.organization_id == org)
    if review_only:
        stmt = stmt.where(Run.outcome.in_(["BLOCKED", "REVIEW_REQUIRED"]))
    if status:
        stmt = stmt.where(Run.status == status)
    if q:
        stmt = stmt.where(Run.id.ilike("%" + q + "%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {
        "items": [
            serialize(r)
            for r in db.scalars(stmt.order_by(Run.created_at.desc()).offset(offset).limit(limit))
        ],
        "total": total,
    }


@app.get("/api/reconciliations/{id}")
def run_details(id: str, db=Depends(db_session), org=Depends(auth)):
    run = owned(db, Run, id, org)
    result = serialize(run)
    result["documents"] = [
        serialize(owned(db, Document, d, org))
        for d in [run.po_id] + run.invoice_ids + run.supporting_ids
    ]
    result["report_available"] = (
        settings.storage / "reports" / run.id / str(run.version) / "report.json"
    ).exists()
    return result


@app.get("/api/reconciliations/{id}/events")
def events(id: str, after: int = 0, db=Depends(db_session), org=Depends(auth)):
    owned(db, Run, id, org)
    return {
        "items": [
            serialize(e)
            for e in db.scalars(
                select(Event)
                .where(
                    Event.run_id == id,
                    Event.organization_id == org,
                    Event.sequence > after,
                )
                .order_by(Event.sequence)
                .limit(1000)
            )
        ]
    }


@app.get("/api/reconciliations/{id}/stream")
async def stream(id: str, request: Request, after: int = 0, org=Depends(auth)):
    with Session() as db:
        owned(db, Run, id, org)
    try:
        cursor = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        raise HTTPException(422, "Invalid event cursor")

    async def feed():
        nonlocal cursor
        while not await request.is_disconnected():
            with Session() as db:
                rows = list(
                    db.scalars(
                        select(Event)
                        .where(
                            Event.run_id == id,
                            Event.organization_id == org,
                            Event.sequence > cursor,
                        )
                        .order_by(Event.sequence)
                        .limit(500)
                    )
                )
                state = owned(db, Run, id, org).status
                payloads = [serialize(e) for e in rows]
            for payload in payloads:
                cursor = payload["sequence"]
                yield f"id: {cursor}\ndata: {json.dumps(payload, default=str)}\n\n"
            if state in TERMINAL:
                yield "event: settled\ndata: {}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        feed(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/reconciliations/{id}/matches")
def matches(
    id: str,
    q: str = "",
    status: str | None = None,
    sort: Literal["line", "score"] = "line",
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    org=Depends(auth),
):
    owned(db, Run, id, org)
    stmt = (
        select(Match)
        .join(Line, Match.invoice_line_id == Line.id)
        .where(Match.run_id == id, Match.organization_id == org)
    )
    if q:
        stmt = stmt.where(Line.description.ilike("%" + q + "%"))
    if status:
        stmt = stmt.where(Match.spec_status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(Match.score.desc() if sort == "score" else Line.line_no)
    rows = []
    for m in db.scalars(stmt.offset(offset).limit(limit)):
        data = serialize(m)
        data["invoice_line"] = serialize(db.get(Line, m.invoice_line_id))
        data["po_line"] = serialize(db.get(Line, m.po_line_id)) if m.po_line_id else None
        rows.append(data)
    return {"items": rows, "total": total}


@app.get("/api/reconciliations/{id}/discrepancies")
def discrepancies(id: str, db=Depends(db_session), org=Depends(auth)):
    owned(db, Run, id, org)
    return {
        "items": [
            serialize(d)
            for d in db.scalars(
                select(Discrepancy).where(
                    Discrepancy.run_id == id, Discrepancy.organization_id == org
                )
            )
        ]
    }


@app.get("/api/reconciliations/{id}/report")
def download_report(
    id: str,
    format: Literal["pdf", "csv", "json"] = "pdf",
    db=Depends(db_session),
    org=Depends(auth),
):
    run = owned(db, Run, id, org)
    filename = "discrepancies.csv" if format == "csv" else "report." + format
    path = settings.storage / "reports" / id / str(run.version) / filename
    if not path.exists():
        raise HTTPException(409, "Report is not ready for this result version")
    return FileResponse(
        path,
        media_type={
            "pdf": "application/pdf",
            "csv": "text/csv",
            "json": "application/json",
        }[format],
        filename=f"reconcile-{id[:8]}-v{run.version}.{format}",
    )


@app.post("/api/reconciliations/{id}/retry")
def retry(id: str, db=Depends(db_session), org=Depends(auth)):
    run = owned(db, Run, id, org)
    if run.status not in ("FAILED", "CANCELLED"):
        raise HTTPException(409, "Only failed or cancelled runs can be retried")
    queue(db, run)
    return serialize(run)


@app.post("/api/reconciliations/{id}/recalculate")
def recalculate(id: str, db=Depends(db_session), org=Depends(auth)):
    run = owned(db, Run, id, org)
    queue(db, run)
    return serialize(run)


@app.post("/api/reconciliations/{id}/cancel")
def cancel(id: str, db=Depends(db_session), org=Depends(auth)):
    run = owned(db, Run, id, org)
    if run.status not in ("QUEUED", "PROCESSING"):
        raise HTTPException(409, "Only active runs can be cancelled")
    run.cancel_requested = 1
    if run.status == "QUEUED":
        run.status = "CANCELLED"
        run.finished_at = now()
    db.commit()
    return serialize(run)


@app.post("/api/matches/{id}/review")
def review(id: str, body: ReviewRequest, db=Depends(db_session), org=Depends(auth)):
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    match = owned(db, Match, id, org)
    run = owned(db, Run, match.run_id, org)
    if run.status in ("QUEUED", "PROCESSING"):
        raise HTTPException(409, "Wait for processing to finish before reviewing")
    if match.version != body.version:
        raise HTTPException(409, "This result has changed; refresh before reviewing")
    before = serialize(match)
    if body.action in ("remap", "substitution"):
        if not body.po_line_id:
            raise HTTPException(422, "Select a PO line")
        line = owned(db, Line, body.po_line_id, org)
        if line.document_id != run.po_id:
            raise HTTPException(422, "PO line belongs to a different purchase order")
        match.po_line_id = line.id
    if body.action in ("reject", "unmatched"):
        match.po_line_id = None
        match.identity_status = "NO_MATCH"
    else:
        if not match.po_line_id:
            raise HTTPException(422, "Select a mapping before accepting")
        match.identity_status = "SAME_PRODUCT"
    match.reviewed = 1
    match.review_action = body.action
    match.version += 1
    match.rationale = "Reviewer " + body.action + ": " + body.note
    db.add(
        Review(
            organization_id=org,
            run_id=run.id,
            match_id=match.id,
            actor="local_workspace_owner",
            action=body.action,
            before=before,
            after=serialize(match),
            note=body.note,
        )
    )
    db.commit()
    queue(db, run)
    return {"match": serialize(match), "run": serialize(run)}


@app.post("/api/elements/{id}/correct")
def correct(id: str, body: CorrectionRequest, db=Depends(db_session), org=Depends(auth)):
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    element = owned(db, Element, id, org)
    if element.version != body.version:
        raise HTTPException(409, "Evidence changed; refresh first")
    if not body.line_id or not body.field:
        raise HTTPException(422, "Select a line and canonical field for this correction")
    line = owned(db, Line, body.line_id, org)
    if line.document_id != element.document_id or id not in [
        e["element_id"] for e in line.evidence
    ]:
        raise HTTPException(422, "Evidence does not support the selected line")
    active = list(
        db.scalars(
            select(Run).where(Run.organization_id == org, Run.status.in_(["QUEUED", "PROCESSING"]))
        )
    )
    if any(element.document_id in [r.po_id] + r.invoice_ids for r in active):
        raise HTTPException(409, "Wait for dependent processing to finish")
    before = {
        "value": str(getattr(line, body.field)),
        "normalized_value": element.normalized_value,
        "version": element.version,
    }
    if body.field in ("quantity", "unit_price", "amount"):
        try:
            value = number(body.value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    else:
        value = body.value
    setattr(line, body.field, value)
    if body.field == "description":
        line.attributes = attributes(body.value)
    line.flags = [
        f
        for f in line.flags
        if f not in ("UNVERIFIED_" + body.field.upper(), "LINE_AMOUNT_MISMATCH")
    ]
    element.normalized_value = body.value
    element.version += 1
    source_document = owned(db, Document, element.document_id, org)
    source_document.version += 1
    if body.field in ("description", "sku"):
        for affected_match in db.scalars(select(Match).where(Match.organization_id == org)):
            if affected_match.invoice_line_id == line.id or affected_match.po_line_id == line.id:
                affected_match.reviewed = 0
                affected_match.review_action = None
                affected_match.version += 1
    affected = [
        r
        for r in db.scalars(select(Run).where(Run.organization_id == org))
        if element.document_id in [r.po_id] + r.invoice_ids
    ]
    for run in affected:
        db.add(
            Review(
                organization_id=org,
                run_id=run.id,
                element_id=element.id,
                actor="local_workspace_owner",
                action="extraction_correction",
                before=before,
                after={
                    "field": body.field,
                    "value": body.value,
                    "version": element.version,
                },
                note=body.note,
            )
        )
    db.commit()
    for run in affected:
        queue(db, run)
    return {
        "element": serialize(element),
        "recalculated_run_ids": [r.id for r in affected],
    }


@app.post("/api/discrepancies/{id}/investigate")
def investigate(id: str, db=Depends(db_session), org=Depends(auth)):
    discrepancy = owned(db, Discrepancy, id, org)
    from backend.app.tools import dispatch

    result = dispatch(
        db,
        discrepancy.run_id,
        "get_source_evidence",
        discrepancy.match_id or discrepancy.id,
        org,
    )
    return {
        "finding": serialize(discrepancy),
        "source_evidence": result,
        "resolution": "Inspect the evidence and submit a documented review or extraction correction.",
    }


@app.get("/api/dashboard/summary")
def summary(db=Depends(db_session), org=Depends(auth)):
    rows = list(db.scalars(select(Run).where(Run.organization_id == org)))
    durations = [
        (
            datetime.fromisoformat(r.finished_at) - datetime.fromisoformat(r.started_at)
        ).total_seconds()
        for r in rows
        if r.started_at and r.finished_at
    ]
    return {
        "total_runs": len(rows),
        "completed": sum(r.status == "COMPLETED" for r in rows),
        "review_required": sum(
            r.status == "WAITING_FOR_REVIEW" or r.outcome == "BLOCKED" for r in rows
        ),
        "failed": sum(r.status == "FAILED" for r in rows),
        "active": sum(r.status in ("QUEUED", "PROCESSING") for r in rows),
        "documents": db.scalar(
            select(func.count()).select_from(Document).where(Document.organization_id == org)
        ),
        "discrepancies": db.scalar(
            select(func.count()).select_from(Discrepancy).where(Discrepancy.organization_id == org)
        ),
        "average_duration_seconds": sum(durations) / len(durations) if durations else None,
        "status_breakdown": {
            s: sum(r.status == s for r in rows) for s in sorted({r.status for r in rows})
        },
    }


@app.get("/api/dashboard/activity")
def activity(db=Depends(db_session), org=Depends(auth)):
    return {
        "items": [
            serialize(e)
            for e in db.scalars(
                select(Event)
                .where(Event.organization_id == org)
                .order_by(Event.sequence.desc())
                .limit(20)
            )
        ]
    }


@app.get("/api/synthetic/scenarios")
def scenarios(org=Depends(auth)):
    return {
        "items": [json.loads(p.read_text()) for p in sorted(SCENARIOS_ROOT.glob("*/manifest.json"))]
    }


@app.post("/api/synthetic/scenarios/{id}/load")
def load_scenario(id: str, db=Depends(db_session), org=Depends(auth)):
    # Membership lookup prevents path traversal. Only PDF bytes enter ingestion.
    allowed = {p.parent.name: p.parent for p in SCENARIOS_ROOT.glob("*/manifest.json")}
    if id not in allowed:
        raise HTTPException(404, "Generate this scenario first")
    folder = allowed[id]
    po, _ = store_pdf(
        db,
        (folder / "purchase_order.pdf").read_bytes(),
        "purchase_order.pdf",
        "po",
        org,
    )
    inv, _ = store_pdf(db, (folder / "invoice.pdf").read_bytes(), "invoice.pdf", "invoice", org)
    return {"po": serialize(po), "invoice": serialize(inv)}


@app.post("/api/evaluations", status_code=201)
def create_evaluation(body: EvaluationCreate, db=Depends(db_session), org=Depends(auth)):
    known = {p.parent.name for p in SCENARIOS_ROOT.glob("*/manifest.json")}
    if any(id not in known for id in body.scenario_ids):
        raise HTTPException(422, "Unknown scenario")
    evaluation = Evaluation(organization_id=org, scenario_ids=body.scenario_ids)
    db.add(evaluation)
    db.commit()
    return serialize(evaluation)


@app.get("/api/evaluations")
def evaluations(db=Depends(db_session), org=Depends(auth)):
    return {
        "items": [
            serialize(e)
            for e in db.scalars(
                select(Evaluation)
                .where(Evaluation.organization_id == org)
                .order_by(Evaluation.created_at.desc())
            )
        ]
    }


@app.get("/api/evaluations/{id}")
def evaluation_details(id: str, db=Depends(db_session), org=Depends(auth)):
    return serialize(owned(db, Evaluation, id, org))


@app.get("/api/elements/{id}")
def element_detail(id: str, db=Depends(db_session), org=Depends(auth)):
    return serialize(owned(db, Element, id, org))


@app.get("/api/reconciliations/{id}/reviews")
def review_history(id: str, db=Depends(db_session), org=Depends(auth)):
    owned(db, Run, id, org)
    return {
        "items": [
            serialize(r)
            for r in db.scalars(
                select(Review)
                .where(Review.run_id == id, Review.organization_id == org)
                .order_by(Review.created_at)
            )
        ]
    }
