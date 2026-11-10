# ruff: noqa: S101, S105, ANN001, ANN201, E501
"""T-B116e M-1: pg_locks check is a short SET LOCAL transaction; lock session not in a txn during HTTP."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.ingest import egress as eg
from app.ingest.core import IngestCore
from app.ingest.state import Priority

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 20, 40, tzinfo=dt.UTC)
FAKE_LIC = "FAKE-" + "tb116e" + "-m1"


def _url() -> str:
    u = os.environ.get("TB116E_DATABASE_URL") or os.environ.get("TB116D_DATABASE_URL")
    if not u:
        pytest.skip("TB116E_DATABASE_URL not set")
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


def test_tb116e_m1_pg_locks_short_txn_idle_during_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    eng = create_engine(_url(), hide_parameters=True)
    captured: list[str] = []

    @event.listens_for(eng, "before_cursor_execute")
    def _cap(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        captured.append(" ".join(str(statement).split()))

    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid, lid)
    core = IngestCore(CFG, engine=eng)
    halt = tmp_path / "H"
    states: list[str | None] = []

    def transport(path: str, secret: str) -> tuple[int, object]:
        with eng.connect() as probe:
            state = probe.execute(
                text("SELECT state FROM pg_stat_activity WHERE pid = :p"),
                {"p": lease.lock_pid},
            ).scalar()
        states.append(state)
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
            halt=halt,
            transport=transport,
        )

    assert states, "transport was not called"
    assert states[0] == "idle", f"lock session during HTTP was {states[0]!r}, expected idle"
    assert any(
        "set local" in s.lower() and "statement_timeout" in s.lower() for s in captured
    ), "pg_locks path did not issue SET LOCAL statement_timeout"
    assert any("pg_locks" in s.lower() for s in captured)
    eng.dispose()
