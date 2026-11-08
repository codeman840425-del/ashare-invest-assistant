"""T-T25d：架构师裁定 T-B46/T-B47（/workspace/team/reports/T-B46-47-rulings.md）的回归用例。

覆盖：
- R6  持仓 /portfolio：行形状（无 instrument_kind、无顶层 estimated、每行 security_type）、价格来源优先级
  （日线收盘 > 快照参考价 > 无价 → estimated）、cash 缺口与 ``"0.00"``、非空字段、行业缺口不单独致 partial；
  手工 POST /trades 代码归一与 fee_total → other_fee、net_amount null。
- R8  /horizon-assessments：security_code 格式（pattern → 400）与不在主数据（→ 404）、snapshot_id 必须是
  data_snapshots 中 purpose=horizon、带 user_id 的真实行、同输入同记录、trigger=on_demand、T-B30a 前 data_missing 封顶。
- R10 /admin/ingest/status：无（有效）租约 leader 为 null、per_minute_limit 不受 500 行截断影响、queued 最早年龄
  不限 24 小时、freshness 固定 6 行、alerts 列表与级别、告警文案不含证书 / IP / 原因。
- D   data_snapshots 写入方：plan/horizon 必须带 user_id（库级 CHECK）、合规行可写、grants.sql 角色级别
  （只有 api / ingest 可 INSERT，maint 与其他角色被拒）、各写入方逐一验收。
- G-7（T-live-83a031c §8.4）：GET /imports、GET /trades 的 ?account_id= 非本人（他人 / 不存在）→ 404 NOT_FOUND；
- R11 真实后端：/accounts、/imports、/imports/{id}/rows、/trades 的非法 cursor 400 确实触发 schemathesis ST202，
  且 tests/backend/contract/r11_exceptions.py 的例外恰好放行（其余检查照常）。
- E   注册 413 先于 503（closed 模式亦然）：见 test_integration_t_t25c.py::test_reg_closed_oversized_is_413_before_mode。

只用一次性 testcontainers 数据库（authdb）；不连 be-b03a-pg / aia-t01，不调用麦蕊或任何真实行情接口。
尚未实现的条目一律 ``xfail(strict=False)`` 并写明责任人。测试证书值只留在内存，不输出。
"""

from __future__ import annotations

import datetime as dt
import decimal
import importlib.util
import json
import re
import secrets
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("tt25d_cli_t24", _HERE / "test_delete_user_data_cli_t_t24.py")
_t24 = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_t24)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:
    pytest.skip(str(exc), allow_module_level=True)
_t23 = _t24._t23

authdb, sql, app_client, mkuser, session, make_settings = (
    _t23.authdb, _t23.sql, _t23.app_client, _t23.mkuser, _t23.session, _t23.make_settings)
two_licences = _t23.two_licences
API, assert_err, Rec, fake_licence, put = _t23.API, _t23.assert_err, _t23.Rec, _t23.fake_licence, _t23.put
require_route, has_route, set_status, leak_count, backend_module = (
    _t23.require_route, _t23.has_route, _t23.set_status, _t23.leak_count, _t23.backend_module)
REPO = _t23.REPO

pytestmark = [pytest.mark.integration]

# ---- 责任人 ----
O_R6 = "后端 T-B46（/portfolio、手工成交 v0.2.9；c9e1e73 等在本地 main，未推 origin）"
O_R6X = "后端 T-B46-x（裁定 R6）"


#: T-B49（6670b10：/portfolio 按契约 #31、迁移 0017 purpose=horizon + user_scoped CHECK）已在本地 main 落地，
#: 原挂 xfail 的 R6 ×5、D、purpose=horizon 用例改为严格断言；本文件须与 6670b10 一起推送（origin 0cb78ad 上预期失败）。
O_R8 = "后端 T-B47-x（裁定 R8：/horizon-assessments 落库、pattern、purpose=horizon）"
O_R8_B30A = "后端 T-B30a（裁定 R8：f.* 特征落地前全部 data_missing 封顶）"
O_R10 = "后端 T-B47-x（裁定 R10：/admin/ingest/status）"
O_D = "后端 D 项（追加裁定 D：data_snapshots 写入方约束——库级 CHECK 与写入函数断言）"
O_D_COL = "后端 T-B16（迁移 0013：data_snapshots.user_id / licence_id；在本地 main，未推 origin）"
O_GRANTS = "运维 T-O11（deploy/db/roles/grants.sql：在本地 main 07a4e2b，未推 origin）"
O_WRITERS = {
    "plan": "后端 T-B34/T-B36（计划写入方，追加裁定 D）",
    "alert": "后端 T-B38（提醒写入方，追加裁定 D）",
    "review": "后端 T-B40（复盘写入方，追加裁定 D）",
    "screen": "后端 T-B31（选股写入方，追加裁定 D）",
    "horizon": O_R8,
}

