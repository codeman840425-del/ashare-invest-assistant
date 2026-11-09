"""T-B102 actual product list process, isolated PG/roles/HPKE, synthetic transport.

Only explicit disposable DSN+cluster are allowed. No deployment/real credential
or external network. The daily dispatch is real, including inode accounting.
"""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select, text, update

from app.api.v1 import admin as admin_routes
from app.api.v1 import data_licence as licence_routes
from app.auth import deps
from app.common.errors import install_exception_handlers
from app.config import get_settings
from app.db.tables.licences import user_data_licences
from app.db.tables.market import master_runs
from app.db.tables.vendor import master_vendor_batches as batches
from app.db.tables.vendor import master_vendor_list_rows as rows
from app.ingest import daily_lists, send_control
from app.ingest.shared_gate import write_stop
from selfchecks import test_tb99_daily as previous


@pytest.fixture(scope="module")
def database() -> Any:
    if os.environ.get("TB99_ISOLATED_DATABASE_URL") != previous.DSN or previous.PORT != 5432:
        pytest.skip("explicit isolated tb99_test DSN required")
    engine = create_engine(previous.DSN, hide_parameters=True)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SHOW cluster_name")).scalar_one() == "tb102-isolated"
    finally:
        engine.dispose()
    yield from previous.database.__wrapped__()


@pytest.fixture
def env(database: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: Any) -> Any:
    source = previous.env.__wrapped__(database, tmp_path, monkeypatch)
    e = next(source)
    e.counter = e.root / "daily_lists.count"
    e.counter.write_text(json.dumps({"schema": "mairui-daily/v1", "records": []}), encoding="utf-8")
    os.chmod(e.counter, 0o600)
    caplog.set_level("INFO", logger="app.ingest.send_governance")
    e.logs = caplog
    e.settings = mode(e.settings, True)

    def wire(path: str, secret: str) -> Any:
        assert secret == e.plaintext
        assert send_control.owned(e.root)
        ledger = json.loads(e.counter.read_text(encoding="utf-8"))
        assert len(ledger["records"]) == len(e.calls) + 1
        e.calls.append((path, e.clock[0]))
        return 200, [{"dm": code[:6], "mc": name} for code, name in previous.NAMES.items()]

    e.wire = wire
    yield e
    with contextlib.suppress(StopIteration):
        next(source)


def mode(settings: Any, enforce: bool) -> Any:
    ingest = settings.business.ingest
    return settings.model_copy(
        update={
            "business": settings.business.model_copy(
                update={
                    "ingest": ingest.model_copy(
                        update={
                            "send_governance": ingest.send_governance.model_copy(
                                update={"enforce": enforce}
                            )
                        }
                    )
                }
            )
        }
    )


def logged(e: Any) -> list[Any]:
    return [
        json.loads(record.getMessage().split("send_governance ", 1)[1])
        for record in e.logs.records
        if record.name == "app.ingest.send_governance"
    ]


def test_tb102_product_three_order_intervals_receipt_and_no_replay(env: Any) -> None:
    e = env
    bid = previous.batch(e)
    assert previous.run(e, bid) == "fetched"
    assert [path for path, at in e.calls] == list(daily_lists.PATHS.values())
    assert len(json.loads(e.counter.read_text())["records"]) == 3
    assert all(
        (right[1] - left[1]).total_seconds() >= 60
        for left, right in zip(e.calls, e.calls[1:], strict=False)
    )
    assert previous.run(e, bid) == "noop"
    assert len(e.calls) == 3
    assert not e.temp.exists()


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_product_common_stop_strong_zero_http_or_bypass_three(
    env: Any, enforce: bool
) -> None:
    e = env
    e.settings = mode(e.settings, enforce)
    bid = previous.batch(e)
    write_stop(e.root / "STOP")
    if enforce:
        assert previous.run(e, bid) == "failed"
        assert e.calls == []
        assert len(json.loads(e.counter.read_text())["records"]) == 1
    else:

        def observing(path: str, secret: str) -> Any:
            e.calls.append(path)
            return 200, [{"dm": "600519", "mc": "synthetic"}]

        assert previous.run(e, bid, upstream=observing) == "fetched"
        assert len(e.calls) == len(json.loads(e.counter.read_text())["records"]) == 3
        assert [row["code"] for row in logged(e)] == ["bypass_stop_would_block"] * 3
    assert not e.temp.exists()
    assert e.plaintext not in e.logs.text


def test_tb102_product_daily_limit_global_across_batches(env: Any) -> None:
    e = env
    bid = previous.batch(e)
    assert previous.run(e, bid) == "fetched"
    # Another authorized logical batch cannot turn a DB row's fresh [] into a fresh day budget.
    other = uuid.uuid4()
    with e.owner.begin() as conn:
        original = conn.execute(select(batches).where(batches.c.id == bid)).one()
        p = conn.execute(
            select(master_runs).where(master_runs.c.id == original.master_run_id)
        ).one()
        new_parent = conn.execute(
            master_runs.insert()
            .values(
                trigger="beat_1800",
                started_at=e.clock[0],
                status=None,
                stats={**p.stats, "batch_id": str(other), "attempted": []},
            )
            .returning(master_runs.c.id)
        ).scalar_one()
        conn.execute(
            batches.insert().values(
                id=other,
                master_run_id=new_parent,
                source_licence_id=e.lid,
                status="requested",
                attempt=1,
                requested_at=e.clock[0],
                deadline_at=original.deadline_at,
                datasets=[],
            )
        )
    assert previous.run(e, other) == "failed"
    assert len(e.calls) == len(json.loads(e.counter.read_text())["records"]) == 3
    assert logged(e)[-1]["snapshot"]["daily_count"] == 3


