"""Synthetic vendor-list normalization and handoff; no real database or network."""

from __future__ import annotations

import datetime as dt
import json
import socket
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from app.db.tables.vendor import DATASETS
from app.ingest.vendor_lists import (
    DatasetResult,
    VendorRow,
    _normalize,
    process_vendor_intent,
)
from app.master.vendor import APPLY_TASK

BATCH_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
LICENCE_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
PAYLOAD_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-ccccccccccc1")
DEADLINE = dt.datetime(2026, 11, 14, 10, tzinfo=dt.UTC)
NOW = DEADLINE - dt.timedelta(minutes=1)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        pytest.fail("vendor list processing attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def fields() -> dict[str, str]:
    return {
        "kind": "vendor_lists",
        "batch_id": str(BATCH_ID),
        "licence_id": str(LICENCE_ID),
        "datasets": json.dumps(DATASETS),
        "priority": "p1_daily",
        "deadline_at": DEADLINE.isoformat(),
    }


def batch(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "source_licence_id": LICENCE_ID,
        "deadline_at": DEADLINE,
        "status": "requested",
    }
    value.update(changes)
    return value


def empty_results() -> list[DatasetResult]:
    return [DatasetResult(dataset) for dataset in DATASETS]


class StubResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def mappings(self) -> StubResult:
        return self

    def one_or_none(self) -> object:
        return self.value


class ScriptedConnection:
    def __init__(self, events: list[tuple[str, Any]], *results: StubResult) -> None:
        self.events = events
        self.results = iter(results)
        self.calls: list[tuple[Any, Any]] = []

    def execute(self, statement: Any, parameters: Any = None) -> StubResult | None:
        self.calls.append((statement, parameters))
        self.events.append(("execute", parameters))
        try:
            return next(self.results)
        except StopIteration:
            return None

    def assert_done(self) -> None:
        assert list(self.results) == []


class Transaction:
    def __init__(self, conn: ScriptedConnection, events: list[tuple[str, Any]]) -> None:
        self.conn = conn
        self.events = events

    def __enter__(self) -> ScriptedConnection:
        self.events.append(("begin", None))
        return self.conn

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.events.append(("rollback" if exc_type else "commit", None))
        return False


class ScriptedEngine:
    def __init__(self, conn: ScriptedConnection, events: list[tuple[str, Any]]) -> None:
        self.conn = conn
        self.events = events

    def begin(self) -> Transaction:
        return Transaction(self.conn, self.events)


class ScriptedRedis:
    def __init__(self, events: list[tuple[str, Any]]) -> None:
        self.events = events
        self.calls: list[tuple[str, str]] = []

    def lpush(self, key: str, value: str) -> None:
        self.calls.append((key, value))
        self.events.append(("lpush", value))


def process(
    conn: ScriptedConnection,
    rds: ScriptedRedis,
    events: list[tuple[str, Any]],
    fetch_results: Callable[[Any], list[DatasetResult]],
    clock: Callable[[], dt.datetime] = lambda: NOW,
) -> str:
    return process_vendor_intent(  # type: ignore[arg-type]
        ScriptedEngine(conn, events),
        rds,
        fields(),
        fetch_results=fetch_results,
        clock=clock,
    )


def update_params(conn: ScriptedConnection) -> dict[str, Any]:
    """Read SQLAlchemy inline values; no SQL is sent to a real database."""
    return dict(conn.calls[-1][0].compile().params)


def test_normalize_preserves_dataset_order_rows_and_payload_ids() -> None:
    results = empty_results()
    results[0] = DatasetResult(
        DATASETS[0],
        (VendorRow("600000.SH", "合成甲"),),
        raw_payload_id=PAYLOAD_ID,
    )
    results[-1] = DatasetResult(
        DATASETS[-1], (VendorRow("830001.BJ", None, dup_conflict=True),)
    )

    summaries, rows, failed = _normalize(results)

    assert failed is False
    assert [item["dataset"] for item in summaries] == list(DATASETS)
    assert summaries[0]["raw_payload_id"] == str(PAYLOAD_ID)
    assert summaries[0]["row_count"] == 1
    assert rows == [
        {
            "dataset": DATASETS[0],
            "security_code": "600000.SH",
            "vendor_name": "合成甲",
            "dup_conflict": False,
        },
        {
            "dataset": DATASETS[-1],
            "security_code": "830001.BJ",
            "vendor_name": None,
            "dup_conflict": True,
        },
    ]


@pytest.mark.parametrize(
    "results",
    [
        [DatasetResult("unknown")],
        [DatasetResult(DATASETS[0]), DatasetResult(DATASETS[0])],
    ],
)
def test_normalize_rejects_unknown_or_duplicate_datasets(
    results: list[DatasetResult],
) -> None:
    with pytest.raises(ValueError, match="invalid dataset results"):
        _normalize(results)


def test_normalize_mandatory_failure_is_failed_but_margin_failure_is_optional() -> None:
    summaries, rows, failed = _normalize([])
    assert failed is True
    assert rows == []
    assert all(item["status"] == "failed" for item in summaries)
    assert all(item["error_code"] == "fetch_failed" for item in summaries)

    results = empty_results()[:3] + [DatasetResult(DATASETS[-1], error_code="upstream")]
    summaries, _, failed = _normalize(results)
    assert failed is False
    assert summaries[-1]["status"] == "failed"


@pytest.mark.parametrize(
    "row",
    [
        VendorRow("bad", None),
        VendorRow("600000.SH", "x" * 129),
        VendorRow("600000.SH", None, dup_conflict=1),  # type: ignore[arg-type]
        VendorRow("600000.SH", None, dup_conflict=True),
    ],
)
def test_normalize_rejects_invalid_public_rows(row: VendorRow) -> None:
    with pytest.raises(ValueError, match="invalid normalized public rows"):
        _normalize([DatasetResult(DATASETS[0], (row,))])


def test_normalize_rejects_duplicate_codes_within_a_dataset() -> None:
    rows = (VendorRow("600000.SH", None), VendorRow("600000.SH", "合成乙"))
    with pytest.raises(ValueError, match="invalid normalized public rows"):
        _normalize([DatasetResult(DATASETS[0], rows)])


def test_process_rejects_an_unrelated_intent_before_transaction() -> None:
    events: list[tuple[str, Any]] = []
    conn = ScriptedConnection(events)
    with pytest.raises(ValueError, match="not a vendor_lists intent"):
        process_vendor_intent(  # type: ignore[arg-type]
            ScriptedEngine(conn, events),
            ScriptedRedis(events),
            {},
            fetch_results=lambda _: [],
        )
    assert events == []


@pytest.mark.parametrize(
    "selected_batch",
    [None, batch(source_licence_id=PAYLOAD_ID), batch(deadline_at=NOW)],
)
def test_process_rolls_back_metadata_mismatch_without_fetch_or_notification(
    selected_batch: dict[str, object] | None,
) -> None:
    events: list[tuple[str, Any]] = []
    conn = ScriptedConnection(events, StubResult(selected_batch))
    rds = ScriptedRedis(events)
    with pytest.raises(ValueError, match="metadata mismatch"):
        process(conn, rds, events, lambda _: pytest.fail("fetch must not run"))
    assert events[-1][0] == "rollback"
    assert rds.calls == []


def test_process_noop_does_not_fetch_or_notify() -> None:
    events: list[tuple[str, Any]] = []
    conn = ScriptedConnection(events, StubResult(batch(status="fetched")))
    rds = ScriptedRedis(events)
    assert (
        process(conn, rds, events, lambda _: pytest.fail("fetch must not run"))
        == "noop"
    )
    assert events == [("begin", None), ("execute", None), ("commit", None)]
    assert rds.calls == []


def test_process_expires_at_deadline_without_fetch_or_notification() -> None:
    events: list[tuple[str, Any]] = []
    conn = ScriptedConnection(events, StubResult(batch()))
    rds = ScriptedRedis(events)
    assert (
        process(
            conn,
            rds,
            events,
            lambda _: pytest.fail("fetch must not run"),
            lambda: DEADLINE,
        )
        == "expired"
    )
    assert len(conn.calls) == 2
    assert update_params(conn)["status"] == "expired"
    assert update_params(conn)["error_code"] == "deadline_exceeded"
    assert events[-1][0] == "commit"
    assert rds.calls == []


def test_process_fetches_persists_then_notifies_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, Any]] = []
    conn = ScriptedConnection(events, StubResult(batch()))
    rds = ScriptedRedis(events)
    results = empty_results()
    results[0] = DatasetResult(DATASETS[0], (VendorRow("600000.SH", "合成甲"),))

    def available(received_conn: object, licence_id: object, now: object) -> bool:
        events.append(("licence", (received_conn, licence_id, now)))
        return True

    def fetch(intent: Any) -> list[DatasetResult]:
        events.append(("fetch", intent))
        return results

    monkeypatch.setattr("app.ingest.vendor_lists.licence_available", available)
    assert process(conn, rds, events, fetch) == "fetched"
    assert len(conn.calls) == 3
    assert conn.calls[-2][1] == [
        {
            "batch_id": BATCH_ID,
            "dataset": DATASETS[0],
            "security_code": "600000.SH",
            "vendor_name": "合成甲",
            "dup_conflict": False,
        }
    ]
    assert update_params(conn)["status"] == "fetched"
    assert update_params(conn)["error_code"] is None
    assert events[-2][0] == "commit"
    assert events[-1][0] == "lpush"
    assert json.loads(rds.calls[0][1]) == {
        "task": APPLY_TASK,
        "args": {"batch_id": str(BATCH_ID)},
    }


