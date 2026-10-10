from collections import defaultdict
from decimal import Decimal

from sqlalchemy import delete, func, select, text

from backend.app.models import Allocation, Discrepancy, Document, Line, Match, Run
from backend.app.normalization import number, specs, unit


def validate(db, run_id):
    # Serialize allocation decisions before reading capacity. SQLite's immediate transaction
    # provides a single local writer; PostgreSQL locks the authoritative PO document row.
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    run = db.get(Run, run_id)
    po_doc = db.scalar(select(Document).where(Document.id == run.po_id).with_for_update())
    db.execute(delete(Allocation).where(Allocation.run_id == run.id))
    db.execute(delete(Discrepancy).where(Discrepancy.run_id == run.id))
    matches = list(db.scalars(select(Match).where(Match.run_id == run.id)))
    lines = {
        line.id: line
        for line in db.scalars(
            select(Line).where(
                Line.organization_id == run.organization_id,
                Line.document_id.in_([run.po_id] + run.invoice_ids),
            )
        )
    }
    docs = {
        d.id: d
        for d in db.scalars(select(Document).where(Document.id.in_([run.po_id] + run.invoice_ids)))
    }
    allocated = defaultdict(lambda: Decimal("0"))
    already_invoiced = set()
    for a in db.scalars(
        select(Allocation).where(Allocation.organization_id == run.organization_id)
    ):
        prior_run = db.get(Run, a.run_id)
        if run.policy.get("evaluation_id") or prior_run.policy.get("evaluation_id"):
            continue
        allocated[a.po_line_id] += number(a.quantity)
        already_invoiced.add(a.invoice_line_id)
    pending = []
    issues = []
    tolerance = number(run.policy.get("price_tolerance_percent", "2")) / 100
    rounding = number(run.policy.get("rounding_tolerance", "0.02"))

    def issue(code, message, severity="error", match=None, evidence=None):
        issues.append(
            Discrepancy(
                organization_id=run.organization_id,
                run_id=run.id,
                match_id=match.id if match else None,
                code=code,
                severity=severity,
                message=message,
                evidence=evidence or [],
            )
        )

    for request in run.policy.get("agent_review_requests", []):
        if request.get("version") == run.version:
            issue("AGENT_REVIEW_REQUIRED", request["reason"], "review")
    if run.policy.get("allocation_plan", {}).get("requires_review"):
        issue(
            "COMPLEX_ALLOCATION_REVIEW",
            "A global split/ambiguous allocation plan is available. Verify product grouping and authorized mapping before committing capacity.",
            "review",
        )
    po_header = po_doc.extraction.get("header", {})
    po_lines = [line for line in lines.values() if line.document_id == run.po_id]
    po_subtotal = sum((number(line.amount) for line in po_lines), Decimal("0"))
    if (
        po_header.get("subtotal") is not None
        and abs(number(po_header["subtotal"]) - po_subtotal) > rounding
    ):
        issue(
            "PO_SUBTOTAL_MISMATCH",
            "PO printed subtotal differs from extracted line amounts.",
        )
    for po_line in po_lines:
        if number(po_line.quantity) < 0 or number(po_line.unit_price) < 0:
            issue("INVALID_PO_VALUE", "PO quantities and unit prices must be nonnegative.")
        for flag in po_line.flags:
            issue(
                "PO_" + flag,
                "Purchase order line "
                + str(po_line.line_no)
                + ": "
                + flag.replace("_", " ").lower(),
                "error" if flag == "LINE_AMOUNT_MISMATCH" else "review",
                evidence=po_line.evidence,
            )
    if (
        not run.policy.get("evaluation_id")
        and po_header.get("number")
        and po_header.get("supplier")
    ):
        for other in db.scalars(
            select(Document).where(
                Document.organization_id == run.organization_id,
                Document.kind == "po",
                Document.id != run.po_id,
            )
        ):
            oh = other.extraction.get("header", {})
            if (
                oh.get("number") == po_header["number"]
                and oh.get("supplier") == po_header["supplier"]
            ):
                prior_runs = list(
                    db.scalars(select(Run).where(Run.po_id == other.id, Run.id != run.id))
                )
                if any(
                    r.outcome == "AUTO_APPROVABLE" and not r.policy.get("evaluation_id")
                    for r in prior_runs
                ):
                    issue(
                        "PO_REVISION_REVIEW_REQUIRED",
                        "Another previously allocated PO document has this supplier/PO identity. A verified revision/capacity basis is required.",
                        "review",
                    )
                    break
    if run.supporting_ids:
        issue(
            "SUPPORTING_DOCUMENT_REVIEW",
            "Supporting receipts, specifications and amendments require reviewer verification; their terms are not automatically adopted.",
            "review",
        )
    for doc_id in run.invoice_ids:
        doc = docs[doc_id]
        h = doc.extraction.get("header", {})
        inv_lines = [line for line in lines.values() if line.document_id == doc_id]
        if h.get("currency") and po_header.get("currency"):
            if h["currency"] != po_header["currency"]:
                issue(
                    "CURRENCY_MISMATCH",
                    f"PO currency {po_header['currency']}; invoice currency {h['currency']}; no authorized FX basis configured.",
                )
        else:
            issue(
                "CURRENCY_UNKNOWN",
                "Currency is not verified in both documents.",
                "review",
            )
        for key, code in [
            ("supplier", "SUPPLIER_MISMATCH"),
            ("buyer", "BUYER_MISMATCH"),
        ]:
            if h.get(key) and po_header.get(key) and h[key].casefold() != po_header[key].casefold():
                issue(code, f"{key} identity differs between the selected documents.")
            elif not h.get(key) or not po_header.get(key):
                issue(
                    "IDENTITY_UNVERIFIED",
                    f"{key} identity is absent in one or both documents.",
                    "review",
                )
        if (
            h.get("po_reference")
            and po_header.get("number")
            and h["po_reference"] != po_header["number"]
        ):
            issue(
                "PO_REFERENCE_MISMATCH",
                "Invoice references a different purchase order.",
            )
        if not h.get("number"):
            issue(
                "INVOICE_NUMBER_MISSING",
                "Invoice identity cannot be verified.",
                "review",
            )
        elif not h.get("po_reference"):
            issue(
                "PO_REFERENCE_MISSING",
                "Invoice purchase order reference is absent.",
                "review",
            )
        # Compare same invoice identity across previously completed runs, scoped by supplier and tenant.
        previous = (
            []
            if run.policy.get("evaluation_id")
            else list(
                db.scalars(
                    select(Document).where(
                        Document.organization_id == run.organization_id,
                        Document.kind == "invoice",
                        Document.id != doc.id,
                    )
                )
            )
        )
        for prior in previous:
            ph = prior.extraction.get("header", {})
            if (
                h.get("number")
                and h.get("supplier")
                and h["number"] == ph.get("number")
                and h["supplier"].casefold() == str(ph.get("supplier", "")).casefold()
            ):
                used = db.scalar(
                    select(func.count())
                    .select_from(Run)
                    .where(
                        Run.organization_id == run.organization_id,
                        Run.id != run.id,
                        Run.status.in_(["COMPLETED", "COMPLETED_WITH_DISCREPANCIES"]),
                        Run.invoice_ids.contains(prior.id),
                    )
                )
                if used and any(
                    not r.policy.get("evaluation_id")
                    for r in db.scalars(
                        select(Run).where(
                            Run.organization_id == run.organization_id,
                            Run.id != run.id,
                            Run.status.in_(["COMPLETED", "COMPLETED_WITH_DISCREPANCIES"]),
                        )
                    )
                    if prior.id in r.invoice_ids
                ):
                    issue(
                        "DUPLICATE_INVOICE",
                        "This supplier invoice number was already reconciled.",
                    )
                    break
        subtotal = sum((number(line.amount) for line in inv_lines), Decimal("0"))
        if h.get("subtotal") is not None and abs(number(h["subtotal"]) - subtotal) > rounding:
            issue(
                "SUBTOTAL_MISMATCH",
                f"Printed subtotal {h['subtotal']}; sum of line amounts {subtotal}.",
            )
        if h.get("total") is None:
            issue(
                "TOTAL_UNVERIFIED",
                "Printed grand total could not be verified.",
                "review",
            )
        else:
            if any(h.get(key) is None for key in ("tax", "freight", "discount")):
                issue(
                    "TOTAL_COMPONENTS_UNKNOWN",
                    "Tax, freight or document discount is absent; totals require review.",
                    "review",
                )
            calculated = (
                subtotal
                + number(h.get("tax") or "0")
                + number(h.get("freight") or "0")
                - number(h.get("discount") or "0")
            )
            if abs(number(h["total"]) - calculated) > rounding:
                issue(
                    "TOTAL_MISMATCH",
                    f"Printed total {h['total']}; independently calculated total {calculated}.",
                )
        if h.get("freight") is not None and number(h["freight"]) != 0:
            issue(
                "FREIGHT_REVIEW_REQUIRED",
                "Nonzero freight requires verification of the authorized charge and its cumulative billing basis.",
                "review",
            )
        if (
            h.get("discount") is not None
            and po_header.get("discount") is not None
            and number(h["discount"]) != number(po_header["discount"])
        ):
            issue(
                "DOCUMENT_DISCOUNT_REVIEW",
                "Invoice and PO document discounts differ; partial-invoice discount basis requires verification.",
                "review",
            )
        printed_tax = h.get("tax")
        calculated_tax = sum(
            (
                (number(line.amount) * number(line.tax_rate) / 100).quantize(Decimal(".01"))
                for line in inv_lines
            ),
            Decimal("0"),
        )
        if printed_tax is not None and abs(number(printed_tax) - calculated_tax) > rounding:
            issue(
                "TAX_REVIEW_REQUIRED",
                f"Printed tax {printed_tax}; extracted line-tax calculation {calculated_tax}. Tax basis/rates require source verification.",
                "review",
            )
        for warning in doc.extraction.get("warnings", []):
            if warning not in doc.extraction.get("reviewed_warnings", []):
                issue("EXTRACTION_WARNING", warning, "review")
    for match in matches:
        inv = lines[match.invoice_line_id]
        match.findings = []
        for flag in inv.flags:
            issue(
                flag,
                f"Invoice line {inv.line_no}: {flag.replace('_', ' ').lower()}.",
                "error" if flag == "LINE_AMOUNT_MISMATCH" else "review",
                match,
                inv.evidence,
            )
        if inv.id in already_invoiced:
            issue(
                "DUPLICATE_INVOICE",
                "This invoice line already has a committed quantity allocation.",
                "error",
                match,
                inv.evidence,
            )
        split = [
            p for p in run.policy.get("allocation_overrides", []) if p["invoice_line_id"] == inv.id
        ]
        if split and match.review_action == "allocation":
            evidence = list(inv.evidence)
            spec_states = []
            qty_ok = sum((number(p["quantity"]) for p in split), Decimal(0)) == number(inv.quantity)
            price_ok = True
            for piece in split:
                po = lines.get(piece["po_line_id"])
                qty = number(piece["quantity"])
                if (
                    not po
                    or po.document_id != run.po_id
                    or qty <= 0
                    or unit(po.unit) != unit(inv.unit)
                ):
                    qty_ok = False
                    issue(
                        "INVALID_ALLOCATION",
                        "Split plan contains an unauthorized or incompatible edge.",
                        "error",
                        match,
                        inv.evidence,
                    )
                    continue
                evidence.extend(po.evidence)
                spec_status, spec_findings = specs(po, inv)
                spec_states.append(spec_status)
                for finding in spec_findings:
                    issue(
                        finding["code"],
                        finding["message"],
                        finding["severity"],
                        match,
                        po.evidence + inv.evidence,
                    )
                if qty > number(po.quantity) - allocated[po.id]:
                    qty_ok = False
                    issue(
                        "QUANTITY_OVERBILL",
                        f"Split quantity {qty} exceeds PO line {po.line_no} remaining capacity.",
                        "error",
                        match,
                        evidence,
                    )
                else:
                    allocated[po.id] += qty
                    pending.append((po, inv, qty))
                if abs(number(inv.unit_price) - number(po.unit_price)) > max(
                    abs(number(po.unit_price)) * tolerance, rounding
                ):
                    price_ok = False
                    issue(
                        "PRICE_MISMATCH",
                        f"Split edge PO line {po.line_no} has a different authorized price.",
                        "error",
                        match,
                        evidence,
                    )
                if number(po.tax_rate) != number(inv.tax_rate):
                    issue(
                        "TAX_RATE_REVIEW",
                        "Split edges have differing tax rates.",
                        "review",
                        match,
                        evidence,
                    )
                if number(po.discount) or number(inv.discount):
                    issue(
                        "SPLIT_DISCOUNT_REVIEW",
                        "Split discount apportionment requires explicit verification.",
                        "review",
                        match,
                        evidence,
                    )
            if not qty_ok:
                issue(
                    "INVALID_SPLIT_QUANTITY",
                    "The split must exactly cover the invoice quantity within remaining PO capacities.",
                    "error",
                    match,
                    evidence,
                )
            match.spec_status = (
                "FAIL"
                if "FAIL" in spec_states
                else "UNKNOWN"
                if "UNKNOWN" in spec_states or not spec_states
                else "PASS"
            )
            match.quantity_status = "PASS" if qty_ok else "FAIL"
            match.price_status = "PASS" if price_ok else "FAIL"
            if (
                abs(
                    number(inv.quantity) * number(inv.unit_price)
                    - number(inv.discount)
                    - number(inv.amount)
                )
                > rounding
                and "LINE_AMOUNT_MISMATCH" not in inv.flags
            ):
                issue(
                    "LINE_AMOUNT_MISMATCH",
                    "Split invoice extended amount does not reconcile.",
                    "error",
                    match,
                    evidence,
                )
            match.findings = [
                {"code": d.code, "severity": d.severity, "message": d.message}
                for d in issues
                if d.match_id == match.id
            ]
            continue
        if match.po_line_id is None:
            match.spec_status = "UNKNOWN"
            match.quantity_status = "UNKNOWN"
            match.price_status = "UNKNOWN"
            issue(
                "NO_MATCH" if match.identity_status == "NO_MATCH" else "AMBIGUOUS_MATCH",
                match.rationale,
                "review",
                match,
                inv.evidence,
            )
            continue
        po = lines[match.po_line_id]
        match.spec_status, findings = specs(po, inv, approved=match.review_action == "substitution")
        for finding in findings:
            issue(
                finding["code"],
                finding["message"],
                finding["severity"],
                match,
                po.evidence + inv.evidence,
            )
        if match.identity_status != "SAME_PRODUCT":
            issue(
                "IDENTITY_REVIEW_REQUIRED",
                match.rationale,
                "review",
                match,
                po.evidence + inv.evidence,
            )
        if unit(inv.unit) != unit(po.unit):
            match.quantity_status = "UNKNOWN"
            issue(
                "UOM_MISMATCH",
                f"Ordered {po.unit}; invoiced {inv.unit}. Packaging equivalence is not established.",
                "review",
                match,
                inv.evidence + po.evidence,
            )
        elif number(inv.quantity) < 0:
            match.quantity_status = "UNKNOWN"
            issue(
                "CREDIT_REVIEW_REQUIRED",
                "Negative quantities require verified credit-note linkage.",
                "review",
                match,
                inv.evidence,
            )
        else:
            remaining = number(po.quantity) - allocated[po.id]
            if number(inv.quantity) > remaining:
                match.quantity_status = "FAIL"
                issue(
                    "QUANTITY_OVERBILL",
                    f"Billed {inv.quantity}; remaining ordered capacity {remaining}.",
                    "error",
                    match,
                    inv.evidence + po.evidence,
                )
            else:
                match.quantity_status = "PASS"
                allocated[po.id] += number(inv.quantity)
                pending.append((po, inv, number(inv.quantity)))
        if number(po.quantity) > 0:
            expected_discount = number(po.discount) * number(inv.quantity) / number(po.quantity)
            if abs(number(inv.discount) - expected_discount) > rounding:
                issue(
                    "DISCOUNT_MISMATCH",
                    f"Expected proportional line discount {expected_discount}; invoice discount {inv.discount}.",
                    "error",
                    match,
                    inv.evidence + po.evidence,
                )
        if number(inv.tax_rate) != number(po.tax_rate):
            issue(
                "TAX_RATE_REVIEW",
                f"PO tax rate {po.tax_rate}; invoice tax rate {inv.tax_rate}.",
                "review",
                match,
                inv.evidence + po.evidence,
            )
        price = number(po.unit_price)
        difference = abs(number(inv.unit_price) - price)
        if difference > max(abs(price) * tolerance, rounding):
            match.price_status = "FAIL"
            issue(
                "PRICE_MISMATCH",
                f"PO unit price {po.unit_price}; billed {inv.unit_price}; tolerance {tolerance * 100}%.",
                "error",
                match,
                inv.evidence + po.evidence,
            )
        else:
            match.price_status = "PASS"
        if (
            abs(
                number(inv.quantity) * number(inv.unit_price)
                - number(inv.discount)
                - number(inv.amount)
            )
            > rounding
            and "LINE_AMOUNT_MISMATCH" not in inv.flags
        ):
            issue(
                "LINE_AMOUNT_MISMATCH",
                "Extended amount differs from quantity times unit price less discount.",
                "error",
                match,
                inv.evidence,
            )
        match.findings = [
            {"code": d.code, "severity": d.severity, "message": d.message}
            for d in issues
            if d.match_id == match.id
        ]
    outcome = (
        "BLOCKED"
        if any(d.severity == "error" for d in issues)
        else "REVIEW_REQUIRED"
        if issues
        else "AUTO_APPROVABLE"
    )
    # Persist capacity only for fully validated runs. Review/blocked runs never consume stock.
    if outcome == "AUTO_APPROVABLE" and not run.policy.get("evaluation_id"):
        for po, inv, qty in pending:
            db.add(
                Allocation(
                    organization_id=run.organization_id,
                    run_id=run.id,
                    po_line_id=po.id,
                    invoice_line_id=inv.id,
                    quantity=qty,
                )
            )
    db.add_all(issues)
    run.outcome = outcome
    run.summary = {
        "lines": len(matches),
        "matched": sum(m.po_line_id is not None for m in matches),
        "unmatched": sum(m.po_line_id is None for m in matches),
        "discrepancies": len(issues),
        "spec_failures": sum(m.spec_status == "FAIL" for m in matches),
        "reviewed": sum(bool(m.reviewed) for m in matches),
        "policy_version": 1,
    }
    db.commit()
    return outcome
