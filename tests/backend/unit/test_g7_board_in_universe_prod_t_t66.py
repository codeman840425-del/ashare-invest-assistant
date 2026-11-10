# ruff: noqa: S101
"""T-T66：直接调用生产 ``board_in_universe`` 与 ``write_candidate`` persist（service.py:355）门闩。

不使用 T-T63 测试内复刻函数 ``_board_in_universe``。夹具代码均为【虚构】；不调麦蕊。
T-T68：库例读 PGHOST/PGPORT/PGUSER/PGPASSWORD（缺省 127.0.0.1:55461）；本机缺省须核 o61-pg，
CI 非缺省端口不误拦；禁连 o53/o55/o57/o60。篡改自证改为改写生产函数对象，避免同义反复。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src/backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config_files import MarketRulesConfig
from app.signals import service as signals_service
from app.signals.models import MarketFacts, SignalInput
from app.signals.service import snapshot_items, write_candidate
from app.strategy.universe_norm import board_in_universe, normalize_boards
from pg_o61 import (
    PgOwnershipError,
    guard_temp_pg,
    libpq_sqlalchemy_url,
    resolve_libpq_params,
    template_db_name,
    validate_temp_db_name,
)

# 官方卡板块开关（未先走 preflight 改写），用于直接打到生产归一
_OFFICIAL_BOARDS = {"main": True, "chinext": True, "star": True, "bse": False}
_FIC_BSE = "830991.BJ"
_FIC_MAIN = "600991.SH"
_AT = dt.datetime(2026, 11, 9, 7, 0, tzinfo=dt.UTC)  # 北京时间 15:00
_EXPR = "f.close_qfq > 0"
_UNIVERSE = {
    "pool": "持仓 ∪ 自选",
    "boards": dict(_OFFICIAL_BOARDS),
    "security_types": ["stock"],
}


def test_service_binds_production_board_in_universe() -> None:
    """service.py 调用点使用的就是 universe_norm.board_in_universe，不是测试复刻。"""
    assert signals_service.board_in_universe is board_in_universe


def test_h01_like_boards_exclude_bse_and_admit_main() -> None:
    boards = dict(_OFFICIAL_BOARDS)
    assert board_in_universe(boards, "bse") is False
    assert board_in_universe(boards, "main") is True
    assert board_in_universe(boards, "main_board") is True
    assert board_in_universe(boards, "chinext") is True
    assert board_in_universe(boards, "star") is True
    # 生产 normalize_boards 会把 main 拷到 main_board（契约/T-B119）
    assert normalize_boards(boards)["main_board"] is True


def test_main_main_board_alias_both_directions() -> None:
    assert board_in_universe({"main": True}, "main") is True
    assert board_in_universe({"main": True}, "main_board") is True
    assert board_in_universe({"main_board": True}, "main") is True
    assert board_in_universe({"main_board": True}, "main_board") is True
    # 双侧并存且不一致时不调和（T-A114 已登记残留）
    conflict = {"main": True, "main_board": False}
    assert board_in_universe(conflict, "main") is True
    assert board_in_universe(conflict, "main_board") is False


def test_empty_or_missing_board_follows_normalize_board_to_main() -> None:
    """lots.normalize_board：None/''/'main' → main_board；官方主板打开时放行（T-A114）。"""
    boards = dict(_OFFICIAL_BOARDS)
    assert board_in_universe(boards, None) is True
    assert board_in_universe(boards, "") is True
    # 无主板旗标时，空板不会被放行
    assert board_in_universe({"bse": False, "star": True}, None) is False
    assert board_in_universe(None, "main") is False
    assert board_in_universe({}, None) is False


def test_unknown_and_wrong_case_boards_are_fail_closed() -> None:
    """未知键与大小写变体：.get(..., False)，normalize_board 不折叠大小写。"""
    boards = dict(_OFFICIAL_BOARDS)
    assert board_in_universe(boards, "foo") is False
    assert board_in_universe(boards, "unknown") is False
    assert board_in_universe(boards, "BJ") is False
    assert board_in_universe(boards, "MAIN") is False
    assert board_in_universe(boards, "Main") is False
    assert board_in_universe(boards, "BSE") is False


def test_tamper_board_in_universe_always_true_fails_exclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """篡改自证：改写生产函数对象后，本文件 from-import 与 service 绑定上的北交所排除必须 FAIL。

    旧写法把模块属性换成新 lambda，再对该新名字断言，是同义反复；且只补丁模块属性
    时，本文件已绑定的 ``board_in_universe`` 仍走原函数，单独那段篡改无效。
    """
    boards = dict(_OFFICIAL_BOARDS)
    assert board_in_universe(boards, "bse") is False
    assert signals_service.board_in_universe is board_in_universe

    def always_true(_boards: object, _board: object) -> bool:
        return True

    # 改写函数对象本身，所有共享该对象的绑定一并生效（含 service.py 的 from-import）
    monkeypatch.setattr(board_in_universe, "__code__", always_true.__code__)
    with pytest.raises(AssertionError):
        assert board_in_universe(boards, "bse") is False
    with pytest.raises(AssertionError):
        assert signals_service.board_in_universe(boards, "bse") is False


# ---- service.py:355 调用链（o61 临时库，虚构证券）---------------------------


@pytest.fixture(scope="module")
def o61_engine() -> Iterator[Engine]:
    host, port, _user, _password = resolve_libpq_params()
    try:
        guard_temp_pg(host, port)
    except PgOwnershipError as exc:
        pytest.fail(str(exc))
    name = validate_temp_db_name("tt68_" + uuid.uuid4().hex[:8])
    tpl = template_db_name()
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
    engine = create_engine(
        libpq_sqlalchemy_url(name),
        hide_parameters=True,
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:n AND pid<>pg_backend_pid()"
                ),
                {"n": name},
            )
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        admin.dispose()
        # 核无残留
        chk = create_engine(
            libpq_sqlalchemy_url("postgres"),
            isolation_level="AUTOCOMMIT",
            hide_parameters=True,
        )
        try:
            with chk.connect() as conn:
                left = conn.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname=:n"), {"n": name}
                ).scalar_one()
            assert left == 0, f"临时库 {name} 未删除"
        finally:
            chk.dispose()


@pytest.fixture(scope="module")
def seeded(o61_engine: Engine) -> dict[str, Any]:
    uid, acc, strat, ver, inst, snap = (uuid.uuid4() for _ in range(6))
    config = {
        "universe": _UNIVERSE,
        "mount_policy": "user",
        "screen": None,
        "spec": {
            "rules": [{"id": "E1", "role": "entry", "dimension": "technical", "expr": _EXPR}]
        },
    }
    # 北京时间 2026-11-09 15:00 对应 _AT；收盘后需下一开放日才能给出 next_open
    with o61_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.users(id, username, password_hash, role, status) "
                "VALUES (:id,:u,'x','user','approved')"
            ),
            {"id": uid, "u": "tt66_" + uid.hex[:8]},
        )
        conn.execute(
            text("INSERT INTO app.accounts(id, user_id, name) VALUES (:id,:uid,'虚构账户')"),
            {"id": acc, "uid": uid},
        )
        conn.execute(
            text(
                "INSERT INTO app.strategies(id, key, owner_user_id, name, horizons, status) "
                "VALUES (:id,:k,:uid,'虚构策略', ARRAY['short'], 'active')"
            ),
            {"id": strat, "k": "tt66_" + strat.hex[:8], "uid": uid},
        )
        conn.execute(
            text(
                "INSERT INTO app.strategy_versions("
                "id, strategy_id, version_no, config, config_hash, kind, lifecycle, param_hash"
                ") VALUES (:id,:sid,1,(:cfg)::jsonb,:h,'rule_template','published',:h)"
            ),
            {"id": ver, "sid": strat, "cfg": json.dumps(config), "h": ver.hex},
        )
        conn.execute(
            text(
                "INSERT INTO app.strategy_instances("
                "id, user_id, strategy_version_id, scope, account_id, status, origin, horizon"
                ") VALUES (:id,:uid,:vid,'account',:acc,'active','user','short')"
            ),
            {"id": inst, "uid": uid, "vid": ver, "acc": acc},
        )
        conn.execute(
            text(
                "INSERT INTO app.data_snapshots(id, created_at, purpose, items, hash, user_id) "
                "VALUES (:id,:at,'signal','{}',:h,:uid)"
            ),
            {"id": snap, "at": _AT, "h": snap.hex, "uid": uid},
        )
        conn.execute(
            text(
                "INSERT INTO market.securities(code, name, exchange, board, listing_status, type) "
                "VALUES "
                "(:bse,'虚构北交所','BJ','bse','listed','stock'), "
                "(:main,'虚构主板','SH','main','listed','stock')"
            ),
            {"bse": _FIC_BSE, "main": _FIC_MAIN},
        )
        conn.execute(
            text(
                "INSERT INTO app.watchlist_items(user_id, security_code) "
                "VALUES (:uid,:bse), (:uid,:main)"
            ),
            {"uid": uid, "bse": _FIC_BSE, "main": _FIC_MAIN},
        )
        conn.execute(
            text(
                "INSERT INTO market.trading_calendar(date, is_open) VALUES "
                "('2026-11-09', true), ('2026-11-10', true)"
            )
        )
    return {"user_id": uid, "instance_id": inst, "snapshot_id": snap}


def _signal(code: str, snapshot_id: uuid.UUID) -> SignalInput:
    eid = "tt66-fic-e1"
    return SignalInput.model_validate(
        {
            "security_code": code,
            "proposed_action": "buy",
            "t_leg": None,
            "score": None,
            "confidence": {"level": "high", "value": "0.8"},
            "stops": {"stop_loss": None, "take_profit": None, "time_stop_days": None},
            "rule_refs": [
                {
                    "rule_id": "E1",
                    "snippet_id": None,
                    "snippet_version": None,
                    "role": "entry",
                    "dimension": "technical",
                    "passed": True,
                    "value": None,
                    "threshold": _EXPR,
                    "evidence_ids": [eid],
                }
            ],
            "evidence": [
                {
                    "id": eid,
                    "key": "f.close_qfq",
                    "value": 12.5,
                    "unit": None,
                    "provider": "system",
                    "endpoint": None,
                    "data_as_of": _AT,
                    "fetched_at": _AT,
                    "epistemic_type": "fact",
                }
            ],
            "counter_evidence": [
                {"text": "【虚构】反证未触发", "expr": "f.close_qfq < 0", "evidence_ids": [eid]}
            ],
            "invalidation": [
                {"text": "【虚构】失效未触发", "expr": "f.close_qfq < 1", "evidence_ids": [eid]}
            ],
            "model_refs": [],
            "risk_flags": [],
            "valid_until": None,
            "snapshot_id": str(snapshot_id),
            "feature_set_version": "tt66-fictional",
            "created_at": _AT,
            "data_status": "fresh",
            "data_as_of": _AT,
            "gaps": [],
        }
    )


def _facts() -> MarketFacts:
    return MarketFacts(
        price=Decimal("12.5"),
        required_cash=Decimal("1250"),
        is_suspended=False,
        list_days=600,
        limit_locked_up=False,
        limit_locked_down=False,
    )


@pytest.fixture(scope="module")
def market_rules() -> MarketRulesConfig:
    return MarketRulesConfig.model_validate(
        yaml.safe_load((ROOT / "config/market_rules.yaml").read_text(encoding="utf-8"))
    )


def _write(
    engine: Engine,
    seeded: dict[str, Any],
    code: str,
    market_rules: MarketRulesConfig,
) -> dict[str, Any]:
    snap_id = uuid.uuid4()
    content = _signal(code, snap_id)
    facts = _facts()
    items = snapshot_items(content, facts)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.data_snapshots(id, created_at, purpose, items, hash, user_id) "
                "VALUES (:id,:at,'signal',(:items)::jsonb,:h,:uid)"
            ),
            {
                "id": snap_id,
                "at": _AT,
                "items": json.dumps(items),
                "h": snap_id.hex,
                "uid": seeded["user_id"],
            },
        )
        return write_candidate(
            conn,
            user_id=seeded["user_id"],
            instance_id=seeded["instance_id"],
            content=content,
            facts=facts,
            market_rules=market_rules,
        )


def test_write_candidate_persist_excludes_bse_via_service_355(
    o61_engine: Engine,
    seeded: dict[str, Any],
    market_rules: MarketRulesConfig,
) -> None:
    """经 write_candidate → persist（service.py:355）board_in_universe：北交所 outside_universe。"""
    result = _write(o61_engine, seeded, _FIC_BSE, market_rules)
    assert result["id"] is None
    assert result["diagnostic"] == "outside_universe"


def test_write_candidate_persist_admits_main_board_via_service_355(
    o61_engine: Engine,
    seeded: dict[str, Any],
    market_rules: MarketRulesConfig,
) -> None:
    """同一调用链：主板（主表 board=main）不得因板块被判 outside_universe。"""
    result = _write(o61_engine, seeded, _FIC_MAIN, market_rules)
    assert result.get("diagnostic") != "outside_universe"


# ---- T-T68：环境变量与护栏（monkeypatch，不实连 o53/o55/o57/o60）--------------


def test_resolve_libpq_params_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD"):
        monkeypatch.delenv(key, raising=False)
    host, port, user, password = resolve_libpq_params()
    assert (host, port, user, password) == ("127.0.0.1", 55461, "postgres", None)
    monkeypatch.setenv("PGHOST", "db")
    monkeypatch.setenv("PGPORT", "5432")
    monkeypatch.setenv("PGUSER", "aia")
    monkeypatch.setenv("PGPASSWORD", "ci-only")
    host, port, user, password = resolve_libpq_params()
    assert (host, port, user) == ("db", 5432, "aia")
    # 与环境对照，不把口令写进断言字面
    assert password is not None and password == os.environ["PGPASSWORD"]
    url = libpq_sqlalchemy_url("aia")
    rendered = url.render_as_string(hide_password=True)
    assert "5432" in rendered and "db" in rendered
    assert "ci-only" not in rendered


def test_guard_temp_pg_local_default_requires_o61(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: ("o61-pg", "monkeypatch 模拟，未连接"),
    )
    assert guard_temp_pg("127.0.0.1", 55461) == "o61-pg"
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: (None, "monkeypatch 模拟：缺省端口无归属"),
    )
    with pytest.raises(PgOwnershipError) as ei:
        guard_temp_pg("127.0.0.1", 55461)
    assert "o61-pg" in str(ei.value)


def test_guard_temp_pg_ci_like_target_is_not_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI（127.0.0.1:5432 或 db:5432）不得因不是 o61-pg 而误拦。"""
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: (None, "monkeypatch 模拟：CI 无 docker 映射，未连接"),
    )
    assert guard_temp_pg("127.0.0.1", 5432) is None
    assert guard_temp_pg("db", 5432) is None


def test_guard_temp_pg_refuses_forbidden_instances_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """禁连 o53/o55/o57/o60：只查名字/模拟归属，不发起连接。"""
    # 主机名命中，lookup 若被调用即失败，证明未查docker也拒绝
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

    # 非缺省端口但归属为禁连容器（本机误指 o55 的 55494 等）
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: ("o55-p2-pg", "monkeypatch 模拟，未连接该实例"),
    )
    with pytest.raises(PgOwnershipError) as ei:
        guard_temp_pg("127.0.0.1", 55494)
    assert "o55" in str(ei.value)
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: ("o53-p3-pg", "monkeypatch 模拟，未连接该实例"),
    )
    with pytest.raises(PgOwnershipError):
        guard_temp_pg("127.0.0.1", 55500)
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: ("o57-pg", "monkeypatch 模拟，未连接该实例"),
    )
    with pytest.raises(PgOwnershipError):
        guard_temp_pg("127.0.0.1", 55457)
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: ("o60-pg", "monkeypatch 模拟，未连接该实例"),
    )
    with pytest.raises(PgOwnershipError):
        guard_temp_pg("127.0.0.1", 55460)

