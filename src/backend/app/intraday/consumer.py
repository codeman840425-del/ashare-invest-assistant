"""Redis pubsub trigger + owned DB receipt fallback. No upstream/network producer."""

from __future__ import annotations

import datetime as dt

import redis
from sqlalchemy import select

from app.config import Settings
from app.db.tables.reviews import data_snapshots
from app.intraday.engine import SCHEMA, Updated, task


class Consumer:
    def __init__(self, settings: Settings, client: redis.Redis) -> None:
        self.settings = settings
        self.client = client
        # redis.Redis.pubsub 工厂方法在 redis 类型存根中未标注返回类型（no-untyped-call）。
        self.pubsub = client.pubsub(ignore_subscribe_messages=True)  # type: ignore[no-untyped-call]
        self.pubsub.subscribe("market.updated")
        self.last_fallback: dt.datetime | None = None

    def close(self) -> None:
        self.pubsub.close()

    def pump(self, at: dt.datetime) -> int:
        if self.settings.app_env != "test":
            return 0
        count = 0
        for _ in range(500):
            message = self.pubsub.get_message(timeout=0.01)
            if message is None:
                break
            if message["type"] != "message":
                continue
            try:
                payload = Updated.model_validate_json(message["data"])
            except ValueError:
                continue
            count += task(self.settings, payload.model_dump(mode="json"))
        # Poll only owned, immutable input receipts; never global unlicensed quotes.
        from app.workers.jobs import _engine

        interval = 2 * self.settings.business.realtime.intervals.quote_interval_s
        if self.last_fallback is None or (at - self.last_fallback).total_seconds() >= interval:
            with _engine(self.settings).connect() as conn:
                q = (
                    select(data_snapshots)
                    .where(
                        data_snapshots.c.purpose == "signal",
                        data_snapshots.c.licence_id.is_not(None),
                        data_snapshots.c.user_id.is_not(None),
                        data_snapshots.c.created_at <= at,
                        data_snapshots.c["items"]["schema_version"].astext == SCHEMA,
                    )
                    .order_by(data_snapshots.c.created_at.desc())
                    .limit(500)
                )
                rows = conn.execute(q).all()
            seen = set()
            for row in rows:
                raw = row.items
                scope = (row.licence_id, raw["security_code"])
                if scope in seen:
                    continue
                seen.add(scope)
                fallback_payload = {
                    "v": 1,
                    "licence_id": str(row.licence_id),
                    "tick_id": raw["tick_id"],
                    "dataset": "quotes",
                    "codes": [raw["security_code"]],
                    "quote_ts_max": raw["quote"]["t"],
                    "published_at": at.isoformat(),
                }
                count += task(self.settings, fallback_payload)
            self.last_fallback = at
        return count
