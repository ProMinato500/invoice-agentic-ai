import re
from decimal import Decimal

from backend.app.ai import agent, structured
from backend.app.core.config import settings
from backend.app.models import Element, uid
from backend.app.normalization import attributes, identifier, number, unit
from backend.app.schemas import CanonicalLine, RecoveredPage
from backend.app.table_context import recovery_chunks
from backend.app.tools import render_region

RECOVERY_TOOLS = {
    "get_document_page": "Read the current authorized page's source text and rectangles.",
    "render_page": "Render the current PDF page for inspection; returns actual image metadata.",
    "crop_region": "Render a bounded region within the current page; returns actual crop metadata.",
    "propose_correction": "Record a source correction proposal for human verification; query is the reason.",
    "inspect_extracted_table": "Inspect reconstructed table rows, repeated headers, spans, type hints, identifier links and existing canonical rows for the current chunk.",
    "validate_extraction": "Read deterministic completeness and financial consistency findings.",
    "reinspect_with_vision": "Read a specified page/crop using the configured vision model; preserve the competing reading for review.",
    "request_human_review": "Record unresolved extraction ambiguity; query is the reason.",
}


def quality_gate(document, canonical, elements, header, warnings, tables=None):
    known = {e.id: e for e in elements}
    pages = {known[i].page for row in canonical for i in row.evidence_ids if i in known}
    reasons = []
    suspect = set()
    if not canonical:
        reasons.append("NO_CANONICAL_ROWS")
        suspect.update(range(1, document.page_count + 1))
    for page in range(1, document.page_count + 1):
        text = " ".join(e.raw_text for e in elements if e.page == page)
        page_tables = [t for t in (tables or []) if t["page"] == page]
        only_supporting_tables = bool(page_tables) and all(
            t["type_hint"] in ("delivery_schedule", "tax_summary", "payment_schedule")
            for t in page_tables
        )
        if only_supporting_tables:
            rectangles = []
            for table in page_tables:
                boxes = [c["bbox"] for c in table["cells"] if c["bbox"]]
                if boxes:
                    rectangles.append(
                        [
                            min(b[0] for b in boxes),
                            min(b[1] for b in boxes),
                            max(b[2] for b in boxes),
                            max(b[3] for b in boxes),
                        ]
                    )
            outside = " ".join(
                e.raw_text
                for e in elements
                if e.page == page
                and not any(
                    e.bbox[0] >= b[0] - 2
                    and e.bbox[1] >= b[1] - 2
                    and e.bbox[2] <= b[2] + 2
                    and e.bbox[3] <= b[3] + 2
                    for b in rectangles
                )
            )
            if re.search(r"qty|quantity|unit price|description|sku|amount", outside, re.I):
                only_supporting_tables = False
        if (
            page not in pages
            and not only_supporting_tables
            and re.search(r"qty|quantity|unit price|description|sku|amount", text, re.I)
        ):
            suspect.add(page)
            reasons.append(f"PAGE_WITH_ITEM_CONTENT_NOT_COVERED:{page}")
    if any(w.startswith("UNREADABLE_TABLE_ROW") for w in warnings):
        reasons.append("PARTIAL_TABLE_PARSE")
        suspect.update(pages)
    if header.get("subtotal") is not None:
        if abs(
            sum((r.amount for r in canonical), Decimal(0)) - number(header["subtotal"])
        ) > Decimal(settings.rounding_tolerance):
            reasons.append("SUBTOTAL_COVERAGE_MISMATCH")
            suspect.update(pages or range(1, document.page_count + 1))
    if any(not header.get(k) for k in ("number", "supplier", "buyer", "currency", "total")):
        reasons.append("MISSING_HEADER_FIELDS")
        suspect.update({1, document.page_count})
    return {
        "reasons": list(dict.fromkeys(reasons)),
        "suspect_pages": sorted(suspect),
        "covered_pages": sorted(pages),
        "page_count": document.page_count,
        "canonical_rows": len(canonical),
        "recovery_required": bool(reasons),
    }


def validate_field(field, known):
    if field.value is None:
        return False
    if not field.evidence_ids or any(i not in known for i in field.evidence_ids):
        raise ValueError("INVALID_AI_FIELD_EVIDENCE")
    text = " ".join(known[i].raw_text for i in field.evidence_ids)
    if any(known[i].method == "OPENAI_VISION_SOURCE" for i in field.evidence_ids):
        return False  # A second model reading is not independent verification.
    if field.name in {
        "quantity",
        "unit_price",
        "amount",
        "tax_rate",
        "discount",
        "subtotal",
        "tax",
        "freight",
        "total",
    }:
        values = []
        for token in re.findall(r"-?\d[\d,.]*", text):
            try:
                values.append(number(token))
            except ValueError:
                pass
        return number(field.value) in values
    return bool(identifier(field.value)) and identifier(field.value) in identifier(text)


