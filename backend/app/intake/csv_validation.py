"""Technical validation of the single V1 vendor CSV contract."""

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from backend.app.intake.package import MAX_PAYLOAD_SIZE_BYTES


def validated_records(stream):
    """Yield typed records after checking the CSV contract."""
    csv.field_size_limit(MAX_PAYLOAD_SIZE_BYTES)
    try:
        rows = csv.reader(stream, strict=True)
        if next(rows, None) != ["record_id", "record_date", "amount", "currency", "reference"]:
            raise ValueError("CSV_HEADER_INVALID")
        for row in rows:
            if len(row) != 5:
                raise ValueError("CSV_ROW_INVALID")
            record, day, value, currency, reference = row
            if not record.strip() or not currency.strip() or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
                raise ValueError("CSV_ROW_INVALID")
            day = date.fromisoformat(day)
            amount = Decimal(value)
            if not amount.is_finite():
                raise ValueError("CSV_ROW_INVALID")
            yield record, day, amount, currency, reference
    except (ValueError, InvalidOperation, csv.Error) as exc:
        if str(exc) == "CSV_HEADER_INVALID":
            raise
        raise ValueError("CSV_ROW_INVALID") from None


def validated_amounts(stream):
    for _, _, amount, _, _ in validated_records(stream):
        yield amount


def validate_csv(path: Path) -> tuple[int | None, str | None]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        try:
            return sum(1 for _ in validated_amounts(stream)), None
        except ValueError as exc:
            return None, str(exc)
