"""Synthetic ingest intent parsing and licence ownership; no credentials or network."""

from __future__ import annotations

import datetime as dt
import json
import socket
import uuid

import pytest
from app.config_files import IngestDataSharing
from app.ingest.intents import (
    GAP_REASON,
    IntentError,
    UserLicence,
    VendorIntent,
    VerifyIntent,
    parse_intent,
    parse_vendor_intent,
    readable_by,
    source_licence_for,
)
from app.ingest.state import Priority
from app.schemas.enums import DataLicenceStatus

USER_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
LICENCE_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
OTHER_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-ccccccccccc1")
BATCH_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-ddddddddddd1")
VERIFICATION_ID = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee1")
DEADLINE = dt.datetime(2026, 11, 14, 10, tzinfo=dt.UTC)
DATASETS = ["hslt_list", "bj_list", "kc_list", "hsrl_real"]
SHARING = IngestDataSharing(mode="per_licence", allow_cross_licence_fallback=False)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        pytest.fail("ingest intent parsing attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def vendor_fields(**changes: object) -> dict[bytes, bytes]:
    fields = {
        b"kind": b"vendor_lists",
        b"batch_id": str(BATCH_ID).encode(),
        b"licence_id": str(LICENCE_ID).encode(),
        b"datasets": json.dumps(DATASETS).encode(),
        b"priority": b"p1_daily",
        b"deadline_at": DEADLINE.isoformat().encode(),
    }
    for key, value in changes.items():
        encoded = key.encode()
        if value is None:
            fields.pop(encoded)
        else:
            fields[encoded] = str(value).encode()
    return fields


def test_parse_vendor_intent_bytes_and_dataset_order() -> None:
    shuffled = list(reversed(DATASETS))
    result = parse_intent(vendor_fields(datasets=json.dumps(shuffled)))
    assert result == VendorIntent(BATCH_ID, LICENCE_ID, tuple(shuffled), DEADLINE)
    assert result.priority is Priority.P1


def test_parse_vendor_intent_accepts_string_keys_and_values() -> None:
    fields = {key.decode(): value.decode() for key, value in vendor_fields().items()}
    assert parse_vendor_intent(fields) == VendorIntent(
        BATCH_ID, LICENCE_ID, tuple(DATASETS), DEADLINE
    )


@pytest.mark.parametrize(
    "key", ["kind", "batch_id", "licence_id", "datasets", "priority", "deadline_at"]
)
def test_vendor_intent_requires_exact_field_set(key: str) -> None:
    with pytest.raises(IntentError, match="invalid fields"):
        parse_vendor_intent(vendor_fields(**{key: None}))


def test_vendor_intent_rejects_additional_or_plaintext_fields_without_echo() -> None:
    plaintext = "synthetic-not-a-secret"
    with pytest.raises(IntentError, match="invalid fields") as error:
        parse_vendor_intent(vendor_fields(licence=plaintext))
    assert plaintext not in str(error.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"licence_id": "bad"},
        {"batch_id": "bad"},
        {"datasets": "not-json"},
        {"datasets": "{}"},
        {"datasets": json.dumps(DATASETS[:3])},
        {"datasets": json.dumps([DATASETS[0]] * 4)},
        {"deadline_at": "bad"},
        {"deadline_at": "2026-11-14T10:00:00"},
        {"priority": "P0"},
    ],
)
def test_vendor_intent_rejects_invalid_metadata(changes: dict[str, str]) -> None:
    with pytest.raises(IntentError, match="invalid metadata"):
        parse_vendor_intent(vendor_fields(**changes))


def test_unrelated_intent_is_left_for_other_consumers() -> None:
    assert parse_intent({"kind": "daily_lists"}) is None
    assert parse_intent({}) is None


def test_verify_intent_defaults_to_p0() -> None:
    result = parse_intent(
        {
            "kind": "verify_licence",
            "licence_id": str(LICENCE_ID),
            "verification_id": str(VERIFICATION_ID),
        }
    )
    assert result == VerifyIntent(LICENCE_ID, VERIFICATION_ID, Priority.P0)


@pytest.mark.parametrize("priority", ["P0", "p1", "P2"])
def test_verify_intent_priority_is_normalized(priority: str) -> None:
    result = parse_intent(
        {
            "kind": "verify_licence",
            "licence_id": str(LICENCE_ID),
            "verification_id": str(VERIFICATION_ID),
            "priority": priority,
        }
    )
    assert isinstance(result, VerifyIntent)
    assert result.priority is Priority[priority.upper()]


def test_verify_intent_rejects_plaintext_licence_without_echo() -> None:
    with pytest.raises(IntentError, match="must not carry") as error:
        parse_intent(
            {
                "kind": "verify_licence",
                "licence_id": str(LICENCE_ID),
                "verification_id": str(VERIFICATION_ID),
                "licence": "synthetic-not-a-secret",
            }
        )
    assert "synthetic-not-a-secret" not in str(error.value)


@pytest.mark.parametrize("field", ["licence_id", "verification_id"])
def test_verify_intent_rejects_bad_uuid(field: str) -> None:
    fields = {
        "kind": "verify_licence",
        "licence_id": str(LICENCE_ID),
        "verification_id": str(VERIFICATION_ID),
        field: "bad",
    }
    with pytest.raises(IntentError, match="bad licence_id/verification_id"):
        parse_intent(fields)


def test_verify_intent_rejects_unknown_priority() -> None:
    with pytest.raises(IntentError, match="bad priority"):
        parse_intent(
            {
                "kind": "verify_licence",
                "licence_id": str(LICENCE_ID),
                "verification_id": str(VERIFICATION_ID),
                "priority": "P3",
            }
        )


def test_active_licence_is_used_for_every_priority_without_cross_user_fallback() -> (
    None
):
    user = UserLicence(USER_ID, LICENCE_ID, DataLicenceStatus.ACTIVE)
    for priority in Priority:
        assert source_licence_for(SHARING, user, priority) == LICENCE_ID
    assert GAP_REASON == "data_licence_unavailable"


def test_expired_licence_is_p0_only() -> None:
    user = UserLicence(USER_ID, LICENCE_ID, DataLicenceStatus.EXPIRED)
    assert source_licence_for(SHARING, user, Priority.P0) == LICENCE_ID
    assert source_licence_for(SHARING, user, Priority.P1) is None
    assert source_licence_for(SHARING, user, Priority.P2) is None


@pytest.mark.parametrize(
    "status",
    [
        DataLicenceStatus.NOT_SET,
        DataLicenceStatus.PENDING_VERIFICATION,
        DataLicenceStatus.INVALID,
        DataLicenceStatus.QUOTA_EXCEEDED,
        DataLicenceStatus.IP_LIMITED,
        DataLicenceStatus.PAUSED_BY_ADMIN,
    ],
)
def test_unusable_status_never_falls_back_to_another_licence(
    status: DataLicenceStatus,
) -> None:
    assert source_licence_for(SHARING, UserLicence(USER_ID, LICENCE_ID, status)) is None


def test_missing_licence_is_unavailable() -> None:
    user = UserLicence(USER_ID, None, DataLicenceStatus.ACTIVE)
    assert source_licence_for(SHARING, user) is None
    assert not readable_by(SHARING, user, LICENCE_ID)


def test_readable_only_by_owner_of_row_source() -> None:
    user = UserLicence(USER_ID, LICENCE_ID, DataLicenceStatus.ACTIVE)
    assert readable_by(SHARING, user, LICENCE_ID)
    assert not readable_by(SHARING, user, OTHER_ID)
