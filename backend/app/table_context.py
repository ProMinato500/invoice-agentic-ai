"""Evidence-backed table context. Classification and continuation are advisory."""

import re
from copy import deepcopy


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def table_kind(title, columns):
    text = " ".join([title, *columns]).lower()
    if "delivery schedule" in text or ("delivery" in text and "dispatch" in text):
        return "delivery_schedule"
    if "payment schedule" in text or "milestone" in text:
        return "payment_schedule"
    # Priced items often contain HSN/GST columns themselves; they are not tax summaries.
    if re.search(r"quantity|\bqty\b", text) and re.search(r"unit price|unit cost|\brate\b", text):
        return "priced_items"
    if ("hsn" in text or "sac" in text) and ("tax" in text or "cgst" in text):
        return "tax_summary"
    return "unknown"


def finish_table(table):
    cells = table["cells"]
    headers = [c for c in cells if c["column_header"]]
    if not headers:
        first = [c for c in cells if c["row"] == 0]
        # Never turn a numeric first data row into a header.
        words = " ".join(c["text"] for c in first).lower()
        if re.search(
            r"description|quantity|\bqty\b|material code|hsn|unit price|delivery|amount", words
        ):
            headers = first
            table["header_basis"] = "inferred_first_row"
        else:
            table["header_basis"] = "missing"
    else:
        table["header_basis"] = "parser_column_header"
    header_ids = {id(c) for c in headers}
    table["headers"] = headers
    table["columns"] = []
    for col in range(table["num_cols"]):
        labels = [
            c["text"]
            for c in headers
            if c["col"] <= col < c["col"] + c["col_span"] and clean(c["text"])
        ]
        table["columns"].append(" / ".join(dict.fromkeys(labels)) or f"Column {col + 1}")
    table["rows"] = []
    for row in range(table["num_rows"]):
        entries = [c for c in cells if c["row"] == row and id(c) not in header_ids]
        if entries:
            table["rows"].append({"index": row, "cells": entries})
    table["type_hint"] = table_kind(table["title"], table["columns"])
    table["classification_basis"] = "header_and_title_hint_requires_semantic_verification"
    return table


def build_tables(raw, elements):
    """Works on new and historical Docling output without altering stored parser data."""
    known = {e.id: e for e in elements}
    result = deepcopy(raw.get("_native_table_context", [])) if not raw.get("tables") else []
    texts = {t.get("self_ref"): t.get("text", "") for t in raw.get("texts", [])}
    for index, source in enumerate(raw.get("tables", [])):
        data = source.get("data", {})
        prov = source.get("prov", [])
        if not prov:
            continue
        page = prov[0]["page_no"]
        table = {
            "id": f"table-{index + 1}",
            "page": page,
            "title": " ".join(texts.get(c.get("$ref"), "") for c in source.get("captions", [])),
            "num_cols": data.get("num_cols", 0),
            "num_rows": data.get("num_rows", 0),
            "cells": [],
        }
        for cell in data.get("table_cells", []):
            eid = cell.get("_evidence_id")
            e = known.get(eid)
            if e is None:
                # Historical files predate explicit IDs. Match both text and geometry.
                box = cell.get("bbox") or {}
                candidates = [
                    x
                    for x in elements
                    if x.page == page
                    and x.method == "DOCLING_CELL"
                    and clean(x.raw_text) == clean(cell.get("text"))
                    and abs(x.bbox[0] - box.get("l", -999)) < 2
                    and abs(x.bbox[2] - box.get("r", -999)) < 2
                ]
                if box.get("coord_origin") == "TOPLEFT":
                    candidates = [
                        x for x in candidates if abs(x.bbox[1] - min(box["t"], box["b"])) < 2
                    ]
                else:
                    height = raw.get("pages", {}).get(str(page), {}).get("size", {}).get("height")
                    if height is not None:
                        candidates = [
                            x
                            for x in candidates
                            if abs(x.bbox[1] - (height - max(box["t"], box["b"]))) < 2
                        ]
                    else:
                        candidates = []
                e = candidates[0] if len(candidates) == 1 else None
            row, col = cell.get("start_row_offset_idx", 0), cell.get("start_col_offset_idx", 0)
            table["cells"].append(
                {
                    "row": row,
                    "col": col,
                    "row_span": max(1, cell.get("end_row_offset_idx", row + 1) - row),
                    "col_span": max(1, cell.get("end_col_offset_idx", col + 1) - col),
                    "column_header": bool(cell.get("column_header")),
                    "row_header": bool(cell.get("row_header")),
                    "text": cell.get("text", ""),
                    "evidence_ids": [e.id] if e else [],
                    "bbox": e.bbox if e else None,
                    "page": page,
                }
            )
        boxes = [c["bbox"] for c in table["cells"] if c["bbox"]]
        if not table["title"] and boxes:
            top = min(b[1] for b in boxes)
            nearby = [
                e
                for e in elements
                if e.page == page
                and e.method in ("DOCLING_TEXT", "PYMUPDF_SOURCE")
                and 0 <= top - e.bbox[3] <= 50
                and len(e.raw_text) < 180
            ]
            if nearby:
                table["title"] = max(nearby, key=lambda e: e.bbox[3]).raw_text
                table["title_basis"] = "nearest_preceding_text_hint"
        result.append(finish_table(table))
    for table in result:
        preceding = [
            t
            for t in result
            if t["page"] == table["page"] - 1
            and t["num_cols"] == table["num_cols"]
            and t.get("header_basis") != "missing"
        ]
        same = [t for t in preceding if t["columns"] == table["columns"]]
        if len(same) == 1:
            table["continues_table_id"] = same[0]["id"]
            table["continuation_basis"] = "same_headers_adjacent_page_hint"
        elif table.get("header_basis") == "missing" and len(preceding) == 1:
            # Retain suggested headers but require review; column count alone is not proof.
            previous = preceding[0]
            table["possible_continuation_of"] = previous["id"]
            table["suggested_columns"] = previous["columns"]
            table["suggested_headers"] = previous["headers"]
            table["continuation_basis"] = "ambiguous_requires_vision_or_review"
    # Explicit identifiers link related tables as evidence hints, never quantity/price overrides.
    index = {}
    for table in result:
        table["related_rows"] = []
        for col, label in enumerate(table["columns"]):
            if not re.search(
                r"material code|item code|sku|part number|line no|item no", label, re.I
            ):
                continue
            for row in table["rows"]:
                for cell in row["cells"]:
                    if cell["col"] != col or not clean(cell["text"]):
                        continue
                    category = "line" if re.search(r"line no|item no", label, re.I) else "material"
                    value = clean(cell["text"]).upper()
                    if category == "line" and value.isdigit():
                        value = str(int(value))
                    index.setdefault((category, value), []).append((table, row, cell))
    for (category, value), hits in index.items():
        for table, row, cell in hits:
            others = [
                {
                    "table_id": t["id"],
                    "page": t["page"],
                    "row": r["index"],
                    "evidence_ids": c["evidence_ids"],
                }
                for t, r, c in hits
                if t["id"] != table["id"]
            ]
            if others:
                table["related_rows"].append(
                    {
                        "row": row["index"],
                        "identifier_type": category,
                        "printed_identifier": cell["text"],
                        "targets": others,
                        "status": "EXPLICIT_IDENTIFIER_HINT_REQUIRES_VERIFICATION",
                    }
                )
    return result


