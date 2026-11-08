"""T-B30 / T-B30a 验收用例（评审 d018fad §3 / §5；plan 第 3280、3361 行：T-B30 以 T-B30a 完成为验收前提）。

T-B47（c9e1e73）已交付 GET /horizon-assessments 与分类计算（接口层用例见
test_auth_t_b03.py::test_v025_horizon_assessment_has_hints_and_classifier_1_2_0，严格断言）。本文件只覆盖
**尚未交付**的 T-B30 / T-B30a 验收条目，全部 ``xfail(strict=True)``、负责人 后端 T-B30a：后端实现后这些用例会
XPASS，strict 使其变红，提醒摘掉标记改为严格断言。

1. T-B30a：horizon_classifier.yaml ``features`` 列出的 15 个 ``f.*`` 都写入 ``app.feature_catalog``（单位、频率、
   可得时点、核实状态不为空，状态不是 gap / deprecated）；
2. 结果落库：GET /horizon-assessments 的 ``snapshot_id`` 是 ``app.data_snapshots`` 中真实存在的行
   （purpose=horizon、user_id=本人），且 ``app.symbol_horizon_assessments`` 有对应记录（trigger=on_demand）；
3. 三种重算触发：导入确认（``import``）、加自选（``watchlist_add``）、每周（``weekly``）各自写入一条评估；
4. 生成 ``proposed`` 状态的 ``strategy_instances``（origin=classifier、scope=security，确认在 T-B32）。

另有一条严格的自检：仓库 config/horizon_classifier.yaml 的 ``features`` 恰为 plan 第 3361 行列出的 15 个键。

只用一次性 testcontainers 数据库（authdb）；不连 be-b03a-pg / aia-t01，不调用麦蕊或任何真实行情接口。
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("tb30a_t25d", _HERE / "test_rulings_t_b46_47_t_t25d.py")
_t25d = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_t25d)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:
    pytest.skip(str(exc), allow_module_level=True)

authdb, sql, app_client, mkuser, session, make_settings = (
    _t25d.authdb, _t25d.sql, _t25d.app_client, _t25d.mkuser, _t25d.session, _t25d.make_settings)
API, Rec, require_route, has_route, REPO = _t25d.API, _t25d.Rec, _t25d.require_route, _t25d.has_route, _t25d.REPO
_seed_security, _uniq_code, _account, _trade, _hz = (
    _t25d._seed_security, _t25d._uniq_code, _t25d._account, _t25d._trade, _t25d._hz)

pytestmark = [pytest.mark.integration]

O_B30A = "后端 T-B30a（plan 第 3361 行：15 个 f.* 写入 feature_catalog / feature_bars_daily；T-B30 验收前提）"
O_B30 = "后端 T-B30a / T-B30（plan 第 3280 行：结果落库、导入确认 / 加自选 / 每周触发、生成 proposed strategy_instances）"
O_B30_PERSIST = O_B30 + "；契约 #27 ⑧：snapshot_id 须是 data_snapshots 真实行（本地 main 为 uuid5 计算值，未落库）"

#: plan 第 3361 行（T-B30a）列出的 15 个分类器特征，顺序同 horizon_classifier.yaml
B30A_FEATURES = (
    "f.amount_20d_avg", "f.turnover_20d_avg", "f.amihud_20d", "f.volatility_20d", "f.intraday_amplitude_20d",
    "f.ma_trend", "f.momentum_60d", "f.roe_ttm", "f.profit_cagr_3y", "f.dividend_continuous_years",
    "f.limit_up_count_20d", "f.fin_report_count", "f.list_days", "f.is_st", "f.is_delisting_period",
)


def _config_dir() -> Path:
    import os

    return Path(os.environ.get("AIA_CONFIG_DIR") or REPO / "config")


def test_classifier_features_are_the_15_b30a_keys() -> None:
    """自检（严格）：仓库 horizon_classifier.yaml 的 ``features`` 恰为 T-B30a 的 15 个键（防止本文件清单过期）。"""
    p = _config_dir() / "horizon_classifier.yaml"
    if not p.is_file():
        pytest.skip(f"{p} 不存在")
    feats = yaml.safe_load(p.read_text(encoding="utf-8")).get("features") or []
    assert tuple(f for f in feats if str(f).startswith("f.")) == B30A_FEATURES


# =============================== 1. 15 个 f.* 进 feature_catalog ===============================
@pytest.mark.xfail(strict=True, reason=O_B30A)
@pytest.mark.parametrize("key", B30A_FEATURES)
def test_b30a_feature_in_catalog(authdb: SimpleNamespace, sql: Callable[..., Any], key: str) -> None:
    """``alembic upgrade head`` 后 feature_catalog 有该键，unit / frequency / pit_rule 不为空、状态可用。"""
    rows = sql("SELECT unit, frequency, pit_rule IS NOT NULL, status FROM app.feature_catalog WHERE feature_key = :k", k=key)
    assert rows, f"feature_catalog 无 {key}"
    unit, freq, has_pit, status = rows[0]
    assert unit and freq and has_pit, (key, unit, freq, has_pit)
    assert status not in {"gap", "deprecated"}, (key, status)


# =============================== 2. 结果落库（真实 snapshot_id） ===============================
@pytest.fixture
def hz(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> SimpleNamespace:
    s = session()
    require_route(s.client, "GET", "/horizon-assessments", _t25d.O_R8)
    code = f"{_uniq_code('600')}.SH"
    _seed_security(sql, code)
    return SimpleNamespace(s=s, call=Rec(s), code=code, uid=str(s.user.id))


def _assessments(sql: Callable[..., Any], uid: str, code: str) -> list[tuple[str, str | None]]:
    return [(r[0], r[1]) for r in sql(
        "SELECT trigger, snapshot_id::text FROM app.symbol_horizon_assessments "
        "WHERE user_id = CAST(:u AS uuid) AND security_code = :c ORDER BY created_at", u=uid, c=code)]


@pytest.mark.xfail(strict=True, reason=O_B30_PERSIST)
def test_b30_result_persisted_with_real_snapshot(hz: SimpleNamespace, sql: Callable[..., Any]) -> None:
    r = _hz(hz.call, hz.code)
    assert r.status_code == 200, r.text[:300]
    sid = str(uuid.UUID(str(r.json()["snapshot_id"])))
    snap = sql("SELECT purpose, user_id::text FROM app.data_snapshots WHERE id = CAST(:i AS uuid)", i=sid)
    assert snap == [("horizon", hz.uid)], snap
    assert ("on_demand", sid) in _assessments(sql, hz.uid, hz.code)


# =============================== 3. 三种重算触发 ===============================
def _trigger_watchlist_add(hz: SimpleNamespace, sql: Callable[..., Any], make_settings: Any, authdb: Any) -> None:
    require_route(hz.s.client, "POST", "/watchlist", O_B30 + "（POST /watchlist 未实现）")
    r = hz.call("POST", "/watchlist", json={"security_code": hz.code, "group": None, "note": None})
    assert r.status_code == 201, r.text[:300]


def _trigger_import(hz: SimpleNamespace, sql: Callable[..., Any], make_settings: Any, authdb: Any) -> None:
    """导入确认：上传 fmt_a 成交样例 → previewed → confirm（只用仓库夹具，不触网）。"""
    require_route(hz.s.client, "POST", "/imports", O_B30 + "（POST /imports 未实现）")
    acc = _account(hz.call)
    data = (REPO / "tests" / "fixtures" / "broker_statements" / "fmt_a" / "trades_sample.txt").read_bytes()
    r = hz.s.client.post(f"{API}/imports", data={"account_id": acc, "kind": "trades"},
                         files={"file": ("trades_sample.txt", data, "text/plain")}, headers={"X-CSRF-Token": hz.s.csrf})
    assert r.status_code == 201, r.text[:300]
    bid = r.json()["batch_id"]
    st = hz.call("GET", f"/imports/{bid}").json()
    assert st["status"] == "previewed", st.get("status")
    c = hz.s.client.post(f"{API}/imports/{bid}/confirm", json={"mode": "valid_rows_only", "acknowledge_warnings": True},
                         headers={"X-CSRF-Token": hz.s.csrf, "Idempotency-Key": str(uuid.uuid4())})
    assert c.status_code == 200, c.text[:300]
    codes = [x[0] for x in sql("SELECT DISTINCT security_code FROM app.trades WHERE account_id = CAST(:a AS uuid)", a=acc)]
    assert codes, "导入后无成交"
    hz.code = codes[0]


def _trigger_weekly(hz: SimpleNamespace, sql: Callable[..., Any], make_settings: Any, authdb: Any) -> None:
    """每周：worker 任务表（app.workers.jobs.TASKS / schedule）有周期评估重算任务，直接执行一次。"""
    jobs = _t25d.backend_module("app.workers.jobs", O_B30)
    names = [n for n in getattr(jobs, "TASKS", {}) if "horizon" in n]
    assert names, f"app.workers.jobs.TASKS 无 horizon 重算任务：{sorted(getattr(jobs, 'TASKS', {}))}"
    acc = _account(hz.call)
    assert _trade(hz.call, acc, hz.code).status_code == 201
    settings = make_settings(database_url=authdb.url)
    assert names[0] in jobs.schedule(settings)
    jobs.TASKS[names[0]](settings)


TRIGGERS = {"import": _trigger_import, "watchlist_add": _trigger_watchlist_add, "weekly": _trigger_weekly}


@pytest.mark.xfail(strict=True, reason=O_B30)
@pytest.mark.parametrize("trigger", sorted(TRIGGERS))
def test_b30_trigger_writes_assessment(hz: SimpleNamespace, sql: Callable[..., Any], make_settings: Any,
                                       authdb: SimpleNamespace, trigger: str) -> None:
    """导入确认 / 加自选 / 每周 → symbol_horizon_assessments 新增一条对应 trigger 的记录，snapshot_id 为真实行。"""
    TRIGGERS[trigger](hz, sql, make_settings, authdb)
    rows = [x for x in _assessments(sql, hz.uid, hz.code) if x[0] == trigger]
    assert rows, (trigger, _assessments(sql, hz.uid, hz.code))
    sid = rows[-1][1]
    assert sid and sql("SELECT purpose FROM app.data_snapshots WHERE id = CAST(:i AS uuid)", i=sid) == [("horizon",)]


# =============================== 4. proposed strategy_instances ===============================
@pytest.mark.xfail(strict=True, reason=O_B30 + "（生成 proposed strategy_instances；确认在 T-B32）")
def test_b30_creates_proposed_strategy_instance(hz: SimpleNamespace, sql: Callable[..., Any]) -> None:
    """分类完成后为该证券生成 status=proposed、origin=classifier、scope=security 的 strategy_instances（不自动激活）。"""
    if has_route(hz.s.client, "POST", "/watchlist"):
        hz.call("POST", "/watchlist", json={"security_code": hz.code, "group": None, "note": None})
    assert _hz(hz.call, hz.code).status_code == 200
    rows = sql("SELECT status, origin, scope FROM app.strategy_instances "
               "WHERE user_id = CAST(:u AS uuid) AND security_code = :c", u=hz.uid, c=hz.code)
    assert rows and all(r[0] == "proposed" and r[1] == "classifier" and r[2] == "security" for r in rows), rows