PERSONAL_PURPOSES = ("candidate", "plan", "horizon")  # 追加裁定 D（T-O11 补 candidate）：含个人数据，user_id 必填


def _uniq_code(prefix: str = "603") -> str:
    return f"{prefix}{secrets.randbelow(1000):03d}"


def _seed_security(sql: Callable[..., Any], code: str, typ: str = "stock", name: str = "示例证券") -> None:
    sql("INSERT INTO market.securities (code, type, name, exchange, board, listing_status, name_norm) "
        "VALUES (:c, :t, :n, :e, 'main', 'listed', :n) ON CONFLICT (code) DO NOTHING",
        c=code, t=typ, n=name, e=code.rsplit(".", 1)[1])


def _cols(sql: Callable[..., Any], schema: str, table: str) -> set[str]:
    return {r[0] for r in sql("SELECT column_name FROM information_schema.columns "
                              "WHERE table_schema=:s AND table_name=:t", s=schema, t=table)}


def _dec(v: Any) -> decimal.Decimal | None:
    return None if v is None else decimal.Decimal(str(v))


# =============================== R6：持仓 ===============================
TRADE_DAY = dt.date(2026, 10, 30)


def _account(call: Rec) -> str:
    r = call("POST", "/accounts", json={"alias": f"测试账户{secrets.token_hex(2)}", "broker_name": "示例券商"})
    assert r.status_code == 201, r.text[:300]
    return str(r.json()["id"])


def _trade(call: Rec, acc: str, code: str, qty: int | str = 100, price: str = "10.00", fee: str | None = "5.00") -> Any:
    # 评审 d018fad M3：契约 v0.2.9 R11 #9（后端 9e693b2）qty/price 为 string(decimal)，一律按字符串发送
    body: dict[str, Any] = {"account_id": acc, "trade_date": TRADE_DAY.isoformat(), "security_code": code,
                            "side": "buy", "qty": str(qty), "price": str(price)}
    if fee is not None:
        body["fee_total"] = fee
    return call("POST", "/trades", json=body)


def _portfolio(call: Rec, acc: str) -> dict[str, Any]:
    r = call("GET", f"/portfolio?account_id={acc}")
    assert r.status_code == 200, r.text[:300]
    return r.json()


def _rows(p: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["security_code"]: r for r in p["positions"]}


def _gaps(p: dict[str, Any]) -> set[tuple[str, str]]:
    return {(g.get("key"), g.get("reason")) for g in p.get("gaps") or []}


