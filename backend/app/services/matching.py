"""Deterministic one-to-one financial matching for finalized CSV snapshots."""

from collections import Counter, defaultdict
from decimal import Decimal, localcontext
import re

AMOUNT_LIMIT = Decimal("1000000000000000000")
MAX_ROWS = 20_000
RESULTS = ("EXACT", "WITHIN_TOLERANCE", "MISSING_A", "MISSING_B", "AMOUNT_MISMATCH",
           "DUPLICATE", "AMBIGUOUS", "INVALID")
MATCHED = frozenset(RESULTS[:2])


def supported_amount(amount):
    return amount.is_finite() and amount.copy_abs() < AMOUNT_LIMIT and amount.as_tuple().exponent >= -6


def normalize(row, business_date, match_on):
    record_id, day, amount, currency, reference = row
    identifier = (record_id if match_on == "record_id" else reference).strip()
    if (day != business_date or not 1 <= len(identifier) <= 128
            or not re.fullmatch("[A-Z]{3}", currency) or not supported_amount(amount)):
        return None
    with localcontext() as context:
        context.prec = 40
        value = amount.quantize(Decimal("0.000001"))
        return (day.isoformat(), identifier, currency, format(value if value else abs(value), "f"))


def match(source_a, source_b, *, business_date, match_on, tolerance, materiality=None):
    """Produce deterministic snapshots, result groups, and exception statistics."""
    groups = defaultdict(lambda: ([], []))
    snapshots = []
    results = []

    def result(category, left, right, *, currency=None, difference=None):
        results.append({"category": category, "source_a": left, "source_b": right,
                        "currency": currency, "difference": format(difference, "f") if difference is not None else None})

    for side, source in enumerate((source_a, source_b)):
        records = sorted((normalize(row, business_date, match_on) for row in source), key=lambda row: (row is None, row))
        snapshots.append(records)
        for position, record in enumerate(records, 1):
            if record is None:
                result("INVALID", [position] if side == 0 else [], [position] if side == 1 else [])
            else:
                groups[record[:3]][side].append((position, record[3]))

    material = False
    with localcontext() as context:
        context.prec = 40
        for key, (left, right) in sorted(groups.items()):
            a, b = ([position for position, _ in values] for values in (left, right))
            difference = None
            if any(len({amount for _, amount in side}) < len(side) for side in (left, right)):
                category = "DUPLICATE"
            elif len(left) > 1 or len(right) > 1:
                category = "AMBIGUOUS"
            else:
                difference = Decimal(left[0][1] if left else "0") - Decimal(right[0][1] if right else "0")
                if not left or not right:
                    category = "MISSING_B" if left else "MISSING_A"
                elif difference == 0:
                    category = "EXACT"
                else:
                    category = "WITHIN_TOLERANCE" if abs(difference) <= tolerance else "AMOUNT_MISMATCH"
                if category not in MATCHED and materiality is not None and abs(difference) >= materiality:
                    material = True
            result(category, a, b, currency=key[2], difference=difference)
    counts = Counter(row["category"] for row in results)
    return snapshots, results, {name: counts[name] for name in RESULTS}, material
