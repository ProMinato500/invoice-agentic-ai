import json
import os
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pymupdf as fitz
from sqlalchemy import delete

from backend.app.ai import structured
from backend.app.core.config import settings
from backend.app.models import Document, Element, Line, uid
from backend.app.normalization import attributes, number, unit
from backend.app.schemas import CanonicalLine, ExtractedDocumentAI

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
        "item",
    ),
    "description": (
        "description",
        "product",
        "item description",
        "details",
        "particulars",
        "service",
    ),
    "quantity": ("qty", "quantity", "billed qty", "ordered qty"),
    "unit": ("unit", "uom", "units"),
    "unit_price": ("unit price", "price", "rate", "unit cost"),
    "amount": ("amount", "total", "line total", "net amount", "extended amount"),
    "tax_rate": ("tax %", "tax rate", "gst %", "vat %"),
    "discount": ("discount", "discount amount"),
}


def header_map(cells):
    mapping = {}
    for col, raw in enumerate(cells):
        v = re.sub(r"\s+", " ", str(raw or "")).strip().lower().rstrip(".")
        for name, aliases in ALIASES.items():
            if v in aliases:
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
            output.append(
                CanonicalLine(
                    line_no=start + len(output),
                    description=desc,
                    sku=get("sku"),
                    quantity=q,
                    unit=unit(get("unit", "EA")),
                    unit_price=p,
                    amount=number(printed) if printed else q * p,
                    tax_rate=number(get("tax_rate", "0")),
                    discount=number(get("discount", "0")),
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
            # Prefer the primary parser's structured tables when it yields canonical rows.
            parsed, _ = parse_table(rows, refs, 1)
            if parsed:
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
    # Schema-constrained normalization for layouts that deterministic table parsing cannot read.
    if not canonical and settings.ai_configured and elements:
        bounded = [{"id": e.id, "page": e.page, "text": e.raw_text} for e in elements[:400]]
        result = structured(
            "extract_document",
            {
                "kind": document.kind,
                "elements": bounded,
                "instruction": "Extract printed header and line fields. Supply supporting IDs for each row. Do not infer absent values. Numeric values must be decimal strings.",
            },
            ExtractedDocumentAI,
            emit,
        )
        header = result.header.model_dump(mode="json")
        known = {e.id: e for e in elements}
        for row in result.lines:
            if not row.evidence_ids or any(x not in known for x in row.evidence_ids):
                raise ValueError(
                    "INVALID_AI_EVIDENCE: extraction returned missing or unauthorized source IDs"
                )
            source = " ".join(known[x].raw_text for x in row.evidence_ids)
            flags = []
            # Monetary evidence must appear in supplied source; a model claim alone is insufficient.
            source_values = set()
            for token in re.findall(r"-?\d[\d,.]*", source):
                try:
                    source_values.add(number(token))
                except ValueError:
                    pass
            for field in ("quantity", "unit_price", "amount"):
                if number(getattr(row, field)) not in source_values:
                    flags.append("UNVERIFIED_" + field.upper())
            canonical.append(
                CanonicalLine(
                    line_no=len(canonical) + 1,
                    description=row.description,
                    sku=row.sku,
                    quantity=number(row.quantity),
                    unit=unit(row.unit),
                    unit_price=number(row.unit_price),
                    amount=number(row.amount),
                    tax_rate=number(row.tax_rate or "0"),
                    discount=number(row.discount or "0"),
                    attributes={
                        **attributes(row.description),
                        **{a.name: a.value for a in row.attributes},
                    },
                    evidence_ids=row.evidence_ids,
                    flags=flags,
                )
            )
        warnings.extend(result.warnings)
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