def recover(document, canonical, elements, header, quality, emit, tables=None):
    alternatives = []
    warnings = []
    targets = quality["suspect_pages"][: settings.max_recovery_pages]
    if len(targets) < len(quality["suspect_pages"]):
        warnings.append("RECOVERY_PAGE_BUDGET_EXHAUSTED: not all suspect pages inspected")
    known = {e.id: e for e in elements}
    for page in targets:
        source = [e for e in elements if e.page == page]
        page_tables = [t for t in (tables or []) if t["page"] == page]
        # Include adjacent-page header evidence for explicitly marked continuation suggestions.
        inherited_ids = {
            i
            for t in page_tables
            for c in t.get("suggested_headers", [])
            for i in c["evidence_ids"]
        }
        context_elements = source + [
            e for e in elements if e.id in inherited_ids and e.page != page
        ]
        chunks = recovery_chunks(context_elements, page_tables)
        for chunk_index, bundle in enumerate(chunks):
            chunk = [e for e in bundle["elements"] if e.page == page or bundle["tables"]]
            table_context = bundle["tables"]
            supplied = {e.id: e for e in chunk}
            page_rows = [
                r.model_dump(mode="json")
                for r in canonical
                if any(known.get(i) and known[i].page == page for i in r.evidence_ids)
            ]
            vision_readings = []

            def execute(name, args):
                if args.record_id != document.id or (args.page is not None and args.page != page):
                    raise ValueError("Unauthorized recovery context")
                if name == "validate_extraction":
                    return quality
                if name in {"get_document_page", "inspect_extracted_table"}:
                    return {
                        "elements": [
                            {"id": e.id, "text": e.raw_text, "bbox": e.bbox} for e in chunk
                        ],
                        "existing_rows": page_rows,
                        "tables": table_context,
                        "document_header": header,
                    }
                if name in {"render_page", "crop_region"}:
                    rendered = render_region(
                        document, page, args.bbox if name == "crop_region" else None
                    )
                    return {
                        "document_id": document.id,
                        "page": page,
                        "bbox": args.bbox,
                        "rendered_bytes": len(rendered),
                        "instruction": "Use reinspect_with_vision to obtain a structured image reading",
                    }
                if name == "propose_correction":
                    alternatives.append(
                        {
                            "page": page,
                            "method": "AGENT_CORRECTION_PROPOSAL",
                            "reason": args.query,
                            "verification_status": "REVIEW_REQUIRED",
                        }
                    )
                    return {"status": "PROPOSAL_SAVED", "canonical_changed": False}
                if name == "request_human_review":
                    warnings.append(
                        "EXTRACTION_AGENT_REVIEW: " + (args.query or "Unresolved source reading")
                    )
                    return {"status": "REVIEW_REQUIRED"}
                if not settings.enable_vision_fallback:
                    raise ValueError("Vision fallback is disabled")
                image = render_region(document, page, args.bbox)
                import pymupdf as fitz

                with fitz.open(document.path) as pdf:
                    bbox = args.bbox or list(pdf[page - 1].rect)
                region = Element(
                    id=uid(),
                    document_id=document.id,
                    organization_id=document.organization_id,
                    page=page,
                    bbox=bbox,
                    raw_text="",
                    method="OPENAI_VISION_SOURCE",
                )
                reading = structured(
                    "targeted_vision_recovery",
                    {
                        "document_id": document.id,
                        "page": page,
                        "region_evidence_id": region.id,
                        "tables": table_context,
                        "document_header": header,
                        "source_elements": [{"id": e.id, "text": e.raw_text} for e in chunk],
                        "instruction": "Read only this image region. Every field must cite supplied source IDs or the region evidence ID. Missing values are null. Never infer prices or totals.",
                    },
                    RecoveredPage,
                    emit,
                    images=[image],
                )
                region.raw_text = "Vision alternative reading: " + str(
                    reading.model_dump(mode="json")
                )
                elements.append(region)
                known[region.id] = region
                supplied[region.id] = region
                vision_readings.append(reading.model_dump(mode="json"))
                return {
                    "reading": reading.model_dump(mode="json"),
                    "method": "VISION_ALTERNATIVE_UNVERIFIED",
                    "source_bbox": bbox,
                }

            try:
                result = agent(
                    "extraction_recovery",
                    {
                        "document_id": document.id,
                        "kind": document.kind,
                        "page": page,
                        "chunk": chunk_index + 1,
                        "chunks_on_page": len(chunks),
                        "quality": quality,
                        "elements": [
                            {"id": e.id, "text": e.raw_text, "bbox": e.bbox} for e in chunk
                        ],
                        "existing_rows": page_rows,
                        "tables": table_context,
                        "document_header": header,
                        "instruction": "Inspect with tools. Use canonical field names exactly: header number/po_reference/supplier/buyer/currency/subtotal/tax/freight/discount/total; item description/sku/quantity/unit/unit_price/amount/tax_rate/discount. Header fields must not be item rows. Use table title, header hierarchy, row boundaries and spans before interpreting values. Classify unknown tables using tools or vision. Table type hints are advisory. Never create priced item rows from delivery schedules, tax summaries or payment schedules, and never use delivery quantities as ordered/billed quantities. Join related tables only through explicit line/material identifiers; ambiguity requires review. Suggested continuation headers are unverified and require vision or review. Extract only this chunk's actual rows and header fields. Each field requires its own supporting IDs. Use null for absent values. Include existing rows unchanged when supported; preserve competing readings. No inferred row amounts.",
                    },
                    RecoveredPage,
                    RECOVERY_TOOLS,
                    execute,
                    emit,
                )
                alternatives.append(
                    {
                        "page": page,
                        "chunk": chunk_index + 1,
                        "method": "AI_RECOVERY",
                        "output": result.model_dump(mode="json"),
                        "vision_readings": vision_readings,
                    }
                )
                if not result.is_complete:
                    warnings.append(f"INCOMPLETE_RECOVERY: page {page}, chunk {chunk_index + 1}")
                warnings.extend(result.warnings)
                for field in result.header:
                    if field.name not in header or field.value is None:
                        continue
                    verified = validate_field(field, supplied)
                    if not verified:
                        warnings.append("UNVERIFIED_HEADER_" + field.name.upper())
                    elif not header.get(field.name):
                        header[field.name] = field.value
                    elif str(header[field.name]) != field.value:
                        warnings.append("CONFLICTING_HEADER_" + field.name.upper())
                forbidden_ids = {
                    i
                    for t in table_context
                    if t["type_hint"] in ("delivery_schedule", "tax_summary", "payment_schedule")
                    for r in t["rows"]
                    for c in r["cells"]
                    for i in c["evidence_ids"]
                }
                for row in result.rows:
                    cited = set(row.evidence_ids) | {i for f in row.fields for i in f.evidence_ids}
                    if cited & forbidden_ids:
                        warnings.append("NON_ITEM_TABLE_ROW_REJECTED")
                        continue
                    fields = {f.name: f for f in row.fields}
                    if any(
                        k not in fields or fields[k].value is None
                        for k in ("description", "quantity", "unit_price", "amount")
                    ):
                        warnings.append("RECOVERY_ROW_MISSING_REQUIRED_FIELDS")
                        continue
                    if len(fields) != len(row.fields):
                        raise ValueError("DUPLICATE_RECOVERY_FIELD")
                    if not row.evidence_ids or any(i not in supplied for i in row.evidence_ids):
                        raise ValueError("INVALID_AI_ROW_EVIDENCE")
                    verified = {
                        k: validate_field(f, supplied)
                        for k, f in fields.items()
                        if f.value is not None
                    }
                    values = {k: f.value for k, f in fields.items()}
                    candidate = CanonicalLine(
                        line_no=len(canonical) + 1,
                        description=values["description"],
                        sku=values.get("sku") or "",
                        quantity=number(values["quantity"]),
                        unit=unit(values.get("unit") or "EA"),
                        unit_price=number(values["unit_price"]),
                        amount=number(values["amount"]),
                        tax_rate=number(values.get("tax_rate") or "0"),
                        discount=number(values.get("discount") or "0"),
                        attributes=attributes(values["description"]),
                        evidence_ids=list(
                            dict.fromkeys(
                                row.evidence_ids + [i for f in row.fields for i in f.evidence_ids]
                            )
                        ),
                        flags=["AI_RECOVERY_REQUIRES_REVIEW"]
                        + ["UNVERIFIED_" + k.upper() for k, v in verified.items() if not v],
                    )
                    duplicates = [
                        r
                        for r in canonical
                        if (candidate.sku and identifier(r.sku) == identifier(candidate.sku))
                        or r.description.casefold().strip()
                        == candidate.description.casefold().strip()
                    ]
                    if duplicates:
                        if not any(
                            (r.quantity, r.unit_price, r.amount)
                            == (candidate.quantity, candidate.unit_price, candidate.amount)
                            for r in duplicates
                        ):
                            warnings.append("COMPETING_ROW_READING: " + candidate.description)
                        continue
                    canonical.append(candidate)
            except Exception as exc:
                warnings.append("RECOVERY_UNRESOLVED: " + type(exc).__name__)
                emit(
                    "WARNING",
                    "Source recovery needs human review",
                    {"document_id": document.id, "page": page, "error": type(exc).__name__},
                )
    return alternatives, list(dict.fromkeys(warnings))
