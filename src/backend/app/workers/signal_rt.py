"""Owned intraday trigger consumer. No source fetch / production adapter activation."""

from __future__ import annotations

import datetime as dt
import sys

from app.config import Settings
from app.intraday.consumer import Consumer
from app.notify.transport import flush
from app.workers.jobs import _engine, _redis
from app.workers.runner import run

_consumer: Consumer | None = None


def tick(settings: Settings) -> None:
    global _consumer
    if settings.app_env != "test":
        # Paused minute source/ownership deployment is not activated by this patch.
        return
    if _consumer is None:
        _consumer = Consumer(settings, _redis(settings))
    now = dt.datetime.now(dt.UTC)
    _consumer.pump(now)
    flush(_engine(settings), _consumer.client, now)


if __name__ == "__main__":
    try:
        sys.exit(run("signal-rt", tick, interval_s=1))
    finally:
        if _consumer:
            _consumer.close()
            _consumer.client.close()
