from hashlib import sha256
from types import SimpleNamespace

import pytest

from backend.app.api.routers.dashboard import ReprocessingRequest
from backend.app.services.processing import reconcile


def test_reconcile_counts_signed_records_and_detects_changed_bytes(tmp_path):
    data = (b"record_id,record_date,amount,currency,reference\n"
            b"a,2026-01-01,-1.00,EUR,\nb,2026-01-01,20,EUR,batch\nc,2026-01-01,0,USD,\n")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    payload = tmp_path / "ledger.csv"
    payload.write_bytes(data)
    file = SimpleNamespace(original_name="ledger.csv", size_bytes=len(data), content_hash=sha256(data).hexdigest())
    result = reconcile(tmp_path, file)
    assert (result.error, result.record_count, result.debit_count, result.credit_count, result.zero_count) == (
        None, 3, 1, 1, 1,
    )
    payload.write_bytes(data.replace(b"20", b"21"))
    assert reconcile(tmp_path, file).error == "SNAPSHOT_INVALID"
    assert reconcile(tmp_path / "unavailable", file).error == "STORAGE_UNAVAILABLE"


@pytest.mark.parametrize("override", [{"confirmed": 1}, {"attempt_series": "1"}, {"actor": "  "},
                                    {"actor": "attacker\noperator"}, {"path": "ledger.csv"}])
def test_reprocessing_request_rejects_invalid_inputs(override):
    from pydantic import ValidationError

    data = dict(file_id="2b78c028-c031-42ff-b632-911b99370640", actor="demo-operator",
                attempt_series=1, confirmed=True)
    with pytest.raises(ValidationError):
        ReprocessingRequest.model_validate(data | override)
