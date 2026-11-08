"""RV-05 repair negatives. Disposable PG/Redis, synthetic credentials and zero vendor I/O."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select, update

from app.db.tables.licences import data_licence_events, user_data_licence_holds, user_data_licences
from app.db.tables.market import trading_calendar
from app.db.tables.notify import notifications
from app.db.tables.ops import ingest_request_log
from app.ingest import daily_lists, live, shared_gate, verification, verification_grants
from app.ingest.intents import VerifyIntent
from app.ingest.shared_gate import GateClosedError, SharedGate
from app.licences import service
from selfchecks import test_tb99_daily as base
from selfchecks import test_tb99_gate as gate_base

# Register the same deliberately isolated fixtures without substituting their database services.
database, env, redis_sink = base.database, base.env, base.redis_sink
gate_env = gate_base.gate_env
IP, batch, run, attempted = base.IP, base.batch, base.run, base.attempted
test_compat_daily_three = base.test_daily_three_order_interval_and_no_fourth_request
test_compat_verify_consumer = base.test_verification_real_redis_consumer_and_fallback_are_once_only


def verify(e: Any, **kwargs: Any) -> str:
    def upstream(path: str, secret: str) -> Any:
        assert secret == e.plaintext
        e.calls.append(path)
        return 200, [{"date": str(e.day)}]

    return verification.process(
        e.collector,
        e.settings,
        kwargs.pop("intent", VerifyIntent(e.lid, uuid.uuid4())),
        clock=lambda: e.clock[0],
        upstream=kwargs.pop("upstream", upstream),
        egress=kwargs.pop("egress", lambda: IP),
        **kwargs,
    )


def test_historical_tb05_stop_maps_before_missing_credential_exit(
    gate_env: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probes import run_all

    root, lid, _ = gate_env
    legacy = tmp_path / "historical-STOP"
    legacy.write_text("synthetic-private-stop-content", encoding="utf-8")
    monkeypatch.setattr(run_all.c, "STOP_FILE", legacy)
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    assert run_all.real_run(SimpleNamespace()) == 2
    assert (root / "STOP").is_file()
    assert "synthetic-private-stop-content" not in (root / "STOP").read_text()
    with pytest.raises(GateClosedError, match="STOP"):
        SharedGate(root, lid, "product_daily").acquire()


@pytest.mark.skipif(os.name == "nt", reason="TB86 POSIX-only runner")
def test_historical_tb86_stop_maps_before_notice_or_credential_access(
    gate_env: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probes import tb86_history

    root, lid, _ = gate_env
    legacy = tmp_path / "historical-STOP"
    legacy.touch()
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    result = tb86_history.execute(
        counter=tmp_path / "never-open-counter",
        stop=legacy,
        secret_path=tmp_path / "never-create-secret",
        root=tmp_path / "never-create-run",
    )
    assert result["outcome"] == "STOP_present"
    assert result["new_reserved_calls"] == 0
    assert (root / "STOP").is_file()
    assert not (tmp_path / "never-create-secret").exists()
    with pytest.raises(GateClosedError, match="STOP"):
        SharedGate(root, lid, "product_daily").acquire()


def test_public_stop_flushes_and_fsyncs_without_copying_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    real = shared_gate.os.fsync

    def fsync(fd: int) -> None:
        calls.append(fd)
        real(fd)

    monkeypatch.setattr(shared_gate.os, "fsync", fsync)
    path = tmp_path / "STOP"
    shared_gate.write_stop(path)
    assert calls
    assert path.read_text() == "operator_review_required\n"
    before = path.read_bytes()
    shared_gate.write_stop(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("code", ["103", "429"])
def test_same_certificate_new_uuid_inherits_halt(gate_env: Any, code: str) -> None:
    root, old, new = gate_env
    with SharedGate(root, old, "probe_tb05") as first:
        first.bind_certificate("synthetic-shared-certificate")
        first.trip(code)
    with SharedGate(root, new, "product_verify") as second:
        with pytest.raises(GateClosedError, match="halted"):
            second.bind_certificate("synthetic-shared-certificate")
        assert second.halt_path == first.halt_path
    with pytest.raises(GateClosedError, match="halted"):
        SharedGate(root, new, "probe_tb86").acquire()


def test_same_certificate_new_uuid_inherits_minute_budget(gate_env: Any) -> None:
    root, old, new = gate_env
    with SharedGate(root, old, "probe_tb05") as first:
        first.bind_certificate("synthetic-shared-certificate")
        first.confirm_egress(IP)
        first.reserve(now=1000)
        first.complete(now=1000)
    with SharedGate(root, new, "probe_tb86") as second:
        second.bind_certificate("synthetic-shared-certificate")
        second.confirm_egress(IP)
        assert first.state_path == second.state_path
        second.reserve(now=1001)
        second.complete(now=1001)
        with pytest.raises(GateClosedError, match="budget"):
            second.reserve(now=1002)
        with pytest.raises(GateClosedError, match="clock_reversed"):
            second.product_delay(999)


@pytest.mark.parametrize(
    "invalid", ["none", "expired", "future", "other_user", "other_licence", "budget"]
)
def test_verification_requires_current_owned_one_request_grant(
    env: Any,
    invalid: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    e = env
    replacements = {
        "expired": {"end": e.clock[0]},
        "future": {"start": e.clock[0] + dt.timedelta(seconds=1)},
        "other_user": {"user_id": uuid.uuid4()},
        "other_licence": {"licence_id": uuid.uuid4()},
        "budget": {"max_http_requests": 0},
    }
    grant = (
        None
        if invalid == "none"
        else dataclasses.replace(e.verification_grant, **replacements[invalid])
    )
    monkeypatch.setattr(verification, "read_grant", lambda: grant)

    def forbidden(*args: Any) -> Any:
        pytest.fail("unauthorized verification reached a secret/HTTP boundary")

    assert verify(e, secret_loader=forbidden, upstream=forbidden, egress=forbidden) in {
        "authorization_unavailable",
        "unavailable",
    }
    assert e.calls == []
    with e.owner.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(ingest_request_log)
                .where(
                    ingest_request_log.c.licence_id == e.lid,
                )
            ).scalar_one()
            == 0
        )


def test_daily_three_only_authorization_does_not_consume_queue_or_pending_verification(
    env: Any,
    redis_sink: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    e, rds = env, redis_sink
    monkeypatch.setattr(verification, "read_grant", lambda: None)
    service.enqueue_verify(rds, licence_id=e.lid, verification_id=uuid.uuid4())
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert run(e, batch(e)) == "fetched"
    assert len(e.calls) == 3
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(status="pending_verification")
        )
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert len(e.calls) == 3


def test_verification_grant_allows_one_call_even_with_multiple_intents(env: Any) -> None:
    e = env
    assert verify(e) == "verified"
    e.clock[0] += dt.timedelta(seconds=61)
    assert verify(e) == "already_attempted"
    assert len(e.calls) == 1


@pytest.mark.parametrize("pause", ["certificate", "hold", "deleted", "global"])
def test_pause_during_credential_load_blocks_actual_verification_send(
    env: Any,
    redis_sink: Any,
    pause: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    e, rds = env, redis_sink
    e.settings = e.settings.model_copy(update={"redis_url": "redis://127.0.0.1:6380/15"})
    rds.delete(e.settings.ingest_paused_key)
    monkeypatch.setattr(verification, "send_paused", live.send_paused)
    loader = daily_lists.credential

    def raced(engine: Any, lid: uuid.UUID) -> str:
        secret = loader(engine, lid)
        if pause == "global":
            rds.set(e.settings.ingest_paused_key, "1")
        else:
            with e.owner.begin() as conn:
                if pause == "hold":
                    conn.execute(user_data_licence_holds.insert().values(user_id=e.user))
                else:
                    values = (
                        {"status": "paused_by_admin"}
                        if pause == "certificate"
                        else {
                            "deleted_at": e.clock[0],
                            "ciphertext": None,
                            "licence_hmac": None,
                        }
                    )
                    conn.execute(
                        update(user_data_licences)
                        .where(user_data_licences.c.id == lid)
                        .values(**values)
                    )
        return secret

    try:
        assert verify(e, secret_loader=raced) == "failed_no_retry"
        assert e.calls == []
    finally:
        rds.delete(e.settings.ingest_paused_key)


def test_global_pause_during_daily_wait_blocks_second_send(
    env: Any,
    redis_sink: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    e, rds = env, redis_sink
    e.settings = e.settings.model_copy(update={"redis_url": "redis://127.0.0.1:6380/15"})
    rds.delete(e.settings.ingest_paused_key)
    monkeypatch.setattr(daily_lists, "send_paused", live.send_paused)
    bid = batch(e)

    def paused_wait(seconds: float) -> None:
        e.pause(seconds)
        rds.set(e.settings.ingest_paused_key, "1")

    try:
        assert run(e, bid, pause=paused_wait) == "failed"
        assert len(e.calls) == len(attempted(e, bid)) == 1
    finally:
        rds.delete(e.settings.ingest_paused_key)


@pytest.mark.parametrize("change", ["clock_back", "closed_day", "unknown_day"])
def test_daily_rechecks_window_calendar_and_backward_clock_after_wait(
    env: Any, change: str
) -> None:
    e = env
    bid = batch(e)

    def changed(seconds: float) -> None:
        e.pause(seconds)
        if change == "clock_back":
            e.clock[0] = e.clock[0].replace(hour=17, minute=59)
        else:
            with e.owner.begin() as conn:
                if change == "closed_day":
                    conn.execute(
                        update(trading_calendar)
                        .where(trading_calendar.c.date == e.day)
                        .values(is_open=False)
                    )
                else:
                    conn.execute(trading_calendar.delete().where(trading_calendar.c.date == e.day))

    assert run(e, bid, pause=changed) == "failed"
    assert len(e.calls) == len(attempted(e, bid)) == 1


def test_delete_readd_same_certificate_cannot_escape_halt_or_duplicate_notice(
    env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    e = env
    monkeypatch.setattr(service, "current_public_key", lambda _: (1, e.seal_key.public_key()))
    monkeypatch.setattr(service, "db_now", lambda _: e.clock[0])
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(licence_hmac=service.licence_hmac(e.settings, e.plaintext))
        )
    bid = batch(e)
    assert run(e, bid, upstream=lambda *_: (429, None)) == "failed"
    original_halt = shared_gate.bound_halt(e.root, e.lid)
    e.clock[0] += dt.timedelta(minutes=3)
    with e.worker.begin() as conn:
        assert service.delete_licence(conn, user_id=e.user, settings=e.settings)
        result = service.set_licence(
            conn,
            e.settings,
            user_id=e.user,
            licence=e.plaintext,
            tier="free",
            has_quant_pro=False,
            expires_on=None,
        )
    new_id = result.row.id
    assert new_id != e.lid
    policy = e.root / "policy.json"
    obj = json.loads(policy.read_text())
    obj["licences"][str(new_id)] = {"per_minute_limit": 150}
    policy.write_text(json.dumps(obj))
    grant = dataclasses.replace(e.verification_grant, licence_id=new_id, receipt_id=uuid.uuid4())
    monkeypatch.setattr(verification, "read_grant", lambda: grant)
    assert verify(e, intent=VerifyIntent(new_id, uuid.uuid4())) == "failed_no_retry"
    assert shared_gate.bound_halt(e.root, new_id) == original_halt
    assert e.calls == []
    live.sync_halts(e.collector, e.settings, SimpleNamespace(eval=lambda *a: "1"), e.root)
    with e.owner.connect() as conn:
        assert (
            conn.execute(
                select(user_data_licences.c.status).where(user_data_licences.c.id == new_id)
            ).scalar_one()
            == "ip_limited"
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(notifications)
                .where(
                    notifications.c.user_id.in_([e.user, e.admin]),
                )
            ).scalar_one()
            == 2
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(data_licence_events)
                .where(
                    data_licence_events.c.user_id == e.user,
                    data_licence_events.c.event == "ip_limited",
                )
            ).scalar_one()
            == 1
        )

    # Synthetic state-machine callbacks model separately authorized later probes;
    # the persisted halt is not removed and no HTTP is executed here.
    for offset in (0, 1):
        live.feedback(
            e.collector,
            e.settings,
            new_id,
            live.Signal.IP_LIMITED,
            token=uuid.uuid4(),
            at=e.clock[0] + dt.timedelta(seconds=offset),
            code="103",
        )
    with e.owner.connect() as conn:
        assert conn.execute(
            select(user_data_licences.c.paused_until).where(
                user_data_licences.c.id == new_id,
            )
        ).scalar_one() == e.clock[0] + dt.timedelta(seconds=3601)


@pytest.mark.skipif(os.name == "nt", reason="root-owned POSIX receipt validation")
def test_verification_receipt_cannot_be_replaced_by_daily_budget_or_writable_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "verification.json"
    now = dt.datetime.now(dt.UTC)
    body = {
        "kind": "mairui_licence_verification",
        "user_id": str(uuid.uuid4()),
        "licence_id": str(uuid.uuid4()),
        "receipt_id": str(uuid.uuid4()),
        "not_before": (now - dt.timedelta(minutes=1)).isoformat(),
        "expires_at": (now + dt.timedelta(minutes=1)).isoformat(),
        "max_http_requests": 1,
    }
    path.write_text(json.dumps(body))
    path.chmod(0o444)
    assert verification_grants.read_grant(path) is not None
    path.chmod(0o600)
    assert verification_grants.read_grant(path) is None
    path.write_text(json.dumps({**body, "kind": "mairui_daily_snapshot", "max_http_requests": 3}))
    path.chmod(0o444)
    assert verification_grants.read_grant(path) is None
