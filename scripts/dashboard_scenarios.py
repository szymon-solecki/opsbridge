"""Synthetic dashboard scenario generator. Runs only within the disposable demo."""

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

INTEGRATIONS = (
    ("Northstar Treasury", "Treasury ledger"),
    ("Harbor Clearing", "Settlement gateway"),
    ("Meridian Payments", "Payment processor"),
    ("Summit Custody", "Custody reporting"),
)
KINDS = ("CASH_POSITION", "SETTLEMENT_REPORT", "FX_CONFIRMATIONS", "CUSTODY_POSITIONS",
         "PAYMENT_REGISTER", "BANK_STATEMENT", "FEE_REPORT", "LIQUIDITY_REPORT", "DAILY_RECONCILIATION")


def expectations():
    from demo_http import client

    api = client()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    identifiers = []
    for name, source in INTEGRATIONS:
        response = api.post("/integrations", json={"name": name, "source_name": source})
        response.raise_for_status()
        integration = response.json()["id"]
        identifiers.append(integration)
        for index, kind in enumerate(KINDS):
            deadline = now + timedelta(hours=4) if index == 0 or index >= 3 else now - timedelta(hours=3)
            result = api.post(f"/integrations/{integration}/delivery-expectations", json={
                "delivery_type": kind, "expected_pattern": "*.csv",
                "business_date": "2026-01-01", "deadline_at": deadline.isoformat(),
            })
            result.raise_for_status()
    print(json.dumps(identifiers))


def publish(wave: int, vendor: int):
    home = Path(os.environ["DEMO_HOME"])
    indices = range(2, len(KINDS)) if wave == 0 else (3, 4, 5)
    with TemporaryDirectory() as local:
        batch = []
        for index in indices:
            kind = KINDS[index]
            token = f"upload-{index}-{wave}"
            filename = f"{kind.lower()}-20260101.csv"
            folder = Path(local) / token
            folder.mkdir()
            rows = ["record_id,record_date,amount,currency,reference"]
            for row in range(4 + vendor * 10 + index * 7):
                amount = f"{100 + 31 * row + vendor}.{(19 * row) % 100:02d}"
                if not row and ((wave == 0 and index in (2, 3)) or (wave == 1 and index == 4)):
                    amount = "INVALID" if index != 4 else "458.75"
                currency = ("EUR", "USD", "GBP")[vendor % 3]
                rows.append(f"TX{vendor:02d}{index:02d}{row:04d},2026-01-01,{amount},{currency},REF-{kind}-{row:04d}")
            payload = ("\n".join(rows) + "\n").encode()
            (folder / filename).write_bytes(payload)
            source_id = f"source-{vendor}-{index}"
            if wave == 1 and index == 3:
                source_id += "-corrected"
            (folder / "manifest.json").write_text(json.dumps({
                "contract_version": 1, "business_date": "2026-01-01", "delivery_type": kind,
                "source_delivery_id": source_id,
                "payload": {"file_name": filename, "size_bytes": len(payload), "sha256": sha256(payload).hexdigest()},
            }), encoding="utf-8")
            stage = home / "staging" / token
            batch.extend([f"mkdir {stage}", f"put {token}/{filename} {stage}/{filename}",
                          f"put {token}/manifest.json {stage}/manifest.json", f"rename {stage} {home}/incoming/{token}"])
        subprocess.run(["sftp", "-D", "/usr/lib/openssh/sftp-server -u 0007", "-b", "-", "localhost"],
                       cwd=local, input="\n".join(batch) + "\n", text=True, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wave", type=int)
    parser.add_argument("--vendor", type=int)
    args = parser.parse_args()
    if args.wave is None:
        expectations()
    else:
        publish(args.wave, args.vendor)
