import hashlib
import json
import time

from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.db import Session
from backend.app.models import Discrepancy, Evaluation, Line, Match, Run
from backend.app.storage import store_pdf
from backend.app.workflow import process_run
from synthetic_data.__main__ import ROOT


def evaluate(eid):
    with Session() as db:
        evaluation = db.get(Evaluation, eid)
        evaluation.status = "PROCESSING"
        db.commit()
        scenario_ids = evaluation.scenario_ids
        org = evaluation.organization_id
    results = []
    try:
        for sid in scenario_ids:
            folder = ROOT / sid
            started = time.perf_counter()
            with Session() as db:
                po, _ = store_pdf(
                    db,
                    (folder / "purchase_order.pdf").read_bytes(),
                    "purchase_order.pdf",
                    "po",
                    org,
                )
                inv, _ = store_pdf(
                    db,
                    (folder / "invoice.pdf").read_bytes(),
                    "invoice.pdf",
                    "invoice",
                    org,
                )
                run = Run(
                    organization_id=org,
                    po_id=po.id,
                    invoice_ids=[inv.id],
                    policy={
                        "price_tolerance_percent": "2",
                        "rounding_tolerance": "0.02",
                        "version": 1,
                        "evaluation_id": eid,
                        "synthetic_benchmark": True,
                    },
                )
                db.add(run)
                db.commit()
                rid = run.id
            process_run(rid)
            # Give interactive jobs priority between benchmark scenarios.
            with Session() as db:
                pending = list(
                    db.scalars(
                        select(Run.id)
                        .where(Run.status == "QUEUED", Run.id != rid)
                        .order_by(Run.created_at)
                        .limit(5)
                    )
                )
            for pending_id in pending:
                process_run(pending_id)
            # Ground truth is only loaded after inference finishes, never provided to the workflow.
            truth_bytes = (folder / "ground_truth.json").read_bytes()
            truth = json.loads(truth_bytes)
            truth_hash = hashlib.sha256(truth_bytes).hexdigest()
            truth_snapshot = settings.storage / "evaluation_truth" / eid
            truth_snapshot.mkdir(parents=True, exist_ok=True)
            (truth_snapshot / (sid + ".json")).write_bytes(truth_bytes)
            with Session() as db:
                run = db.get(Run, rid)
                matches = list(db.scalars(select(Match).where(Match.run_id == rid)))
                codes = set(db.scalars(select(Discrepancy.code).where(Discrepancy.run_id == rid)))
                predicted = {
                    db.get(Line, m.invoice_line_id).line_no: db.get(Line, m.po_line_id).line_no
                    if m.po_line_id
                    else None
                    for m in matches
                }
                actual = {p["invoice_line"]: p["po_line"] for p in truth["pairs"]}
                tp = sum(v is not None and predicted.get(k) == v for k, v in actual.items())
                expected = sum(v is not None for v in actual.values())
                mapped = sum(v is not None for v in predicted.values())
                precision = tp / mapped if mapped else 0
                recall = tp / expected if expected else 1
                recall_k = (
                    sum(
                        any(
                            db.get(Line, c["po_line_id"]).line_no
                            == actual.get(db.get(Line, m.invoice_line_id).line_no)
                            for c in m.candidates
                        )
                        for m in matches
                        if actual.get(db.get(Line, m.invoice_line_id).line_no) is not None
                    )
                    / expected
                    if expected
                    else 1
                )
                results.append(
                    {
                        "scenario_id": sid,
                        "ground_truth_sha256": truth_hash,
                        "run_id": rid,
                        "status": run.status,
                        "outcome": run.outcome,
                        "expected_outcome": truth["outcome"],
                        "outcome_correct": run.outcome == truth["outcome"],
                        "precision": precision,
                        "recall": recall,
                        "f1": 2 * precision * recall / (precision + recall)
                        if precision + recall
                        else 0,
                        "candidate_recall_at_5": recall_k,
                        "discrepancy_detection": all(c in codes for c in truth["expected_codes"]),
                        "false_approval": run.outcome == "AUTO_APPROVABLE"
                        and truth["outcome"] != "AUTO_APPROVABLE",
                        "extracted_lines": len(matches),
                        "expected_lines": truth["invoice_line_count"],
                        "runtime_seconds": round(time.perf_counter() - started, 3),
                        "error": run.error,
                    }
                )
            with Session() as db:
                progress = db.get(Evaluation, eid)
                progress.results = {
                    "synthetic_benchmark": True,
                    "scenarios": results,
                    "processed": len(results),
                    "total": len(scenario_ids),
                }
                db.commit()
        with Session() as db:
            evaluation = db.get(Evaluation, eid)
            evaluation.status = "COMPLETED"
            evaluation.results = {
                "synthetic_benchmark": True,
                "scenarios": results,
                "mean_f1": sum(r["f1"] for r in results) / len(results),
                "false_approvals": sum(r["false_approval"] for r in results),
                "note": "Only executed scenarios are measured. LLM cost is not estimated without configured pricing.",
            }
            db.commit()
    except Exception as exc:
        with Session() as db:
            evaluation = db.get(Evaluation, eid)
            evaluation.status = "FAILED"
            evaluation.error = str(exc)
            evaluation.results = {"scenarios": results}
            db.commit()
