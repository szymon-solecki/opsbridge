"""Explicit operator provisioning for an isolated local instance."""

import argparse
from getpass import getpass
import os
import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.routers.auth import Create
from backend.app.config import verify_database_target
from backend.app.database import get_engine
from backend.app.models.security import OperatorAccount
from backend.app.security import audit, hash_password


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--role", choices=("VIEWER", "OPERATOR", "ADMIN"), default="ADMIN")
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    engine = None
    try:
        password = sys.stdin.readline(258).rstrip("\r\n") if args.password_stdin else getpass("New operator password: ")
        body = Create(username=args.username, role=args.role, password=password)
        expected = os.environ.get("OPSBRIDGE_EXPECTED_DATABASE")
        engine = get_engine()
        verify_database_target(expected, engine.url.database)
        with Session(engine) as session, session.begin():
            verify_database_target(expected, session.scalar(text("SELECT current_database()")))
            account = OperatorAccount(username=body.username, role=body.role, active=True,
                                      password_hash=hash_password(body.password.get_secret_value()))
            session.add(account)
            session.flush()
            audit(session, "ACCOUNT_PROVISIONED", target_id=account.id)
    except Exception:
        print("Operator provisioning failed. Check the verified target, username and password policy.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
