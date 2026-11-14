"""History scheduling; database intents survive lost Redis wakeups."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import redis
from sqlalchemy import Connection

from app.ingest.daily_bars_plan import BEIJING
from app.reports.service import covered


class HistoryWindowDeferredError(RuntimeError):
    """An unsent page reached the protected open-day history window."""


def delayed_until(
    conn: Connection, now: dt.datetime, batch_kind: str, window: int | None
) -> dt.datetime | None:
    if batch_kind != "backfill" and window is None:
        return None
    local = now.astimezone(BEIJING)
    if dt.time(17) <= local.time() < dt.time(17, 45) and covered(conn, local.date()):
        return dt.datetime.combine(local.date(), dt.time(17, 45), BEIJING)
    return None


def delay(client: redis.Redis, args: dict[str, Any], until: dt.datetime) -> None:
    # Stable member: repeated polls or Redis failures never multiply wakeups.
    args = {
        "user_id": None,
        "window_trading_days": None,
        "batch_kind": "daily",
        "batch_seq": 0,
        **args,
    }
    body = {"task": "daily_bars_fetch", "args": args, "enqueued_at": int(until.timestamp())}
    client.zadd("jobs:delayed", {json.dumps(body, sort_keys=True): until.timestamp()})
