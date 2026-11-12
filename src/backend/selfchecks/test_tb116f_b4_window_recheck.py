# ruff: noqa: S101, ANN001
"""T-B116f B-4: window lease re-check uses a 0.5s budget; refusal logs category=lease."""

from __future__ import annotations

import datetime as dt
import io
import logging
import multiprocessing
import os
import time
import uuid
from multiprocessing.connection import Connection
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.ingest import egress as eg
from app.ingest import ip_limit as ipl
from app.ingest.core import IngestCore
from app.ingest.state import Priority

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 21, 40, tzinfo=dt.UTC)
FAKE_LIC = "FAKE-" + "tb116f" + "-b4"


def _url() -> str:
    u = (
        os.environ.get("TB116F_DATABASE_URL")
        or os.environ.get("TB116D_DATABASE_URL")
        or os.environ.get("TB116B_DATABASE_URL")
    )
    if not u:
        pytest.skip("TB116F_DATABASE_URL not set")
    return u


def _seed(eng: Engine, uid: uuid.UUID, lid: uuid.UUID) -> None:
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.users(id, username, password_hash, role, status) "
                "VALUES (:id, :u, 'x', 'user', 'approved')"
            ),
            {"id": uid, "u": f"u{uid.hex[:12]}"},
        )
        conn.execute(
            text(
                "INSERT INTO app.user_data_licences("
                "id, user_id, ciphertext, seal_key_version, licence_hmac, tier, status"
                ") VALUES (:id, :uid, decode('00','hex'), 1, decode(:hm,'hex'), 'annual', 'active')"
            ),
            {"id": lid, "uid": uid, "hm": uuid.uuid4().hex},
        )


def test_tb116f_b4_slow_admit_still_reaches_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    eng = create_engine(_url(), hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid, lid)
    core = IngestCore(CFG, engine=eng)
    captured: list[str] = []

    @event.listens_for(eng, "before_cursor_execute")
    def _cap(conn, cursor, statement, parameters, context, executemany) -> None:
        captured.append(" ".join(str(statement).split()))

    orig = ipl.acquire_ip_limit_lock

    def slow(conn, user_id) -> None:
        time.sleep(2.65)
        return orig(conn, user_id)

    monkeypatch.setattr(ipl, "acquire_ip_limit_lock", slow)
    calls: list[str] = []

    def transport(path: str, secret: str) -> tuple[int, object]:
        calls.append(path)
        return 200, {"ok": True}

    with eg.single_egress(eng) as lease:
        assert lease is not None
        eg.mairui_get(
            lease=lease,
            core=core,
            engine=eng,
            licence_id=lid,
            user_id=uid,
            path="/hslt/list/",
            secret=FAKE_LIC,
            priority=Priority.P1,
            clock=lambda: NOW0,
            stop=tmp_path / "S",
            halt=tmp_path / "H",
            transport=transport,
        )
    assert calls == ["/hslt/list/"]
    timeouts = [
        s for s in captured if "set local" in s.lower() and "statement_timeout" in s.lower()
    ]
    assert any("499ms" in s or "500ms" in s for s in timeouts), timeouts
    eng.dispose()


def _window_reject_child(output: Connection) -> None:
    from app.ingest import netguard as ng

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.WARNING)
    log = logging.getLogger("app.ingest.netguard")
    log.addHandler(handler)
    log.setLevel(logging.WARNING)
    ng.install()
    try:
        with ng.egress_window(None):
            raise SystemExit(2)
    except ng.EgressBlocked:
        output.send(buf.getvalue())
    finally:
        output.close()


def test_tb116f_b4_window_reject_logs_lease_category() -> None:
    # The audit hook is sticky; spawn a fresh interpreter and keep it out of pytest.
    ctx = multiprocessing.get_context("spawn")
    received, sent = ctx.Pipe(duplex=False)
    child = ctx.Process(target=_window_reject_child, args=(sent,))
    child.start()
    sent.close()
    try:
        child.join(timeout=15)
        assert not child.is_alive(), "isolated log check exceeded 15s"
        assert child.exitcode == 0
        assert received.poll(), "isolated child did not report an EgressBlocked refusal"
        output = received.recv()
        assert "event=egress_window" in output, output
        assert "category=lease" in output, output
        assert "window=none" in output, output
        low = output.lower()
        assert "http://" not in low
        assert "https://" not in low
        assert "mairuiapi.com" not in low
    finally:
        if child.is_alive():
            child.terminate()
            child.join()
        received.close()
        child.close()
