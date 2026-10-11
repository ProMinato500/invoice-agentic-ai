import json
import os
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pymupdf as fitz
from sqlalchemy import delete, select

from backend.app.core.config import settings
from backend.app.models import Document, Element, Line, uid
from backend.app.normalization import attributes, number, unit
from backend.app.recovery import quality_gate, recover
from backend.app.schemas import CanonicalLine
from backend.app.table_context import build_tables, finish_table, table_kind

for key in ("HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME"):
    os.environ.setdefault(key, str(settings.storage / "model-cache"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def inspect_pdf(path):
    with fitz.open(stream=Path(path).read_bytes(), filetype="pdf") as pdf:
        if pdf.needs_pass:
            raise ValueError("PASSWORD_PROTECTED_PDF: upload an unlocked document")
        if not 0 < len(pdf) <= settings.max_pages:
            raise ValueError(f"PAGE_LIMIT: documents must have 1-{settings.max_pages} pages")
        return len(pdf)


@lru_cache(maxsize=1)
def converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    if settings.docling_pipeline == "native":
        from docling.datamodel.pipeline_options import NativePdfPipelineOptions
        from docling.pipeline.native_pdf_pipeline import NativePdfPipeline

        options = PdfFormatOption(
            pipeline_cls=NativePdfPipeline, pipeline_options=NativePdfPipelineOptions()
        )
    else:
        opts = PdfPipelineOptions(do_ocr=True, do_table_structure=True)
        opts.ocr_options = RapidOcrOptions()
        opts.document_timeout = settings.job_timeout_seconds
        options = PdfFormatOption(pipeline_options=opts)
    return DocumentConverter(format_options={InputFormat.PDF: options})


def docling_convert(path):
    result = converter().convert(path)
    return result.document.export_to_dict()


ALIASES = {
    "line_no": ("line", "line no", "no", "item no", "#", "sr", "s no"),
    "sku": (
        "sku",
        "code",
        "part no",
        "part number",
        "item code",
        "product code",
        "material code",
        "item",
    ),
    "description": (
        "description",
        "product",
        "item description",
        "details",
        "particulars",
        "service",
        "product / service description",
        "description of goods",
    ),
    "quantity": ("qty", "quantity", "billed qty", "ordered qty"),
    "unit": ("unit", "uom", "units"),
    "unit_price": ("unit price", "price", "rate", "unit cost"),
    "amount": ("amount", "total", "line total", "net amount", "extended amount", "taxable value"),
    "tax_rate": ("tax %", "tax rate", "gst %", "vat %"),
    "discount_rate": ("disc %", "discount %", "discount percent"),
    "discount": ("discount", "discount amount"),
}


def header_map(cells):
    mapping = {}
    for col, raw in enumerate(cells):
        v = re.sub(r"\s+", " ", str(raw or "")).strip().lower().rstrip(".")
        for name, aliases in ALIASES.items():
            if v in aliases:
                if name == "amount" and name in mapping:
                    prior = re.sub(r"\s+", " ", str(cells[mapping[name]] or "")).strip().lower()
                    if prior in ("taxable value", "net amount"):
                        continue
                mapping[name] = col
    return mapping


def parse_table(rows, row_evidence, start):
    mapping = {}
    output = []
    warnings = []
    for index, row in enumerate(rows):
        proposed = header_map(row)
        if {"description", "quantity", "unit_price"}.issubset(proposed):
            mapping = proposed
            continue
        if not mapping:
            continue

        def get(name, default=""):
            column = mapping.get(name)
            return (
                str(row[column] or "").strip()
                if column is not None and column < len(row)
                else default
            )

        desc = get("description")
        if not desc or re.match(
            r"^(sub\s*total|total|grand total|tax|freight|discount)\b", desc, re.I
        ):
            continue
        try:
            q, p = number(get("quantity")), number(get("unit_price"))
            printed = get("amount")
            flags = [] if printed else ["AMOUNT_NOT_PRINTED"]
            discount = number(get("discount", "0"))
            if "discount_rate" in mapping:
                percentage = number(get("discount_rate", "0"))
                if not 0 <= percentage <= 100:
                    raise ValueError("Invalid discount percentage")
                discount = (q * p * percentage / 100).quantize(Decimal(".01"))
            output.append(
                CanonicalLine(
                    line_no=start + len(output),
                    description=desc,
                    sku=get("sku"),
                    quantity=q,
                    unit=unit(get("unit", "EA")),
                    unit_price=p,
                    amount=number(printed) if printed else q * p - discount,
                    tax_rate=number(get("tax_rate", "0")),
                    discount=discount,
                    attributes=attributes(desc),
                    evidence_ids=row_evidence.get(index, []),
                    flags=flags,
                )
            )
        except ValueError:
            warnings.append("UNREADABLE_TABLE_ROW: " + " | ".join(str(x or "") for x in row))
    return output, warnings


def native_header(text, kind):
    def capture(pattern):
        match = re.search(pattern, text, re.I | re.M)
        return match.group(1).strip() if match else None

    header = {
        "number": capture(r"(?:Invoice|Purchase Order|PO)\s*(?:No\.?|Number|#)?\s*[:#]\s*([^\n]+)"),
        "po_reference": capture(r"(?:PO Reference|PO Ref|Purchase Order Reference)\s*:\s*([^\n]+)"),
        "supplier": capture(r"(?:Supplier|Vendor|Seller)\s*:\s*([^\n]+)"),
        "buyer": capture(r"(?:Buyer|Bill To|Customer)\s*:\s*([^\n]+)"),
        "currency": capture(r"Currency\s*:\s*([A-Z]{3})"),
    }
    if not header["currency"]:
        currency = re.search(r"\b(USD|INR|EUR|GBP|AUD|CAD|JPY)\b", text)
        header["currency"] = currency.group(1) if currency else None
    for key, label in [
        ("subtotal", r"Subtotal"),
        ("tax", r"(?:Tax|GST|VAT)"),
        ("freight", r"(?:Freight|Shipping)"),
        ("discount", r"Discount"),
        ("total", r"(?:Grand Total|Total Due|Invoice Total|Order Total)"),
    ]:
        value = capture(r"^" + label + r"\s*[:]?\s*\n?\s*([\d,.]+)\s*$")
        header[key] = str(number(value)) if value else None
    return header


def extract_document(db, document: Document, emit):
    if document.state == "EXTRACTED":
        from backend.app.reports import serialize

        saved_elements = list(
            db.scalars(
                select(Element).where(
                    Element.document_id == document.id,
                    Element.organization_id == document.organization_id,
                )
            )
        )
        saved_lines = list(
            db.scalars(
                select(Line).where(
                    Line.document_id == document.id,
                    Line.organization_id == document.organization_id,
                )
            )
        )
        saved_path = settings.storage / "extractions" / f"{document.id}.json"
        saved_raw = (
            json.loads(saved_path.read_text(encoding="utf-8")) if saved_path.exists() else {}
        )
        saved_tables = build_tables(saved_raw, saved_elements)
        emit(
            "OCR_RESULT",
            "Using persisted parser output and current canonical version",
            {
                "document_id": document.id,
                "cached": True,
                "document_version": document.version,
                "snapshot": {
                    "elements": [serialize(e) for e in saved_elements],
                    "tables": saved_tables,
                    "canonical_lines": [serialize(line) for line in saved_lines],
                    "header": document.extraction.get("header"),
                    "warnings": document.extraction.get("warnings", []),
                    "quality": document.extraction.get(
                        "quality",
                        {
                            "note": "Historical extraction; inspect original source before certifying completeness"
                        },
                    ),
                },
            },
        )
        return
    emit(
        "STARTED",
        f"Parsing {document.name}",
        {"document_id": document.id, "parser": settings.parser},
    )
    raw = {}
    warnings = []
    method = "PYMUPDF"
    if settings.parser == "docling":
        raw = docling_convert(document.path)
        method = "DOCLING"
    elif settings.parser != "pymupdf":
        raise ValueError("Unknown PARSER configuration")
    elements = []
    tables = []
    texts = []
    with fitz.open(document.path) as pdf:
        for page_num, page in enumerate(pdf, 1):
            text = page.get_text()
            texts.append(text)
            for block in page.get_text("blocks"):
                if len(block) > 6 and block[6] != 0:
                    continue
                value = block[4].strip()
                if value:
                    elements.append(
                        Element(
                            id=uid(),
                            organization_id=document.organization_id,
                            document_id=document.id,
                            page=page_num,
                            bbox=list(block[:4]),
                            raw_text=value,
                            method="PYMUPDF_SOURCE",
                        )
                    )
            # Native vector tables provide exact source row rectangles when available.
            for table in page.find_tables().tables:
                rows = table.extract()
                refs = {}
                for i, row in enumerate(table.rows):
                    row_text = " | ".join(str(c or "") for c in rows[i])
                    element = Element(
                        id=uid(),
                        organization_id=document.organization_id,
                        document_id=document.id,
                        page=page_num,
                        bbox=list(row.bbox),
                        raw_text=row_text,
                        method="PYMUPDF_TABLE",
                    )
                    elements.append(element)
                    refs[i] = [element.id]
                native = {
                    "id": f"native-{page_num}-{len(raw.get('_native_table_context', [])) + 1}",
                    "page": page_num,
                    "title": "",
                    "num_rows": len(rows),
                    "num_cols": max((len(r) for r in rows), default=0),
                    "cells": [],
                    "source_granularity": "row_rectangle",
                }
                for r, values in enumerate(rows):
                    for c, value in enumerate(values):
                        native["cells"].append(
                            {
                                "row": r,
                                "col": c,
                                "row_span": 1,
                                "col_span": 1,
                                "column_header": False,
                                "row_header": False,
                                "text": str(value or ""),
                                "evidence_ids": refs[r],
                                "bbox": list(table.rows[r].bbox),
                                "page": page_num,
                            }
                        )
                raw.setdefault("_native_table_context", []).append(finish_table(native))
                if table_kind("", [str(c or "") for row in rows[:3] for c in row]) not in (
                    "delivery_schedule",
                    "tax_summary",
                    "payment_schedule",
                ):
                    tables.append((rows, refs))
        # Preserve Docling cells and convert bottom-origin coordinates to top-origin PDF points.
        for table in raw.get("tables", []):
            data = table.get("data", {})
            cells = data.get("table_cells", [])
            prov = table.get("prov", [])
            if not cells or not prov:
                continue
            page_num = prov[0]["page_no"]
            page_height = pdf[page_num - 1].rect.height
            rows = [
                ["" for _ in range(data.get("num_cols", 0))] for _ in range(data.get("num_rows", 0))
            ]
            refs = {}
            for cell in cells:
                r, c = (
                    cell.get("start_row_offset_idx", 0),
                    cell.get("start_col_offset_idx", 0),
                )
                if r >= len(rows) or c >= len(rows[r]):
                    continue
                value = cell.get("text", "")
                rows[r][c] = value
                bbox = cell.get("bbox")
                if bbox:
                    b = [bbox["l"], bbox["t"], bbox["r"], bbox["b"]]
                    if bbox.get("coord_origin") == "BOTTOMLEFT":
                        b = [
                            bbox["l"],
                            page_height - bbox["t"],
                            bbox["r"],
                            page_height - bbox["b"],
                        ]
                    b = [
                        min(b[0], b[2]),
                        min(b[1], b[3]),
                        max(b[0], b[2]),
                        max(b[1], b[3]),
                    ]
                    element = Element(
                        id=uid(),
                        organization_id=document.organization_id,
                        document_id=document.id,
                        page=page_num,
                        bbox=b,
                        raw_text=value,
                        method="DOCLING_CELL",
                    )
                    elements.append(element)
                    refs.setdefault(r, []).append(element.id)
                    cell["_evidence_id"] = element.id
            # Prefer the primary parser's structured tables when it yields canonical rows.
            parsed, _ = parse_table(rows, refs, 1)
            if parsed and table_kind("", [str(c or "") for row in rows[:3] for c in row]) not in (
                "delivery_schedule",
                "tax_summary",
                "payment_schedule",
            ):
                if not raw.get("_canonical_tables_found"):
                    tables = []
                    raw["_canonical_tables_found"] = True
                tables.append((rows, refs))
        # OCR/native Docling text with source coordinates, useful for scanned pages and AI recovery.
        for item in raw.get("texts", []):
            for prov in item.get("prov", []):
                bbox = prov.get("bbox")
                page_num = prov["page_no"]
                if not bbox:
                    continue
                h = pdf[page_num - 1].rect.height
                b = [bbox["l"], bbox["t"], bbox["r"], bbox["b"]]
                if bbox.get("coord_origin") == "BOTTOMLEFT":
                    b = [bbox["l"], h - bbox["t"], bbox["r"], h - bbox["b"]]
                elements.append(
                    Element(
                        id=uid(),
                        organization_id=document.organization_id,
                        document_id=document.id,
                        page=page_num,
                        bbox=[
                            min(b[0], b[2]),
                            min(b[1], b[3]),
                            max(b[0], b[2]),
                            max(b[1], b[3]),
                        ],
                        raw_text=item.get("text", ""),
                        method="DOCLING_TEXT",
                    )
                )
    canonical = []
    for rows, refs in tables:
        lines, issues = parse_table(rows, refs, len(canonical) + 1)
        canonical.extend(lines)
        warnings.extend(issues)
    text = "\n".join(texts)
    if not text.strip():
        text = "\n".join(e.raw_text for e in elements)
    header = native_header(text, document.kind)
    table_context = build_tables(raw, elements)
    raw["_table_context_version"] = 1
    quality = quality_gate(document, canonical, elements, header, warnings, tables=table_context)
    emit(
        "QUALITY_CHECKED",
        "Extraction completeness checked",
        {"document_id": document.id, "output": quality},
    )
    recovery = []
    if quality["recovery_required"] and document.kind in ("po", "invoice"):
        if settings.ai_configured:
            recovery, recovery_warnings = recover(
                document, canonical, elements, header, quality, emit, tables=table_context
            )
            warnings.extend(recovery_warnings)
        else:
            warnings.append("EXTRACTION_COMPLETENESS_REVIEW: " + ", ".join(quality["reasons"]))
    raw["recovery"] = recovery
    raw["quality"] = quality
    emit(
        "OCR_RESULT",
        "Parser text, tables and recovery readings available",
        {
            "document_id": document.id,
            "parser": method,
            "element_count": len(elements),
            "snapshot": {
                "elements": [
                    {
                        "id": e.id,
                        "page": e.page,
                        "bbox": e.bbox,
                        "raw_text": e.raw_text,
                        "method": e.method,
                    }
                    for e in elements
                ],
                "tables": table_context,
                "canonical_lines": [r.model_dump(mode="json") for r in canonical],
                "header": header,
                "quality": quality,
                "recovery": recovery,
                "warnings": warnings,
            },
            "raw": raw,
        },
    )
    if not canonical and document.kind in ("po", "invoice"):
        raise ValueError(
            "EXTRACTION_REVIEW_REQUIRED: no reliable item rows extracted. Enable standard Docling OCR / configure AI for this layout; no invented rows were created."
        )
    # A retry only replaces uncommitted extraction, never reviewed/existing line IDs.
    db.execute(delete(Element).where(Element.document_id == document.id))
    db.add_all(elements)
    known = {e.id: e for e in elements}
    for row in canonical:
        evidence = [
            {
                "element_id": eid,
                "document_id": document.id,
                "page": known[eid].page,
                "bbox": known[eid].bbox,
                "raw_text": known[eid].raw_text,
            }
            for eid in row.evidence_ids
            if eid in known
        ]
        if not evidence:
            row.flags.append("MISSING_SOURCE_EVIDENCE")
        if abs(row.quantity * row.unit_price - row.discount - row.amount) > Decimal(
            settings.rounding_tolerance
        ):
            row.flags.append("LINE_AMOUNT_MISMATCH")
        data = row.model_dump(exclude={"evidence_ids"}, mode="python")
        db.add(
            Line(
                organization_id=document.organization_id,
                document_id=document.id,
                evidence=evidence,
                **data,
            )
        )
    document.extraction = {
        "header": header,
        "warnings": warnings,
        "parser": method,
        "pipeline": settings.docling_pipeline,
        "line_count": len(canonical),
        "quality": quality,
        "recovery_count": len(recovery),
        "raw_path": str(settings.storage / "extractions" / f"{document.id}.json"),
    }
    raw_path = Path(document.extraction["raw_path"])
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(raw, default=str), encoding="utf-8")
    document.state = "EXTRACTED"
    db.commit()
    emit(
        "COMPLETED",
        f"{document.name}: {len(canonical)} lines extracted",
        {
            "document_id": document.id,
            "line_count": len(canonical),
            "warnings": warnings,
            "parser": method,
        },
    )


def refresh_saved_tables(db, document):
    """Reparse saved tables while retaining line IDs, originals and protected edits."""
    from backend.app.models import Allocation, Match
    from backend.app.reports import serialize

    path = settings.storage / "extractions" / f"{document.id}.json"
    if not path.exists():
        return {"document_id": document.id, "changed": False, "reason": "No saved tables"}
    raw = json.loads(path.read_text(encoding="utf-8"))
    elements = list(
        db.scalars(
            select(Element).where(
                Element.document_id == document.id,
                Element.organization_id == document.organization_id,
            )
        )
    )
    known = {e.id: e for e in elements}
    tables = build_tables(raw, elements)
    existing = list(
        db.scalars(select(Line).where(Line.document_id == document.id).order_by(Line.line_no))
    )
    protected = {e.id for e in elements if e.normalized_value is not None}
    changes, warnings = [], []
    assigned = set()
    maximum = max((r.line_no for r in existing), default=0)
    for table in tables:
        if (
            table["type_hint"] in ("delivery_schedule", "tax_summary", "payment_schedule")
            or table["header_basis"] == "missing"
        ):
            continue
        rows = [table["columns"]]
        refs = {}
        for row in table["rows"]:
            values = [""] * table["num_cols"]
            ids = []
            for cell in row["cells"]:
                values[cell["col"]] = cell["text"]
                ids.extend(cell["evidence_ids"])
            refs[len(rows)] = list(dict.fromkeys(ids))
            rows.append(values)
        parsed, issues = parse_table(rows, refs, 1)
        warnings.extend(issues)
        for candidate in parsed:
            if not candidate.evidence_ids or any(i not in known for i in candidate.evidence_ids):
                warnings.append("TABLE_REFRESH_MISSING_EVIDENCE")
                continue
            matching = [
                line
                for line in existing
                if candidate.sku and line.sku == candidate.sku and line.id not in assigned
            ]
            if not candidate.sku:
                matching = [
                    line
                    for line in existing
                    if line.description == candidate.description and line.id not in assigned
                ]
            if len(matching) > 1:
                warnings.append("TABLE_REFRESH_AMBIGUOUS_EXISTING_ROW")
                continue
            line = matching[0] if matching else None
            if line and (
                any(e["element_id"] in protected for e in line.evidence)
                or db.scalar(
                    select(Allocation.id).where(
                        (Allocation.po_line_id == line.id) | (Allocation.invoice_line_id == line.id)
                    )
                )
                or db.scalar(
                    select(Match.id).where(
                        ((Match.po_line_id == line.id) | (Match.invoice_line_id == line.id))
                        & (Match.reviewed == 1)
                    )
                )
            ):
                warnings.append("TABLE_REFRESH_PRESERVED_PROTECTED_ROW:" + line.id)
                continue
            evidence = [
                {
                    "element_id": i,
                    "document_id": document.id,
                    "page": known[i].page,
                    "bbox": known[i].bbox,
                    "raw_text": known[i].raw_text,
                }
                for i in candidate.evidence_ids
            ]
            data = candidate.model_dump(exclude={"evidence_ids", "line_no"}, mode="python")
            if abs(
                candidate.quantity * candidate.unit_price - candidate.discount - candidate.amount
            ) > Decimal(settings.rounding_tolerance):
                data["flags"].append("LINE_AMOUNT_MISMATCH")
            before = serialize(line) if line else {}
            if line is None:
                maximum += 1
                line = Line(
                    organization_id=document.organization_id,
                    document_id=document.id,
                    line_no=maximum,
                    evidence=evidence,
                    **data,
                )
                db.add(line)
                db.flush()
                existing.append(line)
            else:
                for key, value in data.items():
                    setattr(line, key, value)
                line.evidence = evidence
            assigned.add(line.id)
            changes.append({"before": before, "after": serialize(line), "table_id": table["id"]})
    if changes:
        document.version += 1
        document.extraction = {
            **document.extraction,
            "line_count": len(existing),
            "table_context_version": 1,
            "table_refresh_warnings": warnings,
            "source_verification": None,
        }
    return json.loads(
        json.dumps(
            {
                "document_id": document.id,
                "changed": bool(changes),
                "changes": changes,
                "warnings": warnings,
                "line_count": len(existing),
                "version": document.version,
            },
            default=str,
        )
    )
