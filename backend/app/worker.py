import logging
import time

from sqlalchemy import select, update

from backend.app.core.config import settings
from backend.app.db import Session
from backend.app.models import Evaluation, Run, now
from backend.app.workflow import process_run


def acquire_lock():
    # OS lock is released automatically on crash; a second local worker cannot claim jobs.
    handle = (settings.storage / "worker.lock").open("a+b")
    handle.seek(0)
    handle.write(b"0")
    handle.flush()
    handle.seek(0)
    try:
        if __import__("os").name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("A local worker is already running")
    return handle


def run_once():
    with Session() as db:
        rid = db.scalar(
            select(Run.id).where(Run.status == "QUEUED").order_by(Run.created_at).limit(1)
        )
        if rid:
            changed = db.execute(
                update(Run)
                .where(Run.id == rid, Run.status == "QUEUED")
                .values(status="PROCESSING", heartbeat=now())
            ).rowcount
            db.commit()
            if changed:
                process_run(rid)
            return True
        eid = db.scalar(
            select(Evaluation.id)
            .where(Evaluation.status == "QUEUED")
            .order_by(Evaluation.created_at)
            .limit(1)
        )
    if eid:
        from evaluation.runner import evaluate

        evaluate(eid)
        return True
    return False


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    lock = acquire_lock()
    with Session() as db:
        # Only this worker holds the OS lock, so PROCESSING records are abandoned work.
        db.execute(
            update(Run).where(Run.status == "PROCESSING").values(status="QUEUED", heartbeat=now())
        )
        db.execute(
            update(Evaluation).where(Evaluation.status == "PROCESSING").values(status="QUEUED")
        )
        db.commit()
    try:
        while True:
            (settings.storage / "worker-heartbeat").write_text(now(), encoding="utf-8")
            if not run_once():
                time.sleep(settings.local_worker_poll_seconds)
    finally:
        lock.close()


if __name__ == "__main__":
    main()
