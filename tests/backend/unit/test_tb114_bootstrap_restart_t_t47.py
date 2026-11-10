# ruff: noqa: S101
"""T-T47 / T-B114：拿不到 engine 退出码 78；两次启动后计数仍在。"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 18, 0, tzinfo=dt.UTC)
TIER = DataLicenceTier.ANNUAL
ACTIVE = DataLicenceStatus.ACTIVE
INGEST_PY = ROOT / "src/backend/app/workers/ingest.py"


def _require_db() -> str:
    url = os.environ.get("TT41_DATABASE_URL") or os.environ.get("TB114_DATABASE_URL")
    if not url:
        pytest.skip(
            "TT41_DATABASE_URL/TB114_DATABASE_URL 未设置：T-B114 两启计数需隔离 PG（T-T47）"
        )
    return url


def _seed(engine: Engine, uid: uuid.UUID, lid: uuid.UUID) -> None:
    with engine.begin() as conn:
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
                ") VALUES ("
                ":id, :uid, decode('00','hex'), 1, decode(:hm,'hex'), 'annual', 'active')"
            ),
            {"id": lid, "uid": uid, "hm": uuid.uuid4().hex},
        )


def test_tb114_main_source_wires_bootstrap() -> None:
    src = INGEST_PY.read_text(encoding="utf-8")
    assert "def bootstrap_ingest_core" in src
    main_body = src.split("def main", 1)[1].split("\nif __name__", 1)[0]
    assert "bootstrap_ingest_core" in main_body
    boot = src.split("def bootstrap_ingest_core", 1)[1].split("\ndef ", 1)[0]
    assert "IngestCore(" in boot and "engine=" in boot
    assert "set_ingest_core" in boot


def test_tb114_no_engine_main_returns_78(monkeypatch: pytest.MonkeyPatch) -> None:
    """拿不到 engine（无 DATABASE_URL）时 main 退出码 78，且不进入 run。"""
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    monkeypatch.delenv("APP_MASTER_KEY", raising=False)

    from app.ingest import runtime
    from app.workers import ingest as ingest_worker

    if not hasattr(ingest_worker, "bootstrap_ingest_core"):
        pytest.fail("bootstrap_ingest_core 缺失")

    runtime.set_ingest_core(None)
    monkeypatch.setattr(ingest_worker, "legacy_licence_present", lambda environ=None: False)
    monkeypatch.setattr(ingest_worker, "master_key_present", lambda environ=None: False)

    class _Settings:
        database_url = None
        business = SimpleNamespace(
            ingest=SimpleNamespace(heartbeat=SimpleNamespace(interval_s=15), licences=CFG)
        )

    import app.config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _Settings())
    entered: list[str] = []

    def _fake_run(*a: object, **k: object) -> int:
        entered.append("run")
        return 0

    monkeypatch.setattr(ingest_worker, "run", _fake_run)
    rc = ingest_worker.main()
    assert rc == 78
    assert rc == ingest_worker.EXIT_LEGACY_LICENCE
    assert entered == []
    assert runtime.get_ingest_core() is None


def test_tb114_engine_probe_fail_main_returns_78(monkeypatch: pytest.MonkeyPatch) -> None:
    """DATABASE_URL 有值但探测失败时同样退出码 78。"""
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    monkeypatch.delenv("APP_MASTER_KEY", raising=False)

    from app.ingest import runtime
    from app.workers import ingest as ingest_worker

    runtime.set_ingest_core(None)
    monkeypatch.setattr(ingest_worker, "legacy_licence_present", lambda environ=None: False)
    monkeypatch.setattr(ingest_worker, "master_key_present", lambda environ=None: False)

    class _Settings:
        database_url = SecretStr("postgresql+psycopg://nobody@127.0.0.1:1/nope")
        business = SimpleNamespace(
            ingest=SimpleNamespace(heartbeat=SimpleNamespace(interval_s=15), licences=CFG)
        )

    import app.config as config_mod
    from app.db import engine as engine_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _Settings())

    class _BoomEngine:
        def connect(self) -> Any:
            raise OSError("tt47 synthetic probe fail")

    monkeypatch.setattr(engine_mod, "engine_for", lambda url: _BoomEngine())
    entered: list[str] = []
    monkeypatch.setattr(
        ingest_worker, "run", lambda *a, **k: entered.append("run") or 0
    )
    rc = ingest_worker.main()
    assert rc == 78
    assert entered == []
    assert runtime.get_ingest_core() is None


def test_tb114_two_starts_escalation_count_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    """两次启动后 IP 限流计数仍在（第三击升级）。"""
    url = _require_db()
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")

    from app.db import engine as engine_mod
    from app.ingest import runtime
    from app.ingest.core import IngestCore
    from app.workers import ingest as ingest_worker

    engine_mod.engine_for.cache_clear()
    runtime.set_ingest_core(None)

    uid, lid = uuid.uuid4(), uuid.uuid4()
    admin = create_engine(url, hide_parameters=True)
    _seed(admin, uid, lid)

    class _Settings:
        database_url = SecretStr(url)
        business = SimpleNamespace(
            ingest=SimpleNamespace(
                heartbeat=SimpleNamespace(interval_s=15, ttl_s=30),
                licences=CFG,
            )
        )

    def _hit(core: IngestCore, when: dt.datetime) -> list[str]:
        core.tick(when)
        return [t.event for t in core.apply_ip_limited(lid, when)]

    eng1 = ingest_worker.bootstrap_ingest_core(_Settings())  # type: ignore[arg-type]
    core1 = runtime.get_ingest_core()
    assert core1 is not None and core1.engine is eng1
    core1.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    assert "ip_limited" in _hit(core1, NOW0)
    assert "ip_limited" in _hit(core1, NOW0 + dt.timedelta(minutes=5))

    runtime.set_ingest_core(None)
    assert runtime.get_ingest_core() is None

    eng2 = ingest_worker.bootstrap_ingest_core(_Settings())  # type: ignore[arg-type]
    core2 = runtime.get_ingest_core()
    assert core2 is not None and core2 is not core1
    t3 = NOW0 + dt.timedelta(minutes=10)
    core2.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=t3)
    events = _hit(core2, t3)
    assert "ip_limited_escalated" in events, f"重启后计数丢失: {events}"

    with eng2.connect() as conn:
        n_esc = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id=:u AND actor='ingest' AND event='paused' "
                "AND to_status='ip_limited'"
            ),
            {"u": uid},
        ).scalar_one()
    assert n_esc >= 1
    assert core2.user_escalated_until(lid) is not None

    runtime.set_ingest_core(None)
    engine_mod.engine_for.cache_clear()