@pytest.fixture
def pf(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> SimpleNamespace:
    """手工成交账户：A（主数据内、有日线）、B（主数据内、无日线无快照）、CB（可转债，不在主数据）。"""
    s = session()
    call = Rec(s)
    require_route(s.client, "GET", "/portfolio", O_R6)
    require_route(s.client, "POST", "/trades", O_R6)
    n = _uniq_code()
    a, b = f"{n[:3]}{n[3:]}", _uniq_code("605")
    while b == a:
        b = _uniq_code("605")
    _seed_security(sql, f"{a}.SH")
    _seed_security(sql, f"{b}.SH")
    sql("INSERT INTO market.daily_bars (code, trade_date, open, high, low, close) "
        "VALUES (:c, :d, 12, 13, 11, 12.34) ON CONFLICT DO NOTHING", c=f"{a}.SH", d=TRADE_DAY)
    cb = f"113{secrets.randbelow(1000):03d}"
    acc = _account(call)
    for code in (f"SH{a}", f"SH{b}", f"SH{cb}"):
        r = _trade(call, acc, code)
        assert r.status_code == 201, (code, r.text[:300])
    return SimpleNamespace(s=s, call=call, acc=acc, a=f"{a}.SH", b=f"{b}.SH", cb=f"{cb}.SH")


def test_r6_manual_trade_code_and_fee(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    """R6（手工成交）：SH600xxx → 600xxx.SH；fee_total 写入 other_fee；手工成交 net_amount 为 null。"""
    s = session()
    call = Rec(s)
    require_route(s.client, "POST", "/trades", O_R6)
    code = _uniq_code("600")
    _seed_security(sql, f"{code}.SH")
    acc = _account(call)
    r = _trade(call, acc, f"SH{code}", fee="5.20")
    assert r.status_code == 201, r.text[:300]
    t = r.json()
    assert t["security_code"] == f"{code}.SH"
    assert t["net_amount"] is None
    assert _dec(t["fee_total"]) == decimal.Decimal("5.20")
    (fee,) = sql("SELECT other_fee FROM app.trades WHERE id=:i", i=t["id"])[0]
    assert _dec(fee) == decimal.Decimal("5.20")


def test_r6_row_shape(pf: SimpleNamespace) -> None:
    """R6：无顶层 estimated、行无 instrument_kind、每行有 security_type；不在主数据 → security_type null。"""
    p = _portfolio(pf.call, pf.acc)
    assert "estimated" not in p
    rows = _rows(p)
    assert set(rows) >= {pf.a, pf.b, pf.cb}, sorted(rows)
    for row in rows.values():
        assert "instrument_kind" not in row
        assert "security_type" in row and isinstance(row["estimated"], bool)
        assert row["security_type"] in ("stock", "cdr", "etf", None)
    assert rows[pf.a]["security_type"] == "stock"
    assert rows[pf.cb]["security_type"] is None


def test_r6_no_price_is_estimated_with_null_values(pf: SimpleNamespace) -> None:
    """R6：无日线、无快照参考价 → estimated=true，market_value / pnl / pnl_pct 为 null。"""
    rows = _rows(_portfolio(pf.call, pf.acc))
    for code in (pf.b, pf.cb):
        row = rows[code]
        assert row["estimated"] is True
        assert row["market_value"] is None and row["pnl"] is None and row["pnl_pct"] is None


def test_r6_cash_gap_and_sector_gap(pf: SimpleNamespace) -> None:
    """R6：无现金记录 → gaps 含 (cash, user_input_missing)；行业暴露为 [] 并有 exposure.sector 缺口。"""
    p = _portfolio(pf.call, pf.acc)
    g = _gaps(p)
    assert ("cash", "user_input_missing") in g, sorted(g)
    assert p["exposure"]["sector"] == []
    assert any(f == "exposure.sector" for f, _ in g), sorted(g)


def test_r6_cash_zero_string(pf: SimpleNamespace) -> None:
    p = _portfolio(pf.call, pf.acc)
    assert p["cash"] == "0.00"


def test_r6_non_null_fields(pf: SimpleNamespace) -> None:
    p = _portfolio(pf.call, pf.acc)
    assert p["cash"] is not None and p["total_assets"] is not None
    for row in p["positions"]:
        assert row["cost_price"] is not None and row["weight_pct"] is not None, row["security_code"]


def test_r6_daily_close_priority(pf: SimpleNamespace) -> None:
    row = _rows(_portfolio(pf.call, pf.acc))[pf.a]
    assert row["estimated"] is False
    assert _dec(row["market_value"]) == decimal.Decimal("12.34") * _dec(row["qty"])


def _snapshot_account(call: Rec, sql: Callable[..., Any], user_id: str, items: list[tuple[str, int, str, str]],
                      cash: str | None = "1000.00") -> str:
    """只有一份已提交的券商持仓快照的账户（SQL 直写；无成交流水）。items: (代码, 数量, 成本价, 参考价)。"""
    acc = _account(call)
    batch = str(uuid.uuid4())
    snap = str(uuid.uuid4())
    sql("INSERT INTO app.import_batches (id, user_id, account_id, kind, status, committed_at) "
        "VALUES (:i, :u, :a, 'positions', 'committed', now())", i=batch, u=user_id, a=acc)
    sql("INSERT INTO app.broker_position_snapshots (id, account_id, import_batch_id, as_of, cash_balance, version_no) "
        "VALUES (:i, :a, :b, now() - interval '1 day', :c, 1)", i=snap, a=acc, b=batch, c=cash)
    for code, qty, cost, ref in items:
        sql("INSERT INTO app.broker_position_snapshot_items (snapshot_id, security_code, quantity, sellable_quantity, "
            "broker_cost_price, last_price_ref) VALUES (:s, :c, :q, :q, :p, :r)", s=snap, c=code, q=qty, p=cost, r=ref)
    return acc


def _snap_ctx(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> SimpleNamespace:
    s = session()
    call = Rec(s)
    require_route(s.client, "GET", "/portfolio", O_R6)
    need = {"import_batch_id", "version_no", "cash_balance"}
    if not need <= _cols(sql, "app", "broker_position_snapshots"):
        pytest.xfail(f"{O_R6}：broker_position_snapshots 缺列")
    return SimpleNamespace(s=s, call=call)


def test_r6_snapshot_reference_price_used(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    """R6：无日线时用快照参考价 → estimated=false，市值=参考价×数量。"""
    c = _snap_ctx(session, sql)
    code = f"{_uniq_code('601')}.SH"
    _seed_security(sql, code)
    acc = _snapshot_account(c.call, sql, str(c.s.user.id), [(code, 100, "10.00", "11.00")])
    row = _rows(_portfolio(c.call, acc))[code]
    assert row["estimated"] is False
    assert _dec(row["market_value"]) == decimal.Decimal("1100")


def test_r6_daily_close_beats_snapshot(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    c = _snap_ctx(session, sql)
    code = f"{_uniq_code('601')}.SH"
    _seed_security(sql, code)
    sql("INSERT INTO market.daily_bars (code, trade_date, open, high, low, close) VALUES (:c, :d, 12, 13, 11, 12.34) "
        "ON CONFLICT DO NOTHING", c=code, d=TRADE_DAY)
    acc = _snapshot_account(c.call, sql, str(c.s.user.id), [(code, 100, "10.00", "11.00")])
    row = _rows(_portfolio(c.call, acc))[code]
    assert _dec(row["market_value"]) == decimal.Decimal("1234")


def test_r6_sector_gap_alone_is_not_partial(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    c = _snap_ctx(session, sql)
    code = f"{_uniq_code('601')}.SH"
    _seed_security(sql, code)
    acc = _snapshot_account(c.call, sql, str(c.s.user.id), [(code, 100, "10.00", "11.00")])
    p = _portfolio(c.call, acc)
    assert {f for f, _ in _gaps(p)} == {"exposure.sector"}, sorted(_gaps(p))
    assert p["data_status"] != "partial"


def test_r6_not_in_master_snapshot_priced(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    """T-T25 裁定 #6（docs 46538a6 契约 §7.2 /portfolio、#32 ②）：不在主数据中（security_type=null）的行即使快照里
    有参考价也**不**采用，一律按成本估算：estimated=true，market_value/pnl/pnl_pct 为 null，weight_pct 按成本
    qty×cost_price（total_assets 同样计入成本估算值），gaps 含 positions.convertible_bond（113xxx 属可转债段），
    顶层 data_status=partial。"""
    c = _snap_ctx(session, sql)
    code = f"113{secrets.randbelow(1000):03d}.SH"
    acc = _snapshot_account(c.call, sql, str(c.s.user.id), [(code, 10, "100.00", "101.00")])
    p = _portfolio(c.call, acc)
    row = _rows(p)[code]
    assert row["security_type"] is None
    if row["estimated"] is False or row["market_value"] is not None:
        pytest.xfail(f"{O_R6X}：T-T25 裁定 #6——security_type=null 的行仍采用了快照参考价"
                     f"（estimated={row['estimated']}，market_value={row['market_value']}）")
    assert row["estimated"] is True
    assert row["market_value"] is None and row["pnl"] is None and row["pnl_pct"] is None
    cost = decimal.Decimal(10) * decimal.Decimal("100.00")
    total = _dec(p["total_assets"])
    assert total == _dec(p["cash"]) + cost, (p["total_assets"], p["cash"])
    assert abs(_dec(row["weight_pct"]) - cost / total * 100) < decimal.Decimal("0.01"), row["weight_pct"]
    assert ("positions.convertible_bond", "no_source") in _gaps(p), sorted(_gaps(p))
    assert p["data_status"] == "partial"


# =============================== R8：/horizon-assessments ===============================
def _hz(call: Rec, code: str) -> Any:
    return call("GET", f"/horizon-assessments?security_code={code}")


@pytest.fixture
def hz(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> SimpleNamespace:
    s = session()
    require_route(s.client, "GET", "/horizon-assessments", O_R8)
    code = f"{_uniq_code('600')}.SH"
    _seed_security(sql, code)
    return SimpleNamespace(s=s, call=Rec(s), code=code)


def test_r8_malformed_code_is_400(hz: SimpleNamespace) -> None:
    """R8：15 位数字等格式非法的代码 → 400（不是 404 / 500）。"""
    r = _hz(hz.call, "1" * 15)
    assert r.status_code == 400, r.text[:300]


# 评审 d018fad m1：9e693b2 已给 security_code 加 pattern，稳定通过 → 严格（origin 无该路由时由 hz 的 require_route 运行时 xfail）
def test_r8_openapi_has_pattern(hz: SimpleNamespace) -> None:
    spec = hz.s.client.get(f"{API}/openapi.json").json()
    params = spec["paths"][f"{API}/horizon-assessments"]["get"]["parameters"]
    p = next(x for x in params if x["name"] == "security_code")
    assert p["schema"].get("pattern"), p


@pytest.mark.xfail(strict=False, reason=f"{O_R8}：格式合法但不在主数据（或推断不出市场）→ 404，本地 main 照常分类返回 200")
@pytest.mark.parametrize("code", ["600999.SH", "999999"])
def test_r8_unknown_code_is_404(hz: SimpleNamespace, sql: Callable[..., Any], code: str) -> None:
    sql("DELETE FROM market.securities WHERE code = :c AND name = '__never__'", c=code)  # 不删任何已有行
    if sql("SELECT 1 FROM market.securities WHERE code = :c", c=code):
        pytest.skip("该代码已被其他用例写入主数据")
    r = _hz(hz.call, code)
    assert r.status_code == 404, r.text[:300]


def test_r8_known_code_ok_and_data_missing_cap(hz: SimpleNamespace) -> None:
    """R8：主数据内的代码 → 200；T-B30a 之前 f.* 特征缺失 → caps 含 kind=data_missing（预期行为）。"""
    r = _hz(hz.call, hz.code)
    assert r.status_code == 200, r.text[:300]
    caps = r.json()["caps"]
    if not any(c.get("kind") == "data_missing" for c in caps):
        pytest.xfail(f"{O_R8_B30A}：caps={json.dumps(caps, ensure_ascii=False)[:200]}")


@pytest.mark.xfail(strict=False, reason=f"{O_R8}：snapshot_id 应是 data_snapshots 中 purpose=horizon、user_id=本人的真实行，本地 main 为哈希")
def test_r8_snapshot_is_persisted_row(hz: SimpleNamespace, sql: Callable[..., Any]) -> None:
    sid = _hz(hz.call, hz.code).json()["snapshot_id"]
    uuid.UUID(str(sid))
    row = sql("SELECT purpose, user_id::text FROM app.data_snapshots WHERE id = CAST(:i AS uuid)", i=sid)
    assert row and row[0][0] == "horizon" and row[0][1] == str(hz.s.user.id)


@pytest.mark.xfail(strict=False, reason=f"{O_R8}：同一输入两次请求应复用同一条评估记录（symbol_horizon_assessments，trigger=on_demand）")
def test_r8_same_input_same_record(hz: SimpleNamespace, sql: Callable[..., Any]) -> None:
    a = _hz(hz.call, hz.code).json()["snapshot_id"]
    b = _hz(hz.call, hz.code).json()["snapshot_id"]
    assert a == b
    rows = sql("SELECT trigger, snapshot_id::text FROM app.symbol_horizon_assessments WHERE user_id = :u AND security_code = :c",
               u=hz.s.user.id, c=hz.code)
    assert len(rows) == 1 and rows[0][0] == "on_demand" and rows[0][1] == str(a)


# =============================== R10：/admin/ingest/status ===============================
FRESHNESS_DATASETS = ["quotes", "minute_bars", "daily_bars", "financials", "announcements", "security_master"]


def _status(tl: SimpleNamespace) -> dict[str, Any]:
    require_route(tl.admin.client, "GET", "/admin/ingest/status", _t23.O_INGEST_STATUS)
    r = tl.acall("GET", "/admin/ingest/status")
    assert r.status_code == 200, r.text[:300]
    return r.json()


def test_r10_budget_is_sum_of_active(two_licences: SimpleNamespace) -> None:
    """R10：budget.per_minute_limit = 全部 active 证书的每分钟上限之和（未截断时）。"""
    st = _status(two_licences)
    assert st["budget"]["per_minute_limit"] == sum(
        int(r["per_minute_limit"]) for r in st["licences"] if r["status"] == "active")


@pytest.mark.xfail(strict=False, reason=f"{O_R10}：per_minute_limit 必须在截断前汇总（licences 500 行上限不影响预算）")
def test_r10_budget_not_affected_by_truncation(two_licences: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    full = _status(two_licences)["budget"]["per_minute_limit"]
    assert full > 0
    svc = backend_module("app.licences.service", O_R10)
    monkeypatch.setattr(svc, "INGEST_LICENCES_MAX", 1)  # quota_exceeded 排在 active 前 → active 行被截掉
    st = _status(two_licences)
    assert st["licences_truncated"] is True
    assert st["budget"]["per_minute_limit"] == full


@pytest.mark.xfail(strict=False, reason=f"{O_R10}：无租约（或租约已过期）时 leader 应为 null，本地 main 返回全 null 字段的对象")
def test_r10_leader_null_without_live_lease(two_licences: SimpleNamespace, sql: Callable[..., Any]) -> None:
    sql("INSERT INTO ops.ingest_leases (holder_host, egress_ip, started_at, last_renewed_at) "
        "VALUES ('tt25d-stale', '203.0.113.77', now() - interval '3 days', now() - interval '3 days')")
    try:
        assert _status(two_licences)["leader"] is None
    finally:
        sql("DELETE FROM ops.ingest_leases WHERE holder_host = 'tt25d-stale'")


@pytest.mark.xfail(strict=False, reason=f"{O_R10}：queues[].oldest_age_s 不应只回看 24 小时")
def test_r10_oldest_queued_no_lookback_limit(two_licences: SimpleNamespace, sql: Callable[..., Any]) -> None:
    sql("INSERT INTO ops.ingest_request_log (requested_at, requester, priority, endpoint_key, status) "
        "VALUES (now() - interval '2 days', 'tt25d', 'P2', 'tt25d', 'queued')")
    try:
        q = {x["priority"]: x for x in _status(two_licences)["queues"]}
        assert q["p2_backfill"]["oldest_age_s"] >= 2 * 86400 - 60
    finally:
        sql("DELETE FROM ops.ingest_request_log WHERE requester = 'tt25d'")


@pytest.mark.xfail(strict=False, reason=f"{O_R10}：freshness 固定 6 行（quotes、minute_bars、daily_bars、financials、announcements、security_master），本地 main 为 []")
def test_r10_freshness_six_rows(two_licences: SimpleNamespace) -> None:
    fr = _status(two_licences)["freshness"]
    assert sorted(x["dataset"] for x in fr) == sorted(FRESHNESS_DATASETS)


@pytest.mark.xfail(strict=False, reason=f"{O_R10}：alerts 必须是列表（无告警为 []，不为 null / 缺省）")
def test_r10_alerts_is_list(two_licences: SimpleNamespace) -> None:
    assert isinstance(_status(two_licences)["alerts"], list)


@pytest.mark.xfail(strict=False, reason=f"{O_R10}：invalid 证书 → critical 告警；告警文案不含证书、IP、暂停原因")
def test_r10_invalid_licence_is_critical_and_redacted(two_licences: SimpleNamespace, sql: Callable[..., Any]) -> None:
    tl = two_licences
    set_status(sql, tl.a.user.id, "invalid")
    sql("INSERT INTO ops.ingest_leases (holder_host, egress_ip) VALUES ('tt25d-live', '203.0.113.77')")
    try:
        alerts = _status(tl)["alerts"]
        assert any(a.get("level") == "critical" for a in alerts), alerts
        blob = json.dumps(alerts, ensure_ascii=False)
        assert "203.0.113.77" not in blob and "203.0.113" not in blob
        for lic in (tl.la, tl.lb):
            assert leak_count(lic, blob) == 0
    finally:
        sql("DELETE FROM ops.ingest_leases WHERE holder_host = 'tt25d-live'")


# =============================== D：data_snapshots 写入方 ===============================
def _need_user_col(sql: Callable[..., Any]) -> None:
    if "user_id" not in _cols(sql, "app", "data_snapshots"):
        pytest.xfail(f"{O_D_COL}：data_snapshots 没有 user_id 列")


def _insert_snapshot(conn_exec: Callable[..., Any], purpose: str, user_id: Any) -> None:
    conn_exec("INSERT INTO app.data_snapshots (purpose, items, hash, user_id) "
              "VALUES (:p, CAST('[]' AS jsonb), :h, :u)", p=purpose, h=secrets.token_hex(16), u=user_id)


def _sqlstate(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", exc)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def _constraint(exc: BaseException) -> str | None:
    diag = getattr(getattr(exc, "orig", exc), "diag", None)
    return getattr(diag, "constraint_name", None)


def test_d_compliant_rows_accepted(sql: Callable[..., Any], mkuser: Callable[..., Any]) -> None:
    """D：带 user_id 的 plan 行、市场级 screen 行（user_id null）均可写入。"""
    _need_user_col(sql)
    u = mkuser()
    _insert_snapshot(sql, "plan", u.id)
    _insert_snapshot(sql, "screen", None)


@pytest.mark.parametrize("purpose", PERSONAL_PURPOSES)
def test_d_personal_purpose_requires_user(sql: Callable[..., Any], purpose: str) -> None:
    _need_user_col(sql)
    with pytest.raises(Exception) as ei:
        _insert_snapshot(sql, purpose, None)
    assert _sqlstate(ei.value) == "23514"
    # 被 purpose 枚举 CHECK 拒绝（horizon 尚不是合法 purpose）不算：必须是 user_id 约束
    assert _constraint(ei.value) != "ck_data_snapshots_purpose", _constraint(ei.value)


def test_d_horizon_purpose_allowed(sql: Callable[..., Any], mkuser: Callable[..., Any]) -> None:
    _need_user_col(sql)
    _insert_snapshot(sql, "horizon", mkuser().id)


def test_d_snapshot_rows_are_immutable(sql: Callable[..., Any], mkuser: Callable[..., Any]) -> None:
    """D：已写入的快照不可改（只追加）。"""
    _need_user_col(sql)
    u = mkuser()
    h = secrets.token_hex(16)
    sql("INSERT INTO app.data_snapshots (purpose, items, hash, user_id) VALUES ('plan', CAST('[]' AS jsonb), :h, :u)",
        h=h, u=u.id)
    with pytest.raises(Exception):
        sql("UPDATE app.data_snapshots SET hash = 'x' WHERE hash = :h", h=h)


GRANTS = REPO / "deploy" / "db" / "roles" / "grants.sql"
_ROLE_MAP = {"aia_api": "tt25d_api", "aia_ingest": "tt25d_ingest", "aia_maint": "tt25d_maint"}


@pytest.fixture(scope="module")
def grant_roles(authdb: SimpleNamespace) -> SimpleNamespace:
    """把 grants.sql（角色名换成 tt25d_*，口令换成随机值，去掉 psql 元命令）应用到一次性测试库。
    不改动 aia_* 角色本身，不影响 t24 的 aia_maint 近似角色。"""
    if not GRANTS.is_file():
        pytest.xfail(f"{O_GRANTS}：工作树没有 grants.sql")
    import psycopg

    src = GRANTS.read_text(encoding="utf-8")
    src = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("\\"))
    for var in ("api_pw", "ingest_pw", "maint_pw"):
        src = src.replace(f":'{var}'", f"'{secrets.token_hex(16)}'")
    for old, new in _ROLE_MAP.items():
        src = re.sub(rf"\b{old}\b", new, src)
    with psycopg.connect(authdb.url, autocommit=True) as c:
        c.execute(src)  # type: ignore[arg-type]
        exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname = 'tt25d_nobody'").fetchone()
        if not exists:
            c.execute("CREATE ROLE tt25d_nobody NOLOGIN")
    return SimpleNamespace(url=authdb.url, **{k.split("_")[1]: v for k, v in _ROLE_MAP.items()}, nobody="tt25d_nobody")


def _as_role(url: str, role: str, stmt: str, params: tuple[Any, ...]) -> str | None:
    """以 SET ROLE 身份执行；返回 SQLSTATE（成功为 None，并回滚）。"""
    import psycopg

    with psycopg.connect(url) as c:
        c.execute(f"SET ROLE {role}")
        try:
            c.execute(stmt, params)  # type: ignore[arg-type]
        except psycopg.Error as exc:
            return exc.sqlstate
        finally:
            c.rollback()
    return None


_INS = "INSERT INTO app.data_snapshots (purpose, items, hash, user_id) VALUES ('plan', '[]'::jsonb, %s, %s)"


def test_d_grants_who_may_insert(grant_roles: SimpleNamespace, sql: Callable[..., Any],
                                 mkuser: Callable[..., Any]) -> None:
    """D（角色级别，按 grants.sql）：api / ingest 可 INSERT data_snapshots；maint 与无授权角色 → 42501。"""
    _need_user_col(sql)
    uid = str(mkuser().id)
    for role in (grant_roles.api, grant_roles.ingest):
        assert _as_role(grant_roles.url, role, _INS, (secrets.token_hex(16), uid)) is None, role
    for role in (grant_roles.maint, grant_roles.nobody):
        assert _as_role(grant_roles.url, role, _INS, (secrets.token_hex(16), uid)) == "42501", role


@pytest.mark.parametrize("purpose", sorted(O_WRITERS))
def test_d_writer_sets_user_id(purpose: str) -> None:
    """D（写入方逐一验收）：candidate 已由 test_contract_t_a11_t_f22.py::test_a11_09 覆盖（user_id=本人）。
    其余写入方的端点 / 写入函数尚未落地，验收待对应任务：写入后断言 user_id=本人、licence_id 合规。"""
    pytest.xfail(f"{O_WRITERS[purpose]}：尚无 {purpose} 快照写入方")


# =============================== R11：真实后端 + 例外登记 ===============================
def _r11() -> Any:
    spec = importlib.util.spec_from_file_location("tt25d_r11", _HERE.parent / "contract" / "r11_exceptions.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass 需要模块已登记
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


R11_GETS = ["/api/v1/accounts", "/api/v1/imports", "/api/v1/imports/{batch_id}/rows", "/api/v1/trades"]


@pytest.mark.parametrize("path", R11_GETS)
def test_r11_real_backend_invalid_cursor(path: str, session: Callable[..., SimpleNamespace],
                                         sql: Callable[..., Any]) -> None:
    """R11 #1/#3/#4/#5（真实后端，进程内 ASGI）：非法 cursor → 400 INVALID_CURSOR；不加例外时 schemathesis
    报 ST202（positive_data_acceptance），加 r11_exceptions 后通过，其他检查照常。"""
    schemathesis = pytest.importorskip("schemathesis")
    from hypothesis import HealthCheck, given, settings

    r11 = _r11()
    s = session()
    app = s.client.app
    if not has_route(s.client, "GET", path.removeprefix(API)):
        pytest.xfail(f"{O_R6}：{path} 未挂载")
    schema = schemathesis.openapi.from_asgi(f"{API}/openapi.json", app)
    op = schema[path]["GET"]
    # limit 固定为合法值：limit > 200 → 400 VALIDATION_ERROR 而 OpenAPI 未声明 maximum，不属 R11 #1/3/4/5（另报后端）
    fixed: dict[str, Any] = {"query": {"cursor": "!!not-a-cursor!!", "limit": 20}}
    if "{batch_id}" in path:
        acc = _account(Rec(s))
        bid = str(uuid.uuid4())
        sql("INSERT INTO app.import_batches (id, user_id, account_id, kind, status) VALUES (:i, :u, :a, 'trades', 'committed')",
            i=bid, u=s.user.id, a=acc)
        fixed["path_parameters"] = {"batch_id": bid}
    cookie = "; ".join(f"{k}={v}" for k, v in s.client.cookies.items())
    seen: list[Any] = []

    @given(case=op.as_strategy(**fixed))
    @settings(max_examples=5, deadline=None, database=None, derandomize=True,
              suppress_health_check=list(HealthCheck))
    def run(case: Any) -> None:
        case.headers = {**(case.headers or {}), "Cookie": cookie}
        resp = case.call()
        if resp.status_code != 400:
            return
        assert r11.error_code(resp.content) == "INVALID_CURSOR", resp.text[:200]
        with pytest.raises(BaseException) as ei:  # FailureGroup 是 BaseExceptionGroup
            case.validate_response(resp, checks=[r11.CHECK])
        assert "RejectedPositiveData" in repr(ei.value.exceptions if hasattr(ei.value, "exceptions") else ei.value)
        case.validate_response(resp, excluded_checks=r11.excluded_checks(case, resp))
        seen.append(resp.status_code)

    run()
    assert seen, "没有生成到返回 400 的用例"


# ============ G-7（T-live-83a031c §8.4，G-7.md）：列表 ?account_id= 非本人账户 → 404 ============
O_G7 = "后端 G-7（ab84776：list_imports / list_trades 带 account_id 时先 owned_account；在本地 main，未推 origin）"


@pytest.mark.parametrize("path", ["/imports", "/trades"])
def test_g7_list_with_unowned_account_id_is_404(session: Callable[..., SimpleNamespace], path: str) -> None:
    """契约 §7.5/§7.6（v0.2.9 #27 ⑦）：B 用 A 的账户或不存在的账户 id 查列表 → 404 NOT_FOUND，不返回 items，
    错误体与 /portfolio 的同类 404 同形（不区分“他人”与“不存在”）；A 查本人账户与不带 account_id → 200。"""
    a, b = session(), session()
    require_route(a.client, "GET", path, O_G7)
    ca, cb = Rec(a), Rec(b)
    acc = _account(ca)
    assert ca("GET", f"{path}?account_id={acc}").status_code == 200
    assert cb("GET", path).status_code == 200
    ref = cb("GET", f"/portfolio?account_id={acc}")
    for aid in (acc, str(uuid.uuid4())):
        r = cb("GET", f"{path}?account_id={aid}")
        if r.status_code == 200:
            pytest.xfail(f"{O_G7}：他人/不存在账户返回 200 + 空列表")
        assert_err(r, 404, "NOT_FOUND")
        assert "items" not in r.json()
        if ref.status_code == 404:
            assert set(r.json()["error"]) == set(ref.json()["error"])
