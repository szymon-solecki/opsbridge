"""Prepare a synthetic expectation and publish one package using the system SFTP client."""

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.models import Integration
from backend.app.schemas.delivery_expectation import DeliveryExpectationCreate
from backend.app.services.delivery_expectations import create_delivery_expectation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("integration", type=UUID, help="Integration UUID already mapped on the demo SFTP server")
    parser.add_argument("account", type=str)
    parser.add_argument("--port", type=int, default=2222)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", args.account):
        parser.error("Invalid SFTP account name")
    url = make_url(os.environ["DATABASE_URL"])
    if (url.database != "opsbridge_test" or url.host not in {"localhost", "127.0.0.1"}
            or url.query or url.drivername not in {"postgresql", "postgresql+psycopg"}):
        parser.error("A local isolated opsbridge_test URL is required")
    engine = create_engine(url.set(drivername="postgresql+psycopg"), hide_parameters=True)
    token = uuid4().hex
    now = datetime.now(timezone.utc)
    kind = "DEMO_" + token.upper()
    with engine.connect() as connection:
        with connection.begin():
            if connection.scalar(text("SELECT current_database()")) != "opsbridge_test":
                raise SystemExit("Unexpected demo database")
        with Session(connection) as db:
            with db.begin():
                integration = db.get(Integration, args.integration)
                if integration is None:
                    db.add(Integration(id=args.integration, name=f"Synthetic {args.integration}", source_name="demo"))
            expected = create_delivery_expectation(db, args.integration, DeliveryExpectationCreate(
                delivery_type=kind, expected_pattern="payload.csv", business_date=now.date(),
                deadline_at=now + timedelta(hours=1)))
            print(f"Expectation {expected.id}", flush=True)
    data = f"record_id,record_date,amount,currency,reference\nDEMO-1,{now.date()},12.50,EUR,synthetic\n".encode()
    with TemporaryDirectory() as local:
        folder = Path(local)
        (folder / "payload.csv").write_bytes(data)
        (folder / "manifest.json").write_text(json.dumps(dict(contract_version=1, business_date=str(now.date()),
            delivery_type=kind, source_delivery_id=token,
            payload=dict(file_name="payload.csv", size_bytes=len(data), sha256=sha256(data).hexdigest()))),
            encoding="utf-8")
        remote = f"staging/{token}"
        commands = f"mkdir /{remote}\nput payload.csv /{remote}/payload.csv\nput manifest.json /{remote}/manifest.json\nrename /{remote} /incoming/{token}\n"
        subprocess.run(["sftp", "-b", "-", "-oBatchMode=yes", "-oStrictHostKeyChecking=yes",
                        "-P", str(args.port), f"{args.account}@127.0.0.1"],
                       cwd=folder, input=commands, text=True, check=True)


if __name__ == "__main__":
    main()
