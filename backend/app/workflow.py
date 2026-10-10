import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import delete, select, text

from backend.app.agents import exception_stage, source_reinspection_stage, specification_stage
from backend.app.ai import run_budget
from backend.app.core.config import settings
from backend.app.db import Session
from backend.app.extraction import extract_document
from backend.app.matching import match_lines
from backend.app.models import Allocation, Discrepancy, Document, Event, Run, now, uid
from backend.app.optimization import allocation_stage
from backend.app.reports import build_reports
from backend.app.retrieval import index_po
from backend.app.validation import validate

log = logging.getLogger(__name__)
TERMINAL = {
    "COMPLETED",
    "COMPLETED_WITH_DISCREPANCIES",
    "FAILED",
    "CANCELLED",
    "WAITING_FOR_REVIEW",
}


class State(TypedDict):
    run_id: str
    outcome: str
    version: int


class Cancelled(Exception):
    pass


def emit(run_id, stage, status, message, data=None):
    import json

    from backend.app.trace import public_trace

    with Session() as db:
        if db.bind.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        run = db.get(Run, run_id)
        last_sequence = (
            db.scalar(select(Event.sequence).order_by(Event.sequence.desc()).limit(1)) or 0
        )
        event_id = uid()
        payload = public_trace(data or {})
        folder = settings.storage / "traces" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        trace = {
            "stage": stage,
            "status": status,
            "message": message,
            "version": run.version,
            "data": payload,
        }
        (folder / (event_id + ".json")).write_text(
            json.dumps(trace, default=str, ensure_ascii=False), encoding="utf-8"
        )
        # SSE carries compact references; trace endpoint serves the full persisted output.
        compact = {
            k: v
            for k, v in payload.items()
            if k not in ("input", "output", "schema", "tools", "snapshot", "elements", "raw")
        }
        if len(json.dumps(compact, default=str)) > 5000:
            compact = {
                "document_id": payload.get("document_id"),
                "detail": "Open the saved trace for full output",
            }
        compact.update(version=run.version, trace_available=True)
        db.add(
            Event(
                id=event_id,
                organization_id=run.organization_id,
                run_id=run_id,
                sequence=max(time.time_ns() // 1000, last_sequence + 1),
                stage=stage,
                status=status,
                message=message,
                data=compact,
            )
        )
        run.stage = stage
        run.heartbeat = now()
        db.commit()


def check(run_id):
    with Session() as db:
        run = db.get(Run, run_id)
        if run.cancel_requested:
            raise Cancelled()
        if (
            run.started_at
            and (
                datetime.now(timezone.utc) - datetime.fromisoformat(run.started_at)
            ).total_seconds()
            > settings.job_timeout_seconds
        ):
            raise TimeoutError("JOB_TIMEOUT: configured processing time budget exceeded")


def stage(name, fn):
    def node(state):
        rid = state["run_id"]
        check(rid)
        emit(rid, name, "STARTED", name.replace("_", " ").title())
        result = fn(
            rid,
            lambda status, message, data=None: emit(rid, name, status, message, data),
        )
        check(rid)
        emit(rid, name, "COMPLETED", name.replace("_", " ").title() + " finished")
        return {"outcome": result} if isinstance(result, str) else {}

    return node


def extracting(rid, send):
    with Session() as db:
        run = db.get(Run, rid)
        for docid in list(dict.fromkeys([run.po_id] + run.invoice_ids + run.supporting_ids)):
            check(rid)
            extract_document(db, db.get(Document, docid), send)


def indexing(rid, send):
    with Session() as db:
        run = db.get(Run, rid)
        index_po(db, run.po_id, run.organization_id, send)


def matching(rid, send):
    with Session() as db:
        run = db.get(Run, rid)
        match_lines(db, run, send)


def financial(rid, send):
    with Session() as db:
        outcome = validate(db, rid)
        run = db.get(Run, rid)
        findings = list(db.query(Discrepancy).filter_by(run_id=rid))
        send(
            "VALIDATION_RESULT",
            "Financial and policy checks complete",
            {
                "outcome": outcome,
                "output": {
                    "summary": run.summary,
                    "findings": [
                        {
                            "code": f.code,
                            "severity": f.severity,
                            "message": f.message,
                            "evidence": f.evidence,
                        }
                        for f in findings
                    ],
                },
            },
        )
        return outcome


def report(rid, send):
    with Session() as db:
        run = db.get(Run, rid)
        build_reports(db, run)
        send(
            "REPORT_CREATED",
            "PDF, CSV and JSON reports generated",
            {"version": run.version},
        )


def finish(state):
    rid = state["run_id"]
    with Session() as db:
        run = db.get(Run, rid)
        if state.get("version") != run.version:
            # Consume the old review interrupt without touching the newer result.
            interrupt({"run_id": rid, "reason": "Superseded result version"})
            return {}
        run.status = (
            "WAITING_FOR_REVIEW"
            if run.outcome == "REVIEW_REQUIRED"
            else "COMPLETED_WITH_DISCREPANCIES"
            if run.outcome == "BLOCKED"
            else "COMPLETED"
        )
        run.stage = run.status
        run.finished_at = now()
        db.commit()
        status = run.status
    emit(
        rid,
        status,
        "COMPLETED",
        "Reconciliation ready for review"
        if status == "WAITING_FOR_REVIEW"
        else "Reconciliation finished",
    )
    if status == "WAITING_FOR_REVIEW":
        interrupt(
            {
                "run_id": rid,
                "reason": "Human review required. Corrections create a new audited result version.",
            }
        )
    return {}


@contextmanager
def graph():
    with SqliteSaver.from_conn_string(str(settings.storage / "checkpoints.db")) as saver:
        builder = StateGraph(State)
        nodes = [
            ("EXTRACTING", extracting),
            ("INDEXING", indexing),
            ("MATCHING", matching),
            ("OPTIMIZING_ALLOCATIONS", allocation_stage),
            ("VALIDATING_SPECIFICATIONS", specification_stage),
            ("VALIDATING_FINANCIALS", financial),
            ("GENERATING_REPORT", report),
        ]
        for name, fn in nodes:
            builder.add_node(name, stage(name, fn))
        builder.add_node("finish", finish)
        builder.add_edge(START, nodes[0][0])
        for (a, _), (b, _) in zip(nodes, nodes[1:]):
            if a not in {"EXTRACTING", "VALIDATING_FINANCIALS"}:
                builder.add_edge(a, b)
        builder.add_node("RECOVERING_SOURCE", stage("RECOVERING_SOURCE", source_reinspection_stage))

        def extraction_route(state):
            with Session() as db:
                run = db.get(Run, state["run_id"])
                request = run.policy.get("source_reinspection", {})
                return "recover" if request.get("version") == run.version else "index"

        builder.add_conditional_edges(
            "EXTRACTING", extraction_route, {"recover": "RECOVERING_SOURCE", "index": "INDEXING"}
        )
        builder.add_edge("RECOVERING_SOURCE", "INDEXING")
        builder.add_node(
            "INVESTIGATING_EXCEPTIONS", stage("INVESTIGATING_EXCEPTIONS", exception_stage)
        )
        builder.add_node("REVALIDATING", stage("REVALIDATING", financial))
        builder.add_conditional_edges(
            "VALIDATING_FINANCIALS",
            lambda state: (
                "investigate" if state["outcome"] in {"BLOCKED", "REVIEW_REQUIRED"} else "report"
            ),
            {"investigate": "INVESTIGATING_EXCEPTIONS", "report": "GENERATING_REPORT"},
        )
        builder.add_edge("INVESTIGATING_EXCEPTIONS", "REVALIDATING")
        builder.add_edge("REVALIDATING", "GENERATING_REPORT")
        builder.add_edge(nodes[-1][0], "finish")
        builder.add_edge("finish", END)
        yield builder.compile(checkpointer=saver)


def process_run(rid):
    with Session() as db:
        run = db.get(Run, rid)
        run.status = "PROCESSING"
        run.started_at = run.started_at or now()
        run.heartbeat = now()
        run.attempt += 1
        version = run.version
        db.commit()
    try:
        with run_budget(rid), graph() as flow:
            if version > 1:
                previous_config = {"configurable": {"thread_id": f"{rid}:v{version - 1}"}}
                previous = flow.get_state(previous_config)
                if previous.interrupts:
                    flow.invoke(
                        Command(resume={"reviewed_version": version - 1, "new_version": version}),
                        previous_config,
                    )
                    emit(
                        rid,
                        "HUMAN_REVIEW",
                        "RESUMED",
                        "Prior review checkpoint resumed; recomputing the audited new version",
                        {"superseded_version": version - 1},
                    )
            config = {"configurable": {"thread_id": f"{rid}:v{version}"}}
            snapshot = flow.get_state(config)
            flow.invoke(
                None
                if snapshot.next
                else {"run_id": rid, "outcome": "INCOMPLETE", "version": version},
                config,
            )
    except Cancelled:
        with Session() as db:
            db.execute(delete(Allocation).where(Allocation.run_id == rid))
            run = db.get(Run, rid)
            run.outcome = "INCOMPLETE"
            run.status = "CANCELLED"
            run.stage = "CANCELLED"
            run.finished_at = now()
            db.commit()
        emit(rid, "CANCELLED", "CANCELLED", "Cancelled at a safe stage boundary")
    except Exception as exc:
        log.exception("Run failed: %s", rid)
        with Session() as db:
            db.execute(delete(Allocation).where(Allocation.run_id == rid))
            run = db.get(Run, rid)
            run.outcome = "INCOMPLETE"
            run.status = "FAILED"
            run.error = f"{type(exc).__name__}: {str(exc)[:1800]}"
            run.finished_at = now()
            db.commit()
        emit(
            rid,
            "FAILED",
            "FAILED",
            "Processing failed",
            {"error": type(exc).__name__, "reason": str(exc)[:1800]},
        )
