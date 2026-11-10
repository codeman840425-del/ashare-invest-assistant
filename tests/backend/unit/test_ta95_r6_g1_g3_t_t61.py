# ruff: noqa: S101
"""T-T61 / T-A95 R6：回填 SQL 边界 G1–G3（PG 等号窗口、标记严格不等、截止等号放行）。"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.ingest import ip_limit as ipl
from app.ingest.state import LicenceState, Priority
from app.schemas.enums import DataLicenceStatus, DataLicenceTier
from pathlib import Path
import sys
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pg_o61 import (  # noqa: E402
    PgOwnershipError,
    guard_temp_pg,
    libpq_sqlalchemy_url,
    resolve_libpq_params,
    validate_temp_db_name,
)

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)
WINDOW = CFG.ip_limited_escalate.window_s
PAUSE = CFG.ip_limited_escalate.pause_s


def _template_db() -> str:
    """私有模板库名：环境变量 TT51_TEMPLATE_DB，默认 tt51_tpl，经格式校验。"""
    return validate_temp_db_name(os.environ.get("TT51_TEMPLATE_DB", "tt51_tpl"))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    """按 T-T68 护栏在目标实例上建 tt61_* 临时库；模块结束 DROP 并核无残留。

    模板库名仍读 TT51_TEMPLATE_DB（默认 tt51_tpl）。本机缺省须核 o61-pg；
    CI 非缺省端口不误拦；禁连 o53/o55/o57/o60。连接读 PGHOST/PGPORT/PGUSER/PGPASSWORD。
    """
    host, port, _user, _password = resolve_libpq_params()
    try:
        guard_temp_pg(host, port)
    except PgOwnershipError as exc:
        pytest.fail(str(exc))
    name = validate_temp_db_name("tt61_r6_" + uuid.uuid4().hex[:8])
    tpl = _template_db()
    admin = create_engine(
        libpq_sqlalchemy_url("postgres"),
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
    )
    try:
        with admin.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {name} TEMPLATE {tpl}"))
    except Exception as exc:  # noqa: BLE001
        admin.dispose()
        pytest.skip(f"无法在目标实例上创建临时库：{type(exc).__name__}")
    eng = create_engine(libpq_sqlalchemy_url(name), hide_parameters=True)
    try:
        yield eng
    finally:
        eng.dispose()
        try:
            with admin.connect() as conn:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :d AND pid <> pg_backend_pid()"
                    ),
                    {"d": name},
                )
                conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
            with admin.connect() as conn:
                left = conn.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname = :d"),
                    {"d": name},
                ).scalar_one()
            assert left == 0, f"{name} DROP 后仍残留"
        finally:
            admin.dispose()


def _seed_user(eng: Engine) -> tuple[uuid.UUID, uuid.UUID]:
    uid, lid = uuid.uuid4(), uuid.uuid4()
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
                ") VALUES ("
                ":id, :uid, decode('00','hex'), 1, decode(:hm,'hex'), 'annual', 'active')"
            ),
            {"id": lid, "uid": uid, "hm": uuid.uuid4().hex},
        )
    return uid, lid


def _write(eng: Engine, *, uid: uuid.UUID, lid: uuid.UUID, event: str, to_status: str, at: dt.datetime) -> None:
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ops.data_licence_events("
                "licence_id, user_id, event, actor, from_status, to_status, upstream_code, at"
                ") VALUES ("
                ":lid, :uid, :ev, 'ingest', 'active', :st, '103', :at)"
            ),
            {"lid": lid, "uid": uid, "ev": event, "st": to_status, "at": at},
        )


def _rehydrate(eng: Engine, uid: uuid.UUID, now: dt.datetime) -> ipl.UserIpLimitMemory:
    with eng.connect() as conn:
        return ipl.rehydrate(conn, uid, window_s=WINDOW, pause_s=PAUSE, now=now)


def _ats(mem: ipl.UserIpLimitMemory) -> list[dt.datetime]:
    out = []
    for h in mem.hits:
        if h.tzinfo is None:
            h = h.replace(tzinfo=dt.UTC)
        else:
            h = h.astimezone(dt.UTC)
        out.append(h)
    return out


def test_g1_sql_window_start_inclusive(engine: Engine) -> None:
    """G1：PG 上 at >= :ws 含等号；恰为 now−window_s 的命中计入，早 1s 的不计入。"""
    uid, lid = _seed_user(engine)
    now = NOW0
    ws = now - dt.timedelta(seconds=WINDOW)
    _write(engine, uid=uid, lid=lid, event="ip_limited", to_status="ip_limited", at=ws)
    _write(
        engine,
        uid=uid,
        lid=lid,
        event="ip_limited",
        to_status="ip_limited",
        at=ws - dt.timedelta(seconds=1),
    )
    mem = _rehydrate(engine, uid, now)
    ats = _ats(mem)
    assert ws in ats, f"等号窗口起点应计入，实得 {len(ats)} 条"
    assert (ws - dt.timedelta(seconds=1)) not in ats
    assert len(ats) == 1


def test_g2_sql_mark_strictly_after(engine: Engine) -> None:
    """G2：at > :mark 严格不等；与标记同 at 的升级那一击及标记前窗口内命中重启后均不计。"""
    uid, lid = _seed_user(engine)
    now = NOW0
    ws = now - dt.timedelta(seconds=WINDOW)
    before = ws + dt.timedelta(seconds=60)
    mark = now - dt.timedelta(seconds=30)
    after = mark + dt.timedelta(seconds=1)
    _write(engine, uid=uid, lid=lid, event="ip_limited", to_status="ip_limited", at=before)
    _write(engine, uid=uid, lid=lid, event="ip_limited", to_status="ip_limited", at=mark)
    _write(engine, uid=uid, lid=lid, event="paused", to_status="ip_limited", at=mark)
    _write(engine, uid=uid, lid=lid, event="ip_limited", to_status="ip_limited", at=after)
    mem = _rehydrate(engine, uid, now)
    ats = _ats(mem)
    assert before not in ats
    assert mark not in ats
    assert after in ats
    assert len(ats) == 1
    assert mem.escalated_until is not None
    until = mem.escalated_until.astimezone(dt.UTC) if mem.escalated_until.tzinfo else mem.escalated_until.replace(tzinfo=dt.UTC)
    assert until == mark + dt.timedelta(seconds=PAUSE)


def test_g3_deadline_equal_releases(engine: Engine) -> None:
    """G3：now == last_mark + pause_s 应放行（现有例只用 +1s）。"""
    uid, lid = _seed_user(engine)
    mark = NOW0
    until = mark + dt.timedelta(seconds=PAUSE)
    _write(engine, uid=uid, lid=lid, event="ip_limited", to_status="ip_limited", at=mark)
    _write(engine, uid=uid, lid=lid, event="paused", to_status="ip_limited", at=mark)
    mem = _rehydrate(engine, uid, until)
    assert mem.escalated_until is not None
    got = mem.escalated_until.astimezone(dt.UTC) if mem.escalated_until.tzinfo else mem.escalated_until.replace(tzinfo=dt.UTC)
    assert got == until
    # 截止前：tick 不恢复，allows 为假
    st = LicenceState(cfg=CFG, tier=DataLicenceTier.ANNUAL, status=DataLicenceStatus.IP_LIMITED)
    before = until - dt.timedelta(seconds=1)
    ev_before = st.tick(before, user_escalated_until=until)
    assert not any(t.event == "resumed" for t in ev_before), ev_before
    assert st.status == DataLicenceStatus.IP_LIMITED
    assert st.allows(Priority.P0, before, user_escalated_until=until) is False
    # now == last_mark+pause_s：tick 恢复为 ACTIVE，随后放行
    ev = st.tick(until, user_escalated_until=until)
    assert any(t.event == "resumed" for t in ev), ev
    assert st.status == DataLicenceStatus.ACTIVE
    assert st.allows(Priority.P0, until, user_escalated_until=until) is True


def test_tt69_ta95_ci_like_target_is_not_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI 形态（db:5432 / 127.0.0.1:5432）走与 fixture 相同的 guard_temp_pg，不得误拦。"""
    monkeypatch.setenv("PGHOST", "db")
    monkeypatch.setenv("PGPORT", "5432")
    monkeypatch.setenv("PGUSER", "aia")
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: (None, "monkeypatch 模拟：CI 无 docker 映射，未连接"),
    )
    host, port, _user, _password = resolve_libpq_params()
    assert guard_temp_pg(host, port) is None
    assert guard_temp_pg("127.0.0.1", 5432) is None


def test_tt69_ta95_refuses_forbidden_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    """o53/o55/o57/o60 必须拒绝，且不发起连接。"""

    def _lookup_must_not_run(host: str, port: int) -> tuple[None, str]:
        raise AssertionError(f"不应查询或连接 {host}:{port}")

    monkeypatch.setattr("pg_o61.lookup_tcp_owner", _lookup_must_not_run)
    for host, mark in (
        ("o53-p3-pg", "o53"),
        ("o55-p2-pg", "o55"),
        ("o57-pg", "o57"),
        ("o60-pg", "o60"),
    ):
        with pytest.raises(PgOwnershipError) as ei:
            guard_temp_pg(host, 5432)
        assert mark in str(ei.value)
        assert "拒绝建库" in str(ei.value)
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: ("o55-p2-pg", "monkeypatch 模拟，未连接该实例"),
    )
    with pytest.raises(PgOwnershipError) as ei:
        guard_temp_pg("127.0.0.1", 55494)
    assert "o55" in str(ei.value)