@pytest.mark.parametrize("response", ["exception", "credential_echo", "limit"])
def test_tb102_product_errors_count_stop_and_preserve_redaction(env: Any, response: str) -> None:
    e = env
    bid = previous.batch(e)

    def wire(path: str, secret: str) -> Any:
        e.calls.append(path)
        if response == "exception":
            raise RuntimeError("synthetic URL/" + secret)
        if response == "credential_echo":
            return 200, [{"dm": "600519", "mc": quote(secret, safe="")}]
        return 429, None

    assert previous.run(e, bid, upstream=wire) == "failed"
    assert len(e.calls) == len(json.loads(e.counter.read_text())["records"]) == 1
    assert not e.temp.exists()
    assert e.plaintext not in e.logs.text
    assert (e.root / "STOP").exists() is (response == "limit")
    with e.owner.connect() as conn:
        assert conn.execute(select(rows).where(rows.c.batch_id == bid)).all() == []


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_product_corrupt_accounting_never_bypassed(env: Any, enforce: bool) -> None:
    e = env
    bid = previous.batch(e)
    e.counter.write_text("{truncated", encoding="utf-8")
    e.settings = mode(e.settings, enforce)
    assert previous.run(e, bid) == "failed"
    assert e.calls == []
    assert e.counter.read_text() == "{truncated"
    assert not e.temp.exists()


@pytest.mark.parametrize(
    "case", ["missing_receipt", "replay", "no_certificate", "wrong_licence", "egress"]
)
def test_tb102_product_authorization_egress_not_bypassed(
    env: Any, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    e = env
    bid = previous.batch(e)
    e.settings = mode(e.settings, False)
    if case == "missing_receipt":
        monkeypatch.setattr(daily_lists, "read_grant", lambda: None)
    elif case == "replay":
        monkeypatch.setenv("MAIRUI_MODE", "replay")
    elif case in {"no_certificate", "wrong_licence"}:
        with e.owner.begin() as conn:
            conn.execute(
                update(user_data_licences)
                .where(user_data_licences.c.id == e.lid)
                .values(
                    deleted_at=e.clock[0],
                    ciphertext=None,
                    licence_hmac=None,
                )
            )
    if case == "egress":
        result = daily_lists.process(
            e.collector,
            bid,
            e.grant,
            clock=lambda: e.clock[0],
            settings=e.settings,
            upstream=e.wire,
            temp=e.temp,
            stop=e.stop,
            halt=e.halt,
            egress=lambda: "192.0.2.11",
            secret_loader=lambda *args: pytest.fail("egress failure must precede credential load"),
        )
    else:
        result = previous.run(
            e, bid, secret_loader=lambda *args: pytest.fail("authorization failure")
        )
    assert result in {"failed", "authorization_unavailable", "live_transport_closed"}
    assert e.calls == []
    assert json.loads(e.counter.read_text())["records"] == []


def test_tb102_http_missing_session_and_nonadmin_shape_remain_404(env: Any) -> None:
    e = env
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(admin_routes.router, prefix="/admin")
    app.include_router(licence_routes.router)
    app.dependency_overrides[deps.get_engine] = lambda: e.worker
    app.dependency_overrides[deps.get_redis] = lambda: None
    app.dependency_overrides[get_settings] = lambda: e.settings
    store = type("Store", (), {"get": lambda self, token: None})()
    app.dependency_overrides[deps.get_session_store] = lambda: store

    async def request(path: str) -> int:
        statuses = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                statuses.append(message["status"])

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("127.0.0.1", 80),
            },
            receive,
            send,
        )
        return int(statuses[0])

    assert asyncio.run(request("/admin/ingest/status")) == 404
    store.get = lambda token: type("Session", (), {"user_id": str(e.user)})()
    assert asyncio.run(request("/admin/ingest/status")) == 404


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_product_window_decision_uses_governance_in_both_modes(
    env: Any, enforce: bool
) -> None:
    e = env
    bid = previous.batch(e)
    e.clock[0] -= dt.timedelta(seconds=1)
    e.settings = mode(e.settings, enforce)
    if enforce:
        assert previous.run(e, bid) == "failed"
        assert e.calls == []
        assert json.loads(e.counter.read_text())["records"] == []
    else:
        assert previous.run(e, bid) == "fetched"
        assert len(e.calls) == len(json.loads(e.counter.read_text())["records"]) == 3
    assert logged(e)[0]["code"] == ("blocked_daily" if enforce else "bypass_daily_would_block")
