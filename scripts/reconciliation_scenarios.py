"""Send synthetic Fund Accounting and Custodian data through the isolated SFTP demo."""

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

DATE = "2026-01-01"
PAIRS = ("MIXED", "MATCHED", "CORRECTED")
SOURCES = ("FUND_ACCOUNTING", "CUSTODIAN")
MIXED = (
    [("exact", "100.00"), ("close", "200.00"), ("difference", "300.00"), ("fund-only", "400.00"),
     ("duplicate", "500"), ("duplicate", "500"), ("ambiguous", "610"), ("ambiguous", "620")],
    [("exact", "100.00"), ("close", "200.01"), ("difference", "310.00"), ("custodian-only", "410.00"),
     ("duplicate", "500"), ("ambiguous", "610")],
)
CLEAN = [("exact", "100.00"), ("correct-balance", "250.01")]


def seed():
    from demo_http import client
    api = client()
    sources = []
    deadline = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    for side, source in enumerate(SOURCES):
        label = ("Synthetic Fund Accounting", "Synthetic Custodian")[side]
        response = api.post("/integrations", json={"name": label, "source_name": "Synthetic export"})
        response.raise_for_status()
        key = response.json()["id"]
        deliveries = {}
        for pair in PAIRS:
            response = api.post(f"/integrations/{key}/delivery-expectations", json={
                "business_date": DATE, "delivery_type": f"{source}_{pair}",
                "deadline_at": deadline, "expected_pattern": "positions.csv",
            })
            response.raise_for_status()
            deliveries[pair] = response.json()["id"]
        sources.append({"id": key, "deliveries": deliveries})
    print(json.dumps(sources))


def publish(side):
    home = Path(os.environ["DEMO_HOME"])
    with TemporaryDirectory() as local:
        batch = []
        for pair in PAIRS:
            token = pair.lower()
            folder = Path(local) / token
            folder.mkdir()
            rows = ["record_id,record_date,amount,currency,reference"]
            for index, (ref, amount) in enumerate(MIXED[side] if pair == "MIXED" else CLEAN):
                rows.append(f"S{side}-{index},{DATE},{amount},USD,{ref}")
            payload = ("\n".join(rows) + "\n").encode()
            (folder / "positions.csv").write_bytes(payload)
            (folder / "manifest.json").write_text(json.dumps({
                "contract_version": 1, "business_date": DATE, "delivery_type": f"{SOURCES[side]}_{pair}",
                "source_delivery_id": f"recon-{side}-{token}",
                "payload": {"file_name": "positions.csv", "size_bytes": len(payload), "sha256": sha256(payload).hexdigest()},
            }), encoding="utf-8")
            stage = home / "staging" / token
            batch.extend([f"mkdir {stage}", f"put {token}/positions.csv {stage}/positions.csv",
                          f"put {token}/manifest.json {stage}/manifest.json", f"rename {stage} {home}/incoming/{token}"])
        subprocess.run(["sftp", "-D", "/usr/lib/openssh/sftp-server -u 0007", "-b", "-", "localhost"],
                       cwd=local, input="\n".join(batch) + "\n", text=True, check=True)