def recovery_chunks(elements, tables, limit=120):
    """Complete rows, repeated headers and titles; only supplied IDs may be cited."""
    known = {e.id: e for e in elements}
    used = set()
    chunks = []
    for table in tables:
        headers = table["headers"] + table.get("suggested_headers", [])
        header_ids = {i for c in headers for i in c["evidence_ids"]}
        group, count = [], 0
        for row in table["rows"]:
            open_span_end = max(
                (c["row"] + c["row_span"] for r in group for c in r["cells"]), default=0
            )
            if group and count + len(row["cells"]) > limit and row["index"] >= open_span_end:
                chunks.append(_chunk(table, group, header_ids, known, used))
                group, count = [], 0
            group.append(row)
            count += len(row["cells"])
        if group:
            chunks.append(_chunk(table, group, header_ids, known, used))
        used.update(i for c in table["cells"] for i in c["evidence_ids"])
    boxes = []
    for table in tables:
        rects = [c["bbox"] for c in table["cells"] if c["bbox"]]
        if rects:
            boxes.append(
                (
                    table["page"],
                    [
                        min(b[0] for b in rects),
                        min(b[1] for b in rects),
                        max(b[2] for b in rects),
                        max(b[3] for b in rects),
                    ],
                )
            )

    def duplicate_table_text(e):
        return any(
            page == e.page
            and e.bbox[0] >= b[0] - 2
            and e.bbox[1] >= b[1] - 2
            and e.bbox[2] <= b[2] + 2
            and e.bbox[3] <= b[3] + 2
            for page, b in boxes
        )

    rest = [e for e in elements if e.id not in used and not duplicate_table_text(e)]
    chunks.extend(
        {"elements": rest[i : i + limit], "tables": []} for i in range(0, len(rest), limit)
    )
    return chunks or [{"elements": [], "tables": []}]


def _chunk(table, rows, header_ids, known, used):
    ids = header_ids | {i for r in rows for c in r["cells"] for i in c["evidence_ids"]}
    used.update(ids)
    context = {k: v for k, v in table.items() if k not in ("cells", "rows")}
    context["rows"] = rows
    return {"elements": [known[i] for i in sorted(ids) if i in known], "tables": [context]}
