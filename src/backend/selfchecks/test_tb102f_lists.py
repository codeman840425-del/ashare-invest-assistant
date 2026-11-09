"""T-B102f real product classification with isolated roles and synthetic oversized responses."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.db.tables.licences import data_licence_events, user_data_licence_status
from app.db.tables.market import master_runs
from app.db.tables.notify import notifications
from app.db.tables.ops import ingest_request_log
from app.db.tables.vendor import master_vendor_batches as batches
from app.ingest import daily_lists, verification
from app.ingest.intents import VerifyIntent
from selfchecks import test_tb102_lists as baseline
from selfchecks.test_tb102_lists import previous

database = baseline.database
env = baseline.env


@pytest.mark.parametrize("kind", ["daily", "verify"])
@pytest.mark.parametrize("code", ["103", "429", None])
def test_tb102f_oversized_limit_classifies_and_notifies_without_network_mislabel(
    env: Any, monkeypatch: Any, kind: str, code: str | None
) -> None:
    e = env
    start = b'{"message":"' + b"x" * 12000 + b'",'
    start += b'"error":{"code":' + str(code).encode() + b',"padding":"' if code else b'"data":"'
    payload = start + b"x" * (16 * 1024 * 1024)
    connected: list[bool] = []
    vid = uuid.uuid4()
    bid = previous.batch(e) if kind == "daily" else None

    class Connection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            connected.append(True)

        def set_debuglevel(self, value: int) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            pass

        def getresponse(self) -> Any:
            return SimpleNamespace(status=200, read=lambda count: payload[:count])

        def close(self) -> None:
            assert (e.root / "STOP").exists() is (code is not None)

    monkeypatch.setattr(daily_lists.http.client, "HTTPSConnection", Connection)
    if kind == "daily":
        assert previous.run(e, bid, upstream=daily_lists.wire) == "failed"
        assert len(json.loads(e.counter.read_text())["records"]) == 1
        with e.owner.connect() as conn:
            batch = conn.execute(select(batches).where(batches.c.id == bid)).one()
            stats = conn.execute(
                select(master_runs.c.stats).where(master_runs.c.id == batch.master_run_id)
            ).scalar_one()
            assert bool(stats.get("upstream_halted")) is (code is not None)
    else:
        assert verification.process(
            e.collector,
            e.settings,
            VerifyIntent(e.lid, vid),
            clock=lambda: e.clock[0],
            upstream=daily_lists.wire,
            egress=lambda: previous.IP,
        ) == ("failed" if code else "failed_no_retry")
        with e.owner.connect() as conn:
            logged = conn.execute(
                select(ingest_request_log).where(ingest_request_log.c.id == vid)
            ).one()
            assert logged.mairui_code == code
            assert logged.status == ("failed" if code else "queued")
    assert connected == [True]
    with e.owner.connect() as conn:
        state = conn.execute(
            select(user_data_licence_status).where(user_data_licence_status.c.id == e.lid)
        ).one()
        assert state.last_error_code == (code or "network")
        events = conn.execute(
            select(data_licence_events).where(data_licence_events.c.licence_id == e.lid)
        ).all()
        if code:
            assert state.status == "ip_limited"
            assert len(events) == 1
            assert events[0].event == "ip_limited"
            assert events[0].upstream_code == code
            notices = (
                conn.execute(
                    select(notifications.c.user_id).where(
                        notifications.c.user_id.in_([e.user, e.admin])
                    )
                )
                .scalars()
                .all()
            )
            assert set(notices) == {e.user, e.admin}
        else:
            assert events == []
    assert e.plaintext not in e.logs.text