def verify(sources):
    from concurrent.futures import ThreadPoolExecutor
    from demo_http import client
    import sys
    from uuid import uuid4

    api = client()
    prefix = "/dashboard/reconciliation"
    command = [sys.executable, "-m", "backend.app.operations_worker"]
    subprocess.run([*command, "processing", "--once"], check=True)

    def queue(pair, label, parent=None):
        response = api.post(prefix + "/definitions", json={
            "name": label, "business_date": DATE, "match_on": "reference", "tolerance": "0.01",
            "exception_limit": 1, "materiality": "5", "confirmed": parent is not None, "supersedes_run_id": parent,
            "source_a_delivery_id": sources[0]["deliveries"][pair],
            "source_b_delivery_id": sources[1]["deliveries"][pair],
        })
        response.raise_for_status()
        return response.json()["run_id"]

    def execute():
        def worker(_):
            subprocess.run([*command, "reconciliation", "--once"], check=True)
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(worker, range(2)))

    def get(run):
        response = api.get(f"{prefix}/runs/{run}")
        response.raise_for_status()
        return response.json()

    mixed = queue("MIXED", "Fund vs Custodian · exception review")
    clean = queue("MATCHED", "Fund vs Custodian · fully matched")
    execute()
    original = get(mixed)
    assert original["status"] == "COMPLETED" and original["attempts"] == 1 and original["incident_id"]
    assert original["counts"] == dict(EXACT=1, WITHIN_TOLERANCE=1, MISSING_A=1, MISSING_B=1,
                                       AMOUNT_MISMATCH=1, DUPLICATE=1, AMBIGUOUS=1, INVALID=0)
    assert get(clean)["counts"]["EXACT"] == 2
    corrected = queue("CORRECTED", "Fund vs Custodian · corrected exports", mixed)
    execute()
    result = get(corrected)
    assert result["parent_id"] == mixed and result["counts"]["EXACT"] == 2 and result["incident_id"] is None
    assert get(mixed) == original
    replay_key = str(uuid4())
    replay_path = f"{prefix}/runs/{clean}/rerun"
    for _ in range(2):
        response = api.post(replay_path, json={"confirmed": True, "request_id": replay_key})
        assert response.status_code == 202 and response.json()["run_id"] == replay_key
    crash = """
import os, sys
from uuid import UUID
from backend.app.event_worker import verified_engine
from backend.app.intake.paths import SFTP_DATA_ROOT
from backend.app.services.reconciliation import execute_run
execute_run(verified_engine(), SFTP_DATA_ROOT, UUID(sys.argv[1]), reader=lambda *_: os._exit(73))
"""
    assert subprocess.run([sys.executable, "-c", crash, replay_key], check=False, timeout=15).returncode == 73
    assert get(replay_key)["status"] == "RUNNING"
    execute()
    assert get(replay_key)["attempts"] == 2 and get(replay_key)["counts"]["EXACT"] == 2
    mismatch = next(item["index"] for item in original["items"] if item["category"] == "AMOUNT_MISMATCH")
    ai = api.post("/dashboard/copilot/investigate", headers={"X-OpsBridge-Copilot": "1"},
                  json={"reconciliation_run_id": mixed, "exception_index": mismatch})
    ai.raise_for_status()
    data = ai.json()
    assert data["provider"] == "mock"
    assert any(item["record_id"] == f"{mixed}:{mismatch}" for item in data["evidence"])
    assert data["hypotheses"][0]["key"] == "reconciliation_amount"
    history = api.get(f"/dashboard/deliveries/{sources[0]['deliveries']['MIXED']}/incidents").json()
    assert any(item["id"] == original["incident_id"] and item["notifications"] for item in history)
    if os.getenv("DEMO_RECONCILIATION_MAILPIT") == "1":
        from backend.app.event_worker import verified_engine
        from backend.app.notification_worker import dispatch, send_to_mailpit
        engine = verified_engine()
        try:
            dispatch(engine, lambda envelope: send_to_mailpit(envelope, "127.0.0.1"))
        finally:
            engine.dispose()
        history = api.get(f"/dashboard/deliveries/{sources[0]['deliveries']['MIXED']}/incidents").json()
        jobs = next(item["notifications"] for item in history if item["id"] == original["incident_id"])
        assert any(job["event"] == "OPENED" and job["status"] == "SENT" for job in jobs)
    if os.getenv("RABBITMQ_URL"):
        from backend.app.event_worker import consume_one, publish_one, verified_engine
        from backend.app.messaging import Broker
        broker = Broker(os.environ["RABBITMQ_URL"])
        engine = verified_engine()
        try:
            while publish_one(engine, broker):
                pass
            while consume_one(engine, broker):
                pass
            feed = api.get("/dashboard/activity", params={"event_type": "ReconciliationCompleted"}).json()
            assert any(item["payload"]["reconciliation_run_id"] == mixed for item in feed["items"])
        finally:
            broker.close()
            engine.dispose()
    print("Reconciliation verified: independent SFTP sources, concurrency, interruption recovery, corrected run, incidents and Copilot.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", type=int, choices=(0, 1))
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(json.loads(os.environ["DEMO_RECONCILIATION_SOURCES"]))
    elif args.side is None:
        seed()
    else:
        publish(args.side)
