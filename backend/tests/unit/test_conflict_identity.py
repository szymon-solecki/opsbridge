from uuid import UUID

import pytest

from backend.app.services.conflict_identity import source_delivery_conflict_key


EXPECTATION_ID = UUID("1b25d90d-204b-4b74-8d83-42c474e84522")
SOURCE_DELIVERY_ID = "vendor-batch-A9"
CONTENT_HASH = "a" * 64


def test_conflict_key_is_stable_for_identical_identity() -> None:
    assert source_delivery_conflict_key(
        EXPECTATION_ID, SOURCE_DELIVERY_ID, CONTENT_HASH
    ) == source_delivery_conflict_key(EXPECTATION_ID, SOURCE_DELIVERY_ID, CONTENT_HASH)


def test_conflict_key_matches_golden_uuid_v1() -> None:
    assert source_delivery_conflict_key(
        EXPECTATION_ID, SOURCE_DELIVERY_ID, CONTENT_HASH
    ) == UUID("be97f7ef-0563-50eb-89a1-8e6823323f26")


@pytest.mark.parametrize(
    ("expectation_id", "source_delivery_id", "content_hash"),
    [
        (UUID("1b25d90d-204b-4b74-8d83-42c474e84523"), SOURCE_DELIVERY_ID, CONTENT_HASH),
        (EXPECTATION_ID, "vendor-batch-A10", CONTENT_HASH),
        (EXPECTATION_ID, SOURCE_DELIVERY_ID, "b" * 64),
    ],
)
def test_conflict_key_changes_when_any_identity_component_changes(
    expectation_id: UUID,
    source_delivery_id: str,
    content_hash: str,
) -> None:
    assert source_delivery_conflict_key(
        expectation_id, source_delivery_id, content_hash
    ) != source_delivery_conflict_key(EXPECTATION_ID, SOURCE_DELIVERY_ID, CONTENT_HASH)


def test_conflict_key_preserves_source_id_case() -> None:
    assert source_delivery_conflict_key(
        EXPECTATION_ID, "Vendor-Batch-A9", CONTENT_HASH
    ) != source_delivery_conflict_key(EXPECTATION_ID, "vendor-batch-A9", CONTENT_HASH)


@pytest.mark.parametrize("source_delivery_id", ["", " ", "\t"])
def test_conflict_key_rejects_empty_source_id(source_delivery_id: str) -> None:
    with pytest.raises(ValueError, match="source_delivery_id"):
        source_delivery_conflict_key(EXPECTATION_ID, source_delivery_id, CONTENT_HASH)


def test_conflict_key_rejects_non_sha256_digest() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        source_delivery_conflict_key(EXPECTATION_ID, SOURCE_DELIVERY_ID, "A" * 64)
