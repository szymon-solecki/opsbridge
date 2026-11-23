from datetime import date
from decimal import Decimal, localcontext

from backend.app.services.matching import match


DAY = date(2026, 1, 1)


def source(*records):
    return [(str(index), DAY, Decimal(value), "USD", key) for index, (key, value) in enumerate(records)]


def test_reconciliation_classes_and_order_independence():
    left = source(("exact", "100"), ("close", "4.01"), ("far", "7"), ("left", "-3"),
                  ("repeat", "1"), ("repeat", "1.0"), ("ambiguous", "2"), ("ambiguous", "3"), ("", "5"))
    right = source(("exact", "100.000000"), ("close", "4"), ("far", "7.010001"), ("right", "9"),
                   ("repeat", "1"), ("ambiguous", "2"))
    args = dict(business_date=DAY, match_on="reference", tolerance=Decimal("0.01"), materiality=Decimal("9"))
    outcome = match(left, right, **args)
    assert outcome == match(reversed(left), reversed(right), **args)
    assert set(outcome[2].values()) == {1}
    assert outcome[3] is True
    mismatches = [row for row in outcome[1] if row["category"] == "AMOUNT_MISMATCH"]
    assert mismatches[0]["difference"] == "-0.010001"
    assert all(row["difference"] is None for row in outcome[1] if row["category"] in {"AMBIGUOUS", "DUPLICATE", "INVALID"})


def test_decimal_precision_survives_low_ambient_context_and_currency_is_part_of_key():
    left = [("same", DAY, Decimal("999999999999999999.123456"), "USD", "A")]
    right = [("same", DAY, Decimal("999999999999999999.123455"), "USD", "B"),
             ("same", DAY, Decimal("999999999999999999.123456"), "EUR", "B")]
    with localcontext() as context:
        context.prec = 4
        _, rows, counts, _ = match(left, right, business_date=DAY, match_on="record_id", tolerance=Decimal("0.000001"))
    assert counts["WITHIN_TOLERANCE"] == 1 and counts["MISSING_A"] == 1
    assert next(row for row in rows if row["category"] == "WITHIN_TOLERANCE")["difference"] == "0.000001"
