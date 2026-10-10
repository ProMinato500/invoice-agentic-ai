import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import delete

from backend.app.core.config import settings
from backend.app.db import Session
from backend.app.extraction import extract_document
from backend.app.matching import match_lines
from backend.app.models import Allocation, Document, Event, Run, now
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


class Cancelled(Exception):
    pass


def emit(run_id, stage, status, message, data=None):
    with Session() as db:
        run = db.get(Run, run_id)
        db.add(
            Event(
                organization_id=run.organization_id,
                run_id=run_id,
                sequence=time.time_ns() // 1000,
                stage=stage,
                status=status,
                message=message,
                data=data or {},
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
        return validate(db, rid)


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
            ("VALIDATING_FINANCIALS", financial),
            ("GENERATING_REPORT", report),
        ]
        for name, fn in nodes:
            builder.add_node(name, stage(name, fn))
        builder.add_node("finish", finish)
        builder.add_edge(START, nodes[0][0])
        for (a, _), (b, _) in zip(nodes, nodes[1:]):
            builder.add_edge(a, b)
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
        with graph() as flow:
            config = {"configurable": {"thread_id": f"{rid}:v{version}"}}
            snapshot = flow.get_state(config)
            flow.invoke(
                None if snapshot.next else {"run_id": rid, "outcome": "INCOMPLETE"},
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
