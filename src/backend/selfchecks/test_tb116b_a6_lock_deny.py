# ruff: noqa: S101
"""T-B116b: B-1(a)/B-1(b)/L-a/M-2 selfchecks. Fake transport only; o61 temp DB."""

from __future__ import annotations

import datetime as dt
import os
import time
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.ingest import egress as eg
from app.ingest import ip_limit as ipl
from app.ingest.core import IngestCore
from app.ingest.state import Priority
from app.ingest.upstream import Signal
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 19, 30, tzinfo=dt.UTC)
SECRET = "FAKE-" + "tb116b" + "-a6-lic"


def _url() -> str:
    u = os.environ.get("TB116B_DATABASE_URL") or os.environ.get("TB116_DATABASE_URL")
    if not u:
        pytest.skip("TB116B_DATABASE_URL not set")
    return u


def _seed(eng: Engine, uid: uuid.UUID, lid: uuid.UUID, *, status: str = "active") -> None:
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
                ") VALUES (:id, :uid, decode('00','hex'), 1, decode(:hm,'hex'), 'annual', :st)"
            ),
            {"id": lid, "uid": uid, "hm": uuid.uuid4().hex, "st": status},
        )


def test_tb116b_b1a_ip_limit_lock_held_denies_within_3s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B-1(a)/A6a: xact lock held, no pending → core_denied ≤3s, transport 0."""
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    eng = create_engine(_url(), hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid, lid)
    core = IngestCore(CFG, engine=eng)
    calls: list[str] = []

    def transport(path: str, secret: str) -> tuple[int, object]:
        calls.append(path)
        return 200, {"ok": True}

    holder = eng.connect()
    holder.execute(text("BEGIN"))
    ipl.acquire_ip_limit_lock(holder, uid)
    stop, halt = tmp_path / "S", tmp_path / "H"
    t0 = time.monotonic()
    try:
        with eg.single_egress(eng) as lease:
            assert lease is not None
            with pytest.raises(eg.EgressDenied) as ei:
                eg.mairui_get(
                    lease=lease,
                    core=core,
                    engine=eng,
                    licence_id=lid,
                    user_id=uid,
                    path="/hslt/list/",
                    secret=SECRET,
                    priority=Priority.P1,
                    clock=lambda: NOW0,
                    stop=stop,
                    halt=halt,
                    transport=transport,
                )
            assert ei.value.code == "core_denied"
    finally:
        elapsed = time.monotonic() - t0
        holder.rollback()
        holder.close()
    assert elapsed <= 3.0, f"B-1(a) should deny within 3s, got {elapsed:.2f}s"
    assert calls == []


def test_tb116b_b1b_forged_lease_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-1(b)/A6b: caller-built EgressLease(held=True) → single_egress_not_held, transport 0."""
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    eng = create_engine(_url(), hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid, lid)
    core = IngestCore(CFG, engine=eng)
    calls: list[str] = []

    def transport(path: str, secret: str) -> tuple[int, object]:
        calls.append(path)
        return 200, {"ok": True}

    stop, halt = tmp_path / "S", tmp_path / "H"
    with pytest.raises(eg.EgressDenied) as ei:
        eg.mairui_get(
            lease=eg.EgressLease(held=True),
            core=core,
            engine=eng,
            licence_id=lid,
            user_id=uid,
            path="/hslt/list/",
            secret=SECRET,
            priority=Priority.P1,
            clock=lambda: NOW0,
            stop=stop,
            halt=halt,
            transport=transport,
        )
    assert ei.value.code == "single_egress_not_held"
    assert calls == []


def test_tb116b_m2_102_persists_invalid_then_denies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-2/A25: 102 → write INVALID to DB, then next mairui_get is licence_unavailable."""
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    eng = create_engine(_url(), hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid, lid)
    core = IngestCore(CFG, engine=eng)
    calls: list[str] = []

    def transport_102(path: str, secret: str) -> tuple[int, object]:
        calls.append(path)
        return 102, None

    stop, halt = tmp_path / "S", tmp_path / "H"
    with eg.single_egress(eng) as lease:
        assert lease is not None
        result = eg.mairui_get(
            lease=lease,
            core=core,
            engine=eng,
            licence_id=lid,
            user_id=uid,
            path="/hslt/list/",
            secret=SECRET,
            priority=Priority.P1,
            clock=lambda: NOW0,
            stop=stop,
            halt=halt,
            transport=transport_102,
        )
    assert result.signal == Signal.INVALID
    with eng.connect() as conn:
        st = conn.execute(
            text("SELECT status FROM app.user_data_licences WHERE id=:id"),
            {"id": lid},
        ).scalar_one()
    assert st == "invalid"
    # second call must deny without transport
    n = len(calls)
    with eg.single_egress(eng) as lease2:
        assert lease2 is not None
        with pytest.raises(eg.EgressDenied) as ei:
            eg.mairui_get(
                lease=lease2,
                core=core,
                engine=eng,
                licence_id=lid,
                user_id=uid,
                path="/hslt/list/",
                secret=SECRET,
                priority=Priority.P1,
                clock=lambda: NOW0,
                stop=stop,
                halt=halt,
                transport=transport_102,
            )
        assert ei.value.code == "licence_unavailable"
    assert len(calls) == n  # no additional transport


def test_tb116b_m2_upsert_does_not_downgrade_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-2: memory INVALID must not be overwritten back to active by upsert."""
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    core = IngestCore(CFG, engine=None)
    lid, uid = uuid.uuid4(), uuid.uuid4()
    core.upsert(
        lid,
        user_id=uid,
        tier=DataLicenceTier.ANNUAL,
        status=DataLicenceStatus.INVALID,
        now=NOW0,
        hydrate=False,
    )
    assert core.state(lid).status == DataLicenceStatus.INVALID
    core.upsert(
        lid,
        user_id=uid,
        tier=DataLicenceTier.ANNUAL,
        status=DataLicenceStatus.ACTIVE,
        now=NOW0,
        hydrate=False,
    )
    assert core.state(lid).status == DataLicenceStatus.INVALID
