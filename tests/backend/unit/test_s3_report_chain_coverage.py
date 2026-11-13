"""S3-7 retry/beat integration coverage; synthetic queues, no external services."""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from selfchecks.test_s3_report_chain import RedisQueue

from app.workers import jobs


class DueQueue(RedisQueue):
    def zrangebyscore(self, key: str, minimum: float, maximum: float) -> list[bytes]:
        assert key == jobs.DELAYED_KEY
        return [body.encode() for body, due in self.delayed.items() if minimum <= due <= maximum]

    def zrem(self, key: str, raw: bytes) -> int:
        assert key == jobs.DELAYED_KEY
        return int(self.delayed.pop(raw.decode(), None) is not None)


@pytest.fixture(autouse=True)
def isolated_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "_redis", MagicMock(side_effect=AssertionError("unexpected Redis")))
    monkeypatch.setattr(
        jobs, "_engine", MagicMock(side_effect=AssertionError("unexpected database"))
    )
    monkeypatch.setattr(jobs, "MAX_JOBS_PER_TICK", 1)
    monkeypatch.setattr(jobs.time, "time", lambda: 1_000.0)


def test_analyze_retry_is_delayed_before_report_and_preserves_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = DueQueue()
    args = {"trade_date": "2026-11-13", "user_id": "synthetic-owner", "trigger": "synthetic"}
    analyze = MagicMock(side_effect=ValueError("synthetic retry"))
    final = MagicMock()
    monkeypatch.setitem(jobs.TASKS, jobs.ANALYZE, analyze)
    monkeypatch.setitem(jobs.RETRY_TASKS, jobs.ANALYZE, final)
    jobs._push(queue, jobs.ANALYZE, args)

    assert jobs.worker_tick(SimpleNamespace(), queue) == [(jobs.ANALYZE, "failed")]
    final.assert_not_called()
    assert len(queue.delayed) == 1
    raw, due = next(iter(queue.delayed.items()))
    assert json.loads(raw) == {
        "task": jobs.ANALYZE, "args": args, "attempt": 2, "enqueued_at": 1_000,
    }
    assert due == 1_000 + jobs.RETRY_DELAY_S
    queued = [json.loads(body) for body in queue.queue]
    assert [body["task"] for body in queued] == [jobs.REPORT]
    assert queued[0]["args"] == {"trade_date": args["trade_date"], "user_id": args["user_id"]}
    assert f"{jobs.LOCK_PREFIX}{jobs.ANALYZE}" not in queue.keys


def test_due_analyze_retry_promotes_once_then_chains_report_and_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = DueQueue()
    args = {"trade_date": "2026-11-13", "user_id": "synthetic-owner"}
    body = {"task": jobs.ANALYZE, "args": args, "attempt": 2, "enqueued_at": 400}
    raw = json.dumps(body, sort_keys=True)
    queue.delayed[raw] = 1_000
    future = json.dumps({**body, "attempt": 3}, sort_keys=True)
    queue.delayed[future] = 1_001
    intent = MagicMock()
    monkeypatch.setattr(jobs, "slot_jobs", lambda *_: [])
    monkeypatch.setattr(jobs, "record_intent", intent)
    analyze = MagicMock(return_value=1)
    monkeypatch.setitem(jobs.TASKS, jobs.ANALYZE, analyze)
    now = dt.datetime.fromtimestamp(1_000, dt.UTC)

    assert jobs.beat_slots(SimpleNamespace(), queue, now) == [jobs.ANALYZE]
    assert jobs.beat_slots(SimpleNamespace(), queue, now) == []
    intent.assert_not_called()
    assert [json.loads(item) for item in queue.queue] == [body]
    assert queue.delayed == {future: 1_001}
    assert jobs.worker_tick(SimpleNamespace(), queue) == [(jobs.ANALYZE, "ok")]
    analyze.assert_called_once_with(SimpleNamespace(), **args)
    queued = [json.loads(item) for item in reversed(queue.queue)]
    assert [item["task"] for item in queued] == [jobs.REPORT, jobs.TRACKING]
    assert queued[0]["args"] == args
    assert queued[1]["args"] == {"user_id": args["user_id"]}
    assert queue.delayed == {future: 1_001}
