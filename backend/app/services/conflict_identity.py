"""Stable identifiers for source delivery ID conflicts."""

import json
import re
from uuid import UUID, uuid5


SOURCE_DELIVERY_CONFLICT_NAMESPACE = UUID("7c4514cc-cc65-4c43-9e25-2c436fa2e101")
SOURCE_DELIVERY_CONFLICT_KEY_VERSION = "v1"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)


def source_delivery_conflict_key(
    delivery_expectation_id: UUID,
    source_delivery_id: str,
    content_hash: str,
) -> UUID:
    """Return a deterministic key for an exact source ID/content conflict."""
    if not source_delivery_id.strip():
        raise ValueError("source_delivery_id must not be empty")
    if len(source_delivery_id) > 255:
        raise ValueError("source_delivery_id must not exceed 255 characters")
    if _SHA256_PATTERN.fullmatch(content_hash) is None:
        raise ValueError("content_hash must be a lowercase SHA-256 hexadecimal digest")

    canonical_identity = json.dumps(
        [
            SOURCE_DELIVERY_CONFLICT_KEY_VERSION,
            str(delivery_expectation_id),
            source_delivery_id,
            content_hash,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return uuid5(SOURCE_DELIVERY_CONFLICT_NAMESPACE, canonical_identity)