def test_process_unavailable_licence_skips_fetch_and_marks_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, Any]] = []
    conn = ScriptedConnection(events, StubResult(batch()))
    rds = ScriptedRedis(events)
    monkeypatch.setattr(
        "app.ingest.vendor_lists.licence_available", lambda *args: False
    )
    assert (
        process(conn, rds, events, lambda _: pytest.fail("fetch must not run"))
        == "failed"
    )
    assert len(conn.calls) == 2
    assert update_params(conn)["error_code"] == "licence_unavailable"
    assert all(item["status"] == "failed" for item in update_params(conn)["datasets"])
    assert events[-2][0] == "commit" and events[-1][0] == "lpush"


def test_process_fetch_exception_is_sanitized_and_still_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, Any]] = []
    conn = ScriptedConnection(events, StubResult(batch()))
    rds = ScriptedRedis(events)
    monkeypatch.setattr("app.ingest.vendor_lists.licence_available", lambda *args: True)

    def fetch(_: Any) -> list[DatasetResult]:
        raise RuntimeError("synthetic upstream detail must not escape")

    assert process(conn, rds, events, fetch) == "failed"
    update = update_params(conn)
    assert update["status"] == "failed" and update["error_code"] == "list_failed"
    assert "synthetic upstream detail" not in str(update)
    assert "synthetic upstream detail" not in rds.calls[0][1]


def test_process_successful_empty_results_update_without_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, Any]] = []
    conn = ScriptedConnection(events, StubResult(batch()))
    rds = ScriptedRedis(events)
    monkeypatch.setattr("app.ingest.vendor_lists.licence_available", lambda *args: True)
    assert process(conn, rds, events, lambda _: empty_results()) == "fetched"
    assert len(conn.calls) == 2
    assert update_params(conn)["fetched_at"] == NOW
    assert all(item["row_count"] == 0 for item in update_params(conn)["datasets"])
