"""Single-slot intake worker. Run as a separate process from the API."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
from threading import Event
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from backend.app.intake.csv_validation import validate_csv
from backend.app.intake.package import PackageValidationError, inspect_package
from backend.app.intake.paths import (
    SFTP_DATA_ROOT, accepted_claim_directory, incoming_directory,
    internal_root, quarantine_claim_directory, work_claim_directory,
)
from backend.app.intake.snapshot import Inspection, create_snapshot, inspect_snapshot, sync_directory
from backend.app.models import IntakeClaim, IntakeClaimStatus as State, IntakeFinalLocation, Integration
from backend.app.services.file_intake import committed_outcome, expectation_query
from backend.app.telemetry import READY, outcome, report, start_worker, timed


@contextmanager
def lifecycle(engine, claim_id, *, namespace="intake:claim"):
    key = {"key": f"{namespace}:{claim_id}"}
    with engine.connect() as connection:
        acquired = connection.scalar(text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), key)
        connection.commit()
        try:
            yield connection if acquired else None
        finally:
            if acquired:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), key)
                connection.commit()


def canonical_id(name):
    try:
        parsed = UUID(name)
        return parsed if str(parsed) == name else None
    except ValueError:
        return None


def claim_candidate(engine, integration_id, candidate, root):
    with engine.begin() as connection:
        locked = connection.scalar(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                                   {"key": f"intake:candidate:{integration_id}:{os.fsencode(candidate.name).hex()}"})
        if not locked or not os.path.lexists(candidate):
            return None
        claim_id = uuid4()
        work = work_claim_directory(integration_id, claim_id, root=root)
        work.parent.mkdir(parents=True, exist_ok=True)
        work.mkdir(mode=0o700)
        try:
            candidate.rename(work / "source")
        except FileNotFoundError:
            work.rmdir()
            return None
        for directory in (candidate.parent, work, work.parent, work.parent.parent):
            sync_directory(directory)
        return claim_id


def finalize(root, integration_id, claim_id, error, expected_hash=None):
    """Publish the whole claim directory by rename; resume either side of that rename."""
    work = work_claim_directory(integration_id, claim_id, root=root)
    builder = quarantine_claim_directory if error else accepted_claim_directory
    destination = builder(integration_id, claim_id, root=root)
    if work.exists():
        if destination.exists():
            raise RuntimeError("Ambiguous final package location")
        package = work / "package"
        if not os.path.lexists(package):
            candidate = work / "snapshot"
            if not candidate.exists() and error in {"INVALID_PACKAGE", "UNKNOWN_INTEGRATION"}:
                candidate = work / "source"
            candidate.rename(package)
        if error:
            pending = work / "reason.tmp"
            with pending.open("w", encoding="utf-8") as stream:
                json.dump(dict(error_code=error, integration_id=str(integration_id), claim_id=str(claim_id)), stream)
                stream.flush()
                os.fsync(stream.fileno())
            pending.replace(work / "quarantine_reason.json")
        sync_directory(work)
        destination.parent.mkdir(parents=True, exist_ok=True)
        work.rename(destination)
    if not os.path.lexists(destination / "package") or (error and not (destination / "quarantine_reason.json").is_file()):
        raise RuntimeError("Final package incomplete")
    if error not in {"INVALID_PACKAGE", "UNKNOWN_INTEGRATION"}:
        if expected_hash is None:
            inspect_package(destination / "package")
        elif inspect_snapshot(destination / "package").digest != expected_hash:
            raise RuntimeError("Final payload differs from committed claim")
    for directory in (work.parent, destination.parent, destination.parent.parent, internal_root(root=root)):
        sync_directory(directory)


@timed("intake_claim")
def process(engine, root, integration_id, claim_id):
    with lifecycle(engine, claim_id) as connection:
        if connection is None:
            return
        work = work_claim_directory(integration_id, claim_id, root=root)
        with Session(connection, expire_on_commit=False) as session:
            with session.begin():
                claim = session.get(IntakeClaim, claim_id)
                known = session.get(Integration, integration_id) is not None
                if claim and claim.integration_id != integration_id:
                    raise RuntimeError("Claim identity mismatch")
                if claim is None and known:
                    if not os.path.lexists(work / "source"):
                        return
                    claim = IntakeClaim(id=claim_id, integration_id=integration_id)
                    session.add(claim)
            if not known:
                finalize(root, integration_id, claim_id, "UNKNOWN_INTEGRATION")
                outcome("intake_claim", "unknown_integration")
                report("UNKNOWN_INTEGRATION", level=logging.WARNING, integration_id=integration_id, claim_id=claim_id)
                return
            if claim.status == State.FINALIZED:
                return
            if claim.status != State.COMMITTED:
                count = csv_error = None
                try:
                    snapshot = create_snapshot(work)
                except PackageValidationError:
                    inspection = Inspection(error="INVALID_PACKAGE")
                else:
                    if claim.status == State.CLAIMED:
                        with session.begin():
                            claim.status = State.SNAPSHOTTED
                    inspection = inspect_snapshot(snapshot)
                    if inspection.manifest and not inspection.error:
                        with session.begin():
                            if session.scalar(expectation_query(claim, inspection.manifest)):
                                claim.status = State.VALIDATED
                        count, csv_error = validate_csv(snapshot / inspection.manifest.payload.file_name)
                with session.begin():
                    committed_outcome(session, claim, inspection, count, csv_error)
            finalize(root, integration_id, claim_id, claim.error_code, claim.content_hash)
            with session.begin():
                claim.final_location = IntakeFinalLocation.QUARANTINE if claim.error_code else IntakeFinalLocation.ACCEPTED
                claim.finalized_at = datetime.now(timezone.utc)
                claim.status = State.FINALIZED
            outcome("intake_claim", "quarantined" if claim.error_code else "accepted")
            report("INTAKE_FINALIZED", integration_id=integration_id, claim_id=claim_id,
                   delivery_expectation_id=claim.delivery_expectation_id, file_id=claim.file_id)


def scan(engine, root=SFTP_DATA_ROOT):
    work = internal_root(root=root) / "work"
    work.mkdir(parents=True, exist_ok=True)
    # Include committed rows whose work directory already moved before a crash.
    with Session(engine) as session:
        pending = set(session.execute(select(IntakeClaim.integration_id, IntakeClaim.id)
                                      .where(IntakeClaim.status != State.FINALIZED)).tuples())
    for parent in work.iterdir():
        integration_id = canonical_id(parent.name)
        if integration_id and parent.is_dir():
            for folder in parent.iterdir():
                claim_id = canonical_id(folder.name)
                if claim_id and (os.path.lexists(folder / "source") or os.path.lexists(folder / "package")):
                    pending.add((integration_id, claim_id))

    def attempt(integration_id, claim_id):
        try:
            process(engine, root, integration_id, claim_id)
        except (OSError, RuntimeError, PackageValidationError):
            report("CLAIM_RETRY", level=logging.ERROR, integration_id=integration_id, claim_id=claim_id)
            return False
        return True

    ok = True
    for integration_id, claim_id in pending:
        ok = attempt(integration_id, claim_id) and ok
    for parent in root.iterdir():
        integration_id = canonical_id(parent.name)
        if not integration_id or parent.is_symlink():
            continue
        incoming = incoming_directory(integration_id, root=root)
        if incoming.is_symlink() or not incoming.is_dir():
            continue
        for candidate in incoming.iterdir():
            claim_id = claim_candidate(engine, integration_id, candidate, root)
            if claim_id:
                ok = attempt(integration_id, claim_id) and ok
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    start_worker("intake-worker")
    os.umask(0o077)
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    engine = None
    try:
        expected = os.environ.get("OPSBRIDGE_EXPECTED_DATABASE")
        url = make_url(os.environ["DATABASE_URL"])
        if expected != "opsbridge_test" or url.database != expected or url.host not in {"localhost", "127.0.0.1", "postgres"} or url.query:
            raise ValueError("Unverified intake database")
        engine = create_engine(url.set(drivername="postgresql+psycopg"), poolclass=NullPool, hide_parameters=True)
        with engine.connect() as conn:
            if conn.scalar(text("SELECT current_database()")) != expected:
                raise ValueError("Unexpected intake database")
        while not stop.is_set():
            ok = scan(engine)
            READY.labels("intake-worker").set(int(ok))
            if args.once:
                return 0 if ok else 1
            stop.wait(2)
    except Exception:
        report("WORKER_STOPPED", level=logging.ERROR)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
