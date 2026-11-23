"""Dedicated SLA and processing worker entry points in the modular monolith."""

import argparse
import logging
import os
import signal
from threading import Event

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from backend.app.intake.paths import SFTP_DATA_ROOT
from backend.app.services.processing import scan_processing
from backend.app.services.sla import detect_overdue
from backend.app.services.reconciliation import scan_reconciliation
from backend.app.telemetry import READY, report, start_worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("sla", "processing", "reconciliation"))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker = args.mode + "-worker"
    start_worker(worker)
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    engine = None
    try:
        url = make_url(os.environ["DATABASE_URL"])
        if (os.getenv("OPSBRIDGE_EXPECTED_DATABASE") != "opsbridge_test"
                or url.database != "opsbridge_test" or url.host not in {"localhost", "127.0.0.1", "postgres"} or url.query
                or url.drivername not in {"postgresql", "postgresql+psycopg"}):
            raise ValueError("Unverified operations database")
        engine = create_engine(url.set(drivername="postgresql+psycopg"), poolclass=NullPool, hide_parameters=True)
        with engine.connect() as connection:
            if connection.scalar(text("SELECT current_database()")) != "opsbridge_test":
                raise ValueError("Unexpected operations database")
        while not stop.is_set():
            if args.mode == "sla":
                with Session(engine) as session, session.begin():
                    detect_overdue(session)
            elif args.mode == "processing":
                scan_processing(engine, SFTP_DATA_ROOT)
            else:
                scan_reconciliation(engine, SFTP_DATA_ROOT)
            READY.labels(worker).set(1)
            if args.once:
                return 0
            stop.wait(2)
    except Exception:
        READY.labels(worker).set(0)
        report("WORKER_STOPPED", level=logging.ERROR)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
