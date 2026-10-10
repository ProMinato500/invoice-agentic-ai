import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


class Owned:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(String(80), default="local", index=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Document(Owned, Base):
    __tablename__ = "documents"
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(32), default="UPLOADED")
    extraction: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("organization_id", "sha256", "kind"),)


class Element(Owned, Base):
    __tablename__ = "document_elements"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    bbox: Mapped[list] = mapped_column(JSON)
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)


class Line(Owned, Base):
    __tablename__ = "document_lines"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    sku: Mapped[str] = mapped_column(String(160), default="")
    quantity: Mapped[float] = mapped_column(Numeric(20, 6))
    unit: Mapped[str] = mapped_column(String(50), default="EA")
    unit_price: Mapped[float] = mapped_column(Numeric(20, 6))
    amount: Mapped[float] = mapped_column(Numeric(20, 6))
    tax_rate: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    discount: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (UniqueConstraint("document_id", "line_no"),)


class Run(Owned, Base):
    __tablename__ = "reconciliation_runs"
    po_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    invoice_ids: Mapped[list] = mapped_column(JSON)
    supporting_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(60), default="QUEUED", index=True)
    stage: Mapped[str] = mapped_column(String(60), default="UPLOADED")
    outcome: Mapped[str] = mapped_column(String(40), default="INCOMPLETE")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    cancel_requested: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    heartbeat: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("organization_id", "idempotency_key"),)


class Event(Owned, Base):
    __tablename__ = "workflow_events"
    sequence: Mapped[int] = mapped_column(Integer, unique=True, autoincrement=True, nullable=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Match(Owned, Base):
    __tablename__ = "line_matches"
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"), index=True)
    invoice_line_id: Mapped[str] = mapped_column(ForeignKey("document_lines.id"))
    po_line_id: Mapped[str | None] = mapped_column(ForeignKey("document_lines.id"), nullable=True)
    identity_status: Mapped[str] = mapped_column(String(40))
    spec_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    quantity_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    price_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    score: Mapped[float] = mapped_column(Float, default=0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    reviewed: Mapped[int] = mapped_column(Integer, default=0)
    review_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("run_id", "invoice_line_id"),)


class Discrepancy(Owned, Base):
    __tablename__ = "discrepancies"
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"), index=True)
    match_id: Mapped[str | None] = mapped_column(ForeignKey("line_matches.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)


class Review(Owned, Base):
    __tablename__ = "review_events"
    run_id: Mapped[str | None] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=True)
    match_id: Mapped[str | None] = mapped_column(ForeignKey("line_matches.id"), nullable=True)
    element_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_elements.id"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(40))
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text)


class Allocation(Owned, Base):
    __tablename__ = "quantity_allocations"
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"), index=True)
    po_line_id: Mapped[str] = mapped_column(ForeignKey("document_lines.id"), index=True)
    invoice_line_id: Mapped[str] = mapped_column(ForeignKey("document_lines.id"))
    quantity: Mapped[float] = mapped_column(Numeric(20, 6))
    __table_args__ = (UniqueConstraint("po_line_id", "invoice_line_id"),)


class Evaluation(Owned, Base):
    __tablename__ = "evaluation_runs"
    status: Mapped[str] = mapped_column(String(40), default="QUEUED")
    scenario_ids: Mapped[list] = mapped_column(JSON)
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SearchRecord(Owned, Base):
    __tablename__ = "product_search_records"
    line_id: Mapped[str] = mapped_column(ForeignKey("document_lines.id"), unique=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    search_text: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)


Index("ix_owned_documents", Document.organization_id, Document.kind)
