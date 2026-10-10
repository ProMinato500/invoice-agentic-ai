from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    element_id: str
    document_id: str
    page: int
    bbox: list[float]
    raw_text: str


class CanonicalLine(BaseModel):
    line_no: int
    description: str
    sku: str = ""
    quantity: Decimal
    unit: str = "EA"
    unit_price: Decimal
    amount: Decimal
    tax_rate: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    attributes: dict[str, str] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class ExtractedHeader(BaseModel):
    number: str | None
    po_reference: str | None
    supplier: str | None
    buyer: str | None
    currency: str | None
    subtotal: Decimal | None
    tax: Decimal | None
    freight: Decimal | None
    discount: Decimal | None
    total: Decimal | None


class ExtractedLineAI(BaseModel):
    line_no: int
    description: str
    sku: str
    quantity: str
    unit: str
    unit_price: str
    amount: str
    tax_rate: str
    discount: str
    attributes: list["AttributeAI"]
    evidence_ids: list[str]


class AttributeAI(BaseModel):
    name: str
    value: str


class ExtractedDocumentAI(BaseModel):
    header: ExtractedHeader
    lines: list[ExtractedLineAI]
    warnings: list[str]


class SemanticDecision(BaseModel):
    po_line_id: str | None
    correspondence: Literal["SAME_PRODUCT", "SAME_FAMILY", "DIFFERENT", "UNCERTAIN", "NO_MATCH"]
    evidence_ids: list[str]
    rationale: str


class RunCreate(BaseModel):
    po_id: str
    invoice_ids: list[str] = Field(min_length=1, max_length=20)
    supporting_ids: list[str] = Field(default_factory=list, max_length=20)
    idempotency_key: str | None = Field(default=None, max_length=160)
    price_tolerance_percent: Decimal = Field(default=Decimal("2"), ge=0, le=10)


class ReviewRequest(BaseModel):
    action: Literal["accept", "reject", "remap", "unmatched", "substitution"]
    po_line_id: str | None = None
    note: str = Field(min_length=3, max_length=4000)
    version: int


class CorrectionRequest(BaseModel):
    line_id: str | None = None
    field: Literal["description", "sku", "quantity", "unit", "unit_price", "amount"] | None = None
    value: str = Field(min_length=1, max_length=8000)
    note: str = Field(min_length=3, max_length=4000)
    version: int


class EvaluationCreate(BaseModel):
    scenario_ids: list[str] = Field(min_length=1, max_length=30)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal[
        "get_po_line",
        "get_invoice_line",
        "get_source_evidence",
        "get_previous_allocations",
        "request_human_review",
    ]
    record_id: str
