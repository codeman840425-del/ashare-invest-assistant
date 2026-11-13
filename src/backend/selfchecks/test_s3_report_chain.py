# ruff: noqa: PT009  标准库 unittest 自检，可在不含 pytest 的禁网运行镜像执行。
"""S3-7 / daily-bars-source §9.1：全离线调度自检，无数据库或真实 Redis。"""

from __future__ import annotations

import datetime as dt
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.workers import jobs


class RedisQueue:
    def __init__(self) -> None:
        self.queue: list[str] = []
        self.keys: dict[str, bytes] = {}
        self.delayed: dict[str, float] = {}

    def set(self, key: str, value: object, **kwargs: object) -> bool:
        if kwargs.get("nx") and key in self.keys:
            return False
        self.keys[key] = str(value).encode()
        return True

    def get(self, key: str) -> bytes | None:
        return self.keys.get(key)

    def delete(self, key: str) -> None:
        self.keys.pop(key, None)

    def lpush(self, key: str, value: str) -> None:
        self.queue.insert(0, value)

    def rpop(self, key: str) -> str | None:
        return self.queue.pop() if self.queue else None

    def zadd(self, key: str, values: dict[str, float]) -> None:
        self.delayed.update(values)

    def zrangebyscore(self, *args: object) -> list[bytes]:
        return []


class ReportChainCheck(unittest.TestCase):
    def test_report_slot_is_1730_chained_after_analyze(self) -> None:
        day = dt.datetime(2026, 11, 13, tzinfo=ZoneInfo("Asia/Shanghai"))
        settings = SimpleNamespace()
        with (
            patch.object(jobs, "_engine", return_value=MagicMock()),
            patch("app.reports.service.covered", return_value=True),
        ):
            for minute in range(0, 1440, 5):
                with self.subTest(minute=minute):
                    slots = jobs.slot_jobs(settings, day + dt.timedelta(minutes=minute))
                    actual = [
                        (task, slot)
                        for task, slot, _ in slots
                        if task in {jobs.ANALYZE, jobs.REPORT}
                    ]
                    expected = (
                        [(task, "20261113:1730") for task in (jobs.ANALYZE, jobs.REPORT)]
                        if minute in (1050, 1055, 1060)
                        else []
                    )
                    self.assertEqual(actual, expected)
        self.assertEqual(jobs.CODE_MAP_TIME, "18:30")

    def test_beat_pushes_analyze_only_after_both_intents(self) -> None:
        redis = RedisQueue()
        slots = [
            (task, "20261113:1730", {"trade_date": "2026-11-13"})
            for task in (jobs.ANALYZE, jobs.REPORT)
        ]
        recorded: set[str] = set()

        def intent(settings: object, task: str, day: str) -> None:
            self.assertEqual(day, "2026-11-13")
            recorded.add(task)

        push = jobs._push

        def checked_push(*args: object) -> None:
            self.assertEqual(recorded, {jobs.ANALYZE, jobs.REPORT})
            push(*args)

        with (
            patch.object(jobs, "slot_jobs", return_value=slots),
            patch.object(jobs, "record_intent", side_effect=intent),
            patch.object(jobs, "_push", side_effect=checked_push),
        ):
            self.assertEqual(jobs.beat_slots(SimpleNamespace(), redis), [jobs.ANALYZE])
            self.assertEqual(jobs.beat_slots(SimpleNamespace(), redis), [])
        self.assertEqual([json.loads(raw)["task"] for raw in redis.queue], [jobs.ANALYZE])

    def test_report_after_success_retry_and_final_failure(self) -> None:
        for failed, attempt in ((False, 1), (True, 1), (True, 3)):
            with self.subTest(failed=failed, attempt=attempt):
                redis = RedisQueue()
                args = {"trade_date": "2026-11-13", "user_id": "synthetic-owner"}
                jobs._push(redis, jobs.ANALYZE, args, attempt)
                analyze = MagicMock(
                    side_effect=ValueError("synthetic") if failed else None, return_value=1
                )
                final = MagicMock()
                with (
                    patch.object(jobs, "MAX_JOBS_PER_TICK", 1),
                    patch.dict(jobs.TASKS, {jobs.ANALYZE: analyze}),
                    patch.dict(jobs.RETRY_TASKS, {jobs.ANALYZE: final}),
                ):
                    done = jobs.worker_tick(SimpleNamespace(), redis)
                self.assertEqual(done, [(jobs.ANALYZE, "failed" if failed else "ok")])
                queued = [json.loads(raw) for raw in redis.queue]
                report = [body for body in queued if body["task"] == jobs.REPORT]
                self.assertEqual(len(report), 1)
                self.assertEqual(report[0]["args"], args)
                self.assertEqual(any(body["task"] == jobs.TRACKING for body in queued), not failed)
                self.assertEqual(len(redis.delayed), int(failed and attempt == 1))
                if failed and attempt == 3:
                    final.assert_called_once()


if __name__ == "__main__":
    unittest.main()
