import argparse
import json
import random
from copy import deepcopy
from pathlib import Path
from xml.sax.saxutils import escape

import pymupdf as fitz
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

rl_config.invariant = 1

ROOT = Path(__file__).resolve().parent / "generated"
SCENARIOS = [
    "happy_path",
    "specification_mismatch",
    "price_mismatch",
    "partial_invoice",
    "extra_item",
    "quantity_overbilling",
    "total_mismatch",
    "currency_mismatch",
    "missing_specification",
    "model_mismatch",
    "semantic_alias",
    "ambiguous_match",
    "scanned",
    "multi_page",
    "large_document",
]
LAYOUTS = [
    "clean_po",
    "clean_invoice",
    "minimal",
    "dense_technical",
    "borderless",
    "landscape",
    "multi_column",
    "continued_table",
    "service",
    "industrial",
    "scanned",
    "mixed",
]


def render(
    path,
    kind,
    rows,
    scenario,
    template,
    bad_total=False,
    currency="USD",
    po_number="PO-2026-0042",
):
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = (
            "Courier"
            if template == "industrial"
            else "Times-Roman"
            if template == "mixed"
            else "Helvetica"
        )
        if template == "dense_technical":
            style.fontSize = 8
            style.leading = 10
    page_size = landscape(A4) if template in ("landscape", "dense_technical") else A4
    doc = SimpleDocTemplate(
        str(path),
        pagesize=page_size,
        rightMargin=32,
        leftMargin=32,
        topMargin=30,
        bottomMargin=30,
    )
    usable = page_size[0] - 64
    subtotal = sum(r["qty"] * r["price"] for r in rows)
    heading = "Purchase Order" if kind == "po" else "Invoice"
    story = [Paragraph(heading, styles["Title"]), Spacer(1, 12)]
    fields = [
        f"{heading} Number: {po_number if kind == 'po' else 'INV-2026-' + str(sum(ord(x) for x in scenario))}",
        "Supplier: Northstar Fictional Supply Ltd",
        "Buyer: Example Research Works Ltd",
        "Address: 42 Example Avenue, Sample City",
        "Tax ID: FICTIONAL-00042",
        "Date: 2026-01-15",
        f"Currency: {currency}",
        "Payment Terms: Net 30",
        f"PO Reference: {po_number}",
    ]
    if template == "multi_column":
        meta_rows = [
            [
                Paragraph(escape(fields[i]), styles["Normal"]),
                Paragraph(escape(fields[i + 1]), styles["Normal"]) if i + 1 < len(fields) else "",
            ]
            for i in range(0, len(fields), 2)
        ]
        story.append(Table(meta_rows, colWidths=[usable / 2, usable / 2]))
    else:
        for field in fields:
            story.append(Paragraph(escape(field), styles["Normal"]))
    story.append(Spacer(1, 18))
    header = ["SKU", "Description", "Qty", "Unit", "Unit Price", "Amount"]
    widths = [
        usable * 0.14,
        usable * 0.40,
        usable * 0.08,
        usable * 0.08,
        usable * 0.15,
        usable * 0.15,
    ]
    data = [header]
    for r in rows:
        data.append(
            [
                Paragraph(escape(r["sku"]), styles["Normal"]),
                Paragraph(escape(r["description"]), styles["Normal"]),
                str(r["qty"]),
                "EA",
                f"{r['price']:.2f}",
                f"{r['qty'] * r['price']:.2f}",
            ]
        )
    if template == "service":
        data[0] = ["Code", "Service", "Quantity", "UOM", "Rate", "Net Amount"]
    if template == "mixed":
        order = [1, 0, 3, 2, 5, 4]
        data = [[row[i] for i in order] for row in data]
        widths = [widths[i] for i in order]
    if template == "minimal":
        data[0] = ["SKU", "Details", "Qty", "Unit", "Price", "Total"]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#183b56")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        (
            "ROWBACKGROUNDS",
            (0, 1),
            (-1, -1),
            [colors.white, colors.HexColor("#f1f5f9")],
        ),
    ]
    if template not in ("borderless", "minimal", "service"):
        commands.append(("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")))
    else:
        commands.append(("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#cbd5e1")))
    if template == "dense_technical":
        commands.extend(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    if template == "industrial":
        commands.extend(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Courier"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ]
        )
    if template == "clean_po":
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#365d4a")))
    if template == "borderless":
        commands = [c for c in commands if c[0] != "ROWBACKGROUNDS"]
    table.setStyle(TableStyle(commands))
    story += [table, Spacer(1, 14)]
    for label, value in [
        ("Subtotal", subtotal),
        ("Tax", 0),
        ("Freight", 0),
        ("Discount", 0),
        ("Grand Total", subtotal + (11 if bad_total else 0)),
    ]:
        story.append(Paragraph(f"{label}: {value:.2f}", styles["Normal"]))
    story += [
        Spacer(1, 12),
        Paragraph(
            "All organizations and payment details in this synthetic document are fictional. No payment should be made.",
            styles["Normal"],
        ),
    ]

    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(32, 18, f"{heading} | page {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    if template == "scanned":
        original = fitz.open(path)
        raster = fitz.open()
        for page in original:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            new = raster.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, stream=pix.tobytes("png"))
        original.close()
        raster.save(str(path) + ".scan")
        raster.close()
        Path(str(path) + ".scan").replace(path)


def generate(scenario, seed=42, po_lines=10, invoice_lines=8, template=None):
    rng = random.Random(seed)
    sku_start = 1000 if seed == 42 else rng.randint(1000, 9000)
    base_price = 100 if seed == 42 else rng.randint(80, 160)
    count = po_lines if scenario == "large_document" else 40 if scenario == "multi_page" else 3
    po = [
        {
            "sku": f"NS-{sku_start + i}",
            "description": f"Northstar model X{i + 1} laptop i7 16GB RAM 512GB SSD 3 years warranty",
            "qty": 10,
            "price": base_price + i * 25,
        }
        for i in range(count)
    ]
    inv = deepcopy(po)
    expected_codes = []
    outcome = "AUTO_APPROVABLE"
    if scenario == "specification_mismatch":
        inv[0]["description"] = inv[0]["description"].replace("16GB RAM", "8GB RAM")
        expected_codes = ["SPEC_MISMATCH"]
        outcome = "BLOCKED"
    elif scenario == "price_mismatch":
        inv[0]["price"] += 20
        expected_codes = ["PRICE_MISMATCH"]
        outcome = "BLOCKED"
    elif scenario == "partial_invoice":
        inv = inv[:1]
        inv[0]["qty"] = 3
    elif scenario == "extra_item":
        inv.append(
            {
                "sku": "EXTRA-999",
                "description": "Unordered specialty actuator model Z9",
                "qty": 2,
                "price": 90,
            }
        )
        expected_codes = ["NO_MATCH"]
        outcome = "REVIEW_REQUIRED"
    elif scenario == "quantity_overbilling":
        inv[0]["qty"] = 12
        expected_codes = ["QUANTITY_OVERBILL"]
        outcome = "BLOCKED"
    elif scenario == "total_mismatch":
        expected_codes = ["TOTAL_MISMATCH"]
        outcome = "BLOCKED"
    elif scenario == "currency_mismatch":
        expected_codes = ["CURRENCY_MISMATCH"]
        outcome = "BLOCKED"
    elif scenario == "missing_specification":
        inv[0]["description"] = "Northstar laptop model X1"
        expected_codes = ["SPEC_MISSING"]
        outcome = "REVIEW_REQUIRED"
    elif scenario == "model_mismatch":
        inv[0]["description"] = inv[0]["description"].replace("model X1", "model Y1")
        expected_codes = ["SPEC_MISMATCH"]
        outcome = "BLOCKED"
    elif scenario == "semantic_alias":
        inv[0]["sku"] = ""
        inv[0]["description"] = (
            "Laptop Northstar X1 Intel i7, RAM 16GB, SSD 512GB, warranty 36 months"
        )
        outcome = "REVIEW_REQUIRED"
    elif scenario == "ambiguous_match":
        po[1]["sku"] = po[0]["sku"]
        po[1]["description"] = po[0]["description"]
        expected_codes = ["AMBIGUOUS_MATCH"]
        outcome = "REVIEW_REQUIRED"
    elif scenario == "large_document":
        inv = inv[:invoice_lines]
    folder = ROOT / (scenario + "--" + template if template else scenario)
    folder.mkdir(parents=True, exist_ok=True)
    layout = template or (
        "scanned"
        if scenario == "scanned"
        else "continued_table"
        if scenario == "multi_page"
        else "clean_invoice"
    )
    render(
        folder / "purchase_order.pdf",
        "po",
        po,
        scenario,
        "clean_po" if scenario != "scanned" else "scanned",
    )
    render(
        folder / "invoice.pdf",
        "invoice",
        inv,
        scenario,
        layout,
        bad_total=scenario == "total_mismatch",
        currency="EUR" if scenario == "currency_mismatch" else "USD",
    )
    pairs = []
    for i, row in enumerate(inv):
        matching = [j for j, r in enumerate(po) if r["sku"] == row["sku"] and row["sku"]]
        pairs.append(
            {
                "invoice_line": i + 1,
                "po_line": matching[0] + 1 if len(matching) == 1 else None,
            }
        )
    if scenario == "semantic_alias":
        pairs[0]["po_line"] = 1
    truth = {
        "pairs": pairs,
        "expected_codes": expected_codes,
        "outcome": outcome,
        "po_line_count": len(po),
        "invoice_line_count": len(inv),
    }
    manifest = {
        "id": folder.name,
        "name": scenario.replace("_", " ").title()
        + (" - " + template.replace("_", " ") if template else ""),
        "seed": seed,
        "template": layout,
        "documents": ["purchase_order.pdf", "invoice.pdf"],
        "synthetic": True,
        "intended_recovery": "OCR"
        if scenario == "scanned"
        else "semantic comparison"
        if scenario == "semantic_alias"
        else "deterministic validation",
    }
    for name, data in [
        ("manifest.json", manifest),
        ("ground_truth.json", truth),
        ("expected_discrepancies.json", expected_codes),
        (
            "generation_metadata.json",
            {
                "seed": seed,
                "layout": layout,
                "fictional": True,
                "corruption": {"raster_dpi": 108} if scenario == "scanned" else {},
            },
        ),
    ]:
        (folder / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["generate"])
    p.add_argument("--all", action="store_true")
    p.add_argument("--scenario", choices=SCENARIOS, default="happy_path")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--po-lines", type=int, default=5000)
    p.add_argument("--invoice-lines", type=int, default=3000)
    p.add_argument("--template", choices=LAYOUTS)
    args = p.parse_args()
    for scenario in SCENARIOS if args.all else [args.scenario]:
        # --all includes a bounded large example; explicitly requested stress sizes remain honored.
        n = 100 if args.all and scenario == "large_document" else args.po_lines
        m = 60 if args.all and scenario == "large_document" else args.invoice_lines
        print(json.dumps(generate(scenario, args.seed, n, m, args.template)))
    if args.all and not args.template:
        for layout in LAYOUTS:
            print(
                json.dumps(
                    generate(
                        "multi_page" if layout == "continued_table" else "happy_path",
                        args.seed,
                        template=layout,
                    )
                )
            )


if __name__ == "__main__":
    main()
