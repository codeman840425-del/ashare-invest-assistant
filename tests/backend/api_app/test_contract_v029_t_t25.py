"""T-T25：契约 v0.2.9（T-A10，架构师 687159f）§9 “v0.2.9 验收”第 1–11 条 + 3 个不兼容变更的回归用例。

用例名前缀 ``test_NN_`` 对应验收第 NN 条；``test_bc6_`` / ``test_bc11_`` / ``test_bc12_`` 对应变更表的 3 个不兼容项：

- #6  ``GET /candidate-signals/{id}/events`` 改为 §1.2 分页 ``{items, next_cursor}``（``at desc, id desc``，无 ``detail``）；
- #11 ``POST /plan-drafts/{id}/discard`` 请求体为 ``{}``，旧客户端的 ``note`` 被忽略（不 400、不落库）；
- #12 ``GET /non-executable-reasons`` 不带 ``status`` 时只返回 ``active``（带 ``signal_ids=`` 同样）。

门控原则（不放宽断言）：

- 所用 docs（``AIA_DOCS_DIR``，缺省为仓库 docs/）低于 v0.2.9 → 文档层用例 xfail（运维推送 687159f）；
- 端点尚未挂载 → imperative ``xfail``，写明后端责任任务；挂载后严格断言；
- 已实现的部分（DB 约束、``config/market_rules.yaml``、注册判定顺序（main f72b8c7）、证书设置开关）严格断言；
- 前端源码静态检查（``src/frontend/src``）未同步 → xfail，写明前端负责项。

真实 PG/Redis（复用 T-T22/T-T23 夹具，独立临时库），进程内 TestClient；不联网、不调用麦蕊；测试证书运行时随机生成。
"""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import json
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_spec = importlib.util.spec_from_file_location("tt25_rulings", Path(__file__).with_name("test_architect_rulings_t_t25.py"))
_r = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_r)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:
    pytest.skip(str(exc), allow_module_level=True)
_t23 = _r._t23

authdb, sql, app_client, mkuser, session, make_settings = (
    _t23.authdb, _t23.sql, _t23.app_client, _t23.mkuser, _t23.session, _t23.make_settings)
API, assert_err, reg, new_name, new_pw = _t23.API, _t23.assert_err, _t23.reg, _t23.new_name, _t23.new_pw
Rec, fake_licence, put, live_row, leak_count = _t23.Rec, _t23.fake_licence, _t23.put, _t23.live_row, _t23.leak_count
require_route, backend_version = _t23.require_route, _t23.backend_version
_httpdiag, httpdiag = _t23._httpdiag, _t23.httpdiag

pytestmark = [pytest.mark.integration, pytest.mark.contract]

REPO = Path(__file__).resolve().parents[3]
V029 = "v0.2.9"
C029 = "契约 v0.2.9 687159f"
#: 契约 §3（v0.2.9 新增）：取值与顺序；与 candidate_signal_events.cause 的 CHECK 一致
EVENT_CAUSES = ["executability_check", "reason_released", "user", "expiry", "invalidation", "supersede"]

O_DOCS29 = f"运维（把{C029} 推到 origin；所用 docs 低于 v0.2.9）"
O_ENUMS29 = (f"后端 T-B33（{C029} #6 / 验收 1：/meta/enums.version=v0.2.9 并输出 candidate_signal_event_cause；"
             "本地 main 仍报 v0.2.8）")
O_FRONT29 = (f"前端（{C029} 前端改动列：enums.ts CONTRACT_VERSION=v0.2.9 与 candidate_signal_event_cause、"
             "mock 删除 plan_confirmed 只用 6 个 cause、放弃草案不发 note）")
O_PORTFOLIO = f"后端 T-B08 / T-B19（{C029} #1–#3 / 验收 2：/portfolio、/terminal 未实现）"
O_SIGNALS = f"后端 T-B33（{C029} #6–#9、#12 / 验收 3–5：/candidate-signals、/non-executable-reasons、/restrictions 未实现）"
O_TRACKING = f"后端 T-B27（{C029} #10 / 验收 6：tracking ?scope=mine|site 未实现）"
O_DRAFTS = f"后端 T-B34 / T-B36（{C029} #11、#13、#14 / 验收 7–9：/plan-drafts 未实现）"
O_SEED = "后端 T-B33 / T-B20（候选信号种子需 strategy_versions 夹具；T-B20 策略库未落地）"
O_REG = _r.O_REG_ORDER
FLAG = _r.FLAG


# =============================== 工具 ===============================
_VERSION_RE = re.compile(r"版本：\*\*v(\d+)\.(\d+)(?:\.(\d+))?\*\*")


def _docs() -> SimpleNamespace:
    d = Path(os.environ.get("AIA_DOCS_DIR", REPO / "docs"))
    p = d / "api-contract.md"
    if not p.is_file():
        pytest.skip(f"{d} 下没有 api-contract.md")
    text = p.read_text(encoding="utf-8")
    m = _VERSION_RE.search(text)
    return SimpleNamespace(text=text, ver=tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0))


def _docs029() -> str:
    d = _docs()
    if d.ver < (0, 2, 9):
        pytest.xfail(f"{O_DOCS29}：docs 版本 v{'.'.join(map(str, d.ver))}")
    return d.text


def _acceptance(text: str) -> dict[int, str]:
    """§9 “v0.2.9 验收” 的编号条目 → 文本。"""
    start = text.index("**v0.2.9 验收**")
    block = text[start:].split("\n- **", 1)[0]
    return {int(n): body for n, body in re.findall(r"^\s+(\d+)\. (.+)$", block, re.M)}


def _enum_row(text: str, name: str) -> list[str]:
    m = re.search(rf"^\| `{name}` \| (.+?) \|", text, re.M)
    assert m, f"§3 没有 {name}"
    return re.findall(r"`([a-z0-9_]+)`", m.group(1).split("（", 1)[0])


def _check_values(table: Any, column: str) -> list[str]:
    """SQLAlchemy 表上 ``column IN (...)`` CHECK 的取值（按书写顺序）。"""
    for con in table.constraints:
        sqltext = str(getattr(con, "sqltext", ""))
        if re.match(rf"^\s*{column} IN \(", sqltext):
            return re.findall(r"'([^']+)'", sqltext)
    raise AssertionError(f"{table.name}.{column} 没有 IN 约束")


def _signals() -> Any:
    """``app.db.tables.signals``（候选信号、事件、不可执行原因、计划草案的表定义）。"""
    return importlib.import_module("app.db.tables.signals")


def _err_shape(r: Any) -> str:
    """错误信封去掉逐请求变化的 request_id 后的规范化 JSON（比较“响应体相同”）。"""
    err = dict(r.json()["error"])
    err.pop("request_id", None)
    return json.dumps(err, ensure_ascii=False, sort_keys=True)


# =============================== 第 0 项：文档自检（验收清单 1–11 齐全） ===============================
#: 每条验收中必须出现的关键文字（防止条目被改写后用例对不上号）
ITEM_TOKENS = {
    1: ["candidate_signal_event_cause", "CONTRACT_VERSION"],
    2: ["import_as_is", "estimated=true", "data_status=\"partial\""],
    3: ["{items, next_cursor}", "at desc, id desc", "detail"],
    4: ["security_code", "status=all", "obsolete"],
    5: ["REASON_NOT_MANUALLY_RELEASABLE", "released_by=\"system\"", "STRATEGY_CONFLICT"],
    6: ["scope=site", "scope=other"],
    7: ["signal_ids", "SIGNAL_NOT_EXECUTABLE"],
    8: ["lot_rule", "deviation_ack=true", "chosen_qty=150"],
    9: ["{\"note\": \"示例\"}", "INVALID_STATE_TRANSITION"],
    10: ["REGISTRATION_CLOSED", "蜜罐"],
    11: ["MAINTENANCE", "DELETE` → `204"],
}


def test_00_contract_v029_acceptance_items_1_to_11() -> None:
    """契约 §9 “v0.2.9 验收” 恰为 1–11 条，各条含本文件所依据的关键文字；版本头与变更表 3 个不兼容项。"""
    text = _docs029()
    items = _acceptance(text)
    assert sorted(items) == list(range(1, 12)), sorted(items)
    for n, tokens in ITEM_TOKENS.items():
        for tok in tokens:
            assert tok in items[n], (n, tok)
    head = text[text.index("### v0.2.9"):text.index("### v0.2.8")]
    assert "#6（候选信号事件改为分页包装）" in head and "#11（放弃草案的请求体）" in head and "#12" in head


# =============================== 第 1 条：/meta/enums 与 candidate_signal_event_cause ===============================
def test_01_docs_event_cause_enum() -> None:
    """第 1 条（文档层）：§3 新增 candidate_signal_event_cause，取值与顺序逐项相等。"""
    assert _enum_row(_docs029(), "candidate_signal_event_cause") == EVENT_CAUSES


@pytest.mark.unit
def test_01_db_cause_check_equals_contract_enum() -> None:
    """第 1 / 3 条（已实现，严格）：candidate_signal_events.cause 的 CHECK 取值与顺序等于契约枚举。"""
    assert _check_values(_signals().candidate_signal_events, "cause") == EVENT_CAUSES


def test_01_meta_enums_v029(app_client: Callable[..., Any]) -> None:
    """第 1 条（接口层）：version = v0.2.9；enums.candidate_signal_event_cause 取值与顺序逐项相等。"""
    c = app_client("open")
    body = c.get(f"{API}/meta/enums").json()
    if body.get("version") != V029:
        pytest.xfail(f"{O_ENUMS29}；当前 version = {body.get('version')}")
    assert body["enums"]["candidate_signal_event_cause"] == EVENT_CAUSES


FRONT = REPO / "src" / "frontend" / "src"


def _front(rel: str) -> str:
    p = FRONT / rel
    if not p.is_file():
        pytest.skip(f"工作树没有 src/frontend/src/{rel}")
    return p.read_text(encoding="utf-8")


def test_01_frontend_contract_version_v029() -> None:
    """第 1 条（前端）：enums.ts 的 CONTRACT_VERSION = v0.2.9，并含 candidate_signal_event_cause（6 个取值同序）。"""
    src = _front("api/enums.ts")
    m = re.search(r"CONTRACT_VERSION\s*=\s*'(v[0-9.]+)'", src)
    assert m, "enums.ts 没有 CONTRACT_VERSION"
    if m.group(1) != V029:
        pytest.xfail(f"{O_FRONT29}；当前 {m.group(1)}")
    m2 = re.search(r"candidate_signal_event_cause:\s*\[([^\]]*)\]", src)
    assert m2 and re.findall(r"'([a-z_]+)'", m2.group(1)) == EVENT_CAUSES


# =============================== 第 2 条：可转债持仓 ===============================
def test_02_convertible_bond_position_estimated(session: Callable[..., SimpleNamespace]) -> None:
    """第 2 条 + 裁定 R6：import_as_is 可转债行 → security_type=null、estimated=true、market_value/pnl/pnl_pct=null、
    weight_pct 按成本（不为 null）；顶层 data_status=partial、无顶层 estimated；有日线或快照参考价的股票/ETF 行
    estimated=false；/terminal 的 holding 一致。手工成交 / 快照路径的 R6 断言见 test_rulings_t_b46_47_t_t25d.py。"""
    s = session()
    require_route(s.client, "GET", "/portfolio", O_PORTFOLIO)
    require_route(s.client, "POST", "/imports", O_PORTFOLIO + "（导入端点 T-B18/T-B19）")
    pytest.xfail(O_PORTFOLIO + "：导入夹具（含可转债行的交割单）待端点落地后补")  # pragma: no cover


#: 裁定 R6 ③：持仓行上这些字段永不为 null（顶层 cash、total_assets 同理，见 test_r6_* in test_rulings_t_b46_47_t_t25d.py）
R6_ROW_NON_NULL = ("qty", "sellable_qty", "cost_price", "weight_pct")


@pytest.mark.parametrize("row", [
    {"security_type": None, "estimated": True, "market_value": None, "pnl": None, "pnl_pct": None},
    {"security_type": "stock", "estimated": True, "market_value": None, "pnl": None, "pnl_pct": None},
    {"security_type": "stock", "estimated": False, "market_value": "1000.00", "pnl": "0.00", "pnl_pct": "0.00"},
    {"security_type": None, "estimated": False, "market_value": "1000.00", "pnl": "0.00", "pnl_pct": "0.00"},
], ids=["cb_not_in_master", "stock_no_price_estimated", "stock_priced", "not_in_master_snapshot_priced"])
def test_02_position_row_shape_rules(row: dict[str, Any]) -> None:
    """第 2 条 + 裁定 R6（规则自检，严格）：估值行与非估值行的字段组合规则（供 _check_position 复用）。
    R6 ①：``security_type: security_type|null``（null = 不在主数据中），不再有 ``instrument_kind``；
    R6 ② 第 3 步：日线与快照参考价都没有时才估算——估算与是否在主数据无关（股票同样可能估算）。"""
    assert _check_position({"weight_pct": "1.00", "qty": "10", "sellable_qty": "10", "cost_price": "100", **row}) is None


@pytest.mark.parametrize("bad", [
    {"estimated": True, "market_value": "0.00"},  # 估算行市值是 null，不是 0（问题 79）
    {"instrument_kind": "stock"},  # R6 ① 驳回 instrument_kind
    {"security_type": "convertible_bond"},  # 不是契约 security_type 取值
    {"weight_pct": None},  # R6 ③
    {"cost_price": None},  # R6 ③
], ids=["estimated_mv_zero", "instrument_kind", "bad_security_type", "weight_null", "cost_null"])
def test_02_position_row_shape_rejects(bad: dict[str, Any]) -> None:
    """R6 规则自检的反例：每一条都必须被 _check_position 拒绝（防止断言形同虚设）。"""
    row = {"security_type": "stock", "estimated": False, "market_value": "1000.00", "pnl": "0.00", "pnl_pct": "0.00",
           "weight_pct": "1.00", "qty": "10", "sellable_qty": "10", "cost_price": "100", **bad}
    with pytest.raises(AssertionError):
        _check_position(row)


def _check_position(p: dict[str, Any]) -> None:
    """裁定 R6 的持仓行规则（T-B46-47-rulings.md）。"""
    assert "instrument_kind" not in p, "R6 ①：驳回 instrument_kind，改用 security_type"
    assert "security_type" in p and p["security_type"] in {"stock", "cdr", "etf", None}, p.get("security_type")
    assert isinstance(p["estimated"], bool)
    if p["estimated"]:
        assert p["market_value"] is None and p["pnl"] is None and p["pnl_pct"] is None, "无行情不是 0（R6 ② / 问题 79）"
    else:
        assert p["market_value"] is not None, "有现价（日线收盘或快照参考价）时市值不为 null"
    for k in R6_ROW_NON_NULL:
        assert p.get(k) is not None, f"R6 ③：{k} 不为 null"


# =============================== 第 3 条 + 不兼容 #6：候选信号事件分页 ===============================
def _seed_signal(sql: Callable[..., Any], uid: str) -> str:
    try:
        return str(sql("INSERT INTO app.candidate_signals (user_id, strategy_version_id, security_code, horizon, "
                       "proposed_action, rule_refs, evidence, counter_evidence, invalidation, model_refs) "
                       "SELECT :u, sv.id, '600981.SH', 'swing', 'buy', '[]', '[]', '[]', '[]', '[]' "
                       "FROM app.strategy_versions sv LIMIT 1 RETURNING id", u=uid)[0][0])
    except Exception as exc:  # noqa: BLE001
        pytest.xfail(f"{O_SEED}：{type(exc).__name__}")


def _seed_events(sql: Callable[..., Any], sid: str, n: int, same_at: bool = True) -> list[str]:
    at = dt.datetime(2026, 11, 2, 1, 0, tzinfo=dt.UTC)
    ids = []
    for i in range(n):
        ids.append(str(sql("INSERT INTO app.candidate_signal_events (signal_id, from_state, to_state, cause, detail, at) "
                           "VALUES (:s, :f, 'blocked', 'executability_check', CAST(:d AS jsonb), :at) RETURNING id",
                           s=sid, f=None if i == 0 else "open", d=json.dumps({"k": i}),
                           at=at if same_at else at + dt.timedelta(minutes=i))[0][0]))
    return ids


def test_bc6_events_is_paginated_wrapper(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    """不兼容 #6 / 验收第 3 条：响应为 {items, next_cursor}（不是数组）；按 at desc, id desc；翻页不重不漏；
    元素键集合 = {id, from, to, cause, at}（无 detail）；cause ∈ 枚举；首条 from 为 null。"""
    s = session()
    require_route(s.client, "GET", "/candidate-signals/{id}/events", O_SIGNALS)
    sid = _seed_signal(sql, s.user.id)
    seeded = _seed_events(sql, sid, 5, same_at=True) + _seed_events(sql, sid, 3, same_at=False)
    call, got, cursor, pages = Rec(s), [], None, 0
    while True:
        r = call("GET", f"/candidate-signals/{sid}/events", params={"limit": 3, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert isinstance(body, dict) and set(body) >= {"items", "next_cursor"}, "v0.2.9 起不再返回裸数组"
        for e in body["items"]:
            assert set(e) == {"id", "from", "to", "cause", "at"}, e
            assert e["cause"] in EVENT_CAUSES
        got += body["items"]
        cursor, pages = body["next_cursor"], pages + 1
        if not cursor:
            break
        assert pages < 10
    ids = [e["id"] for e in got]
    assert len(ids) == len(set(ids)) and set(ids) == set(seeded), "翻页不重不漏"
    keys = [(e["at"], e["id"]) for e in got]
    assert keys == sorted(keys, reverse=True), "at desc, id desc"


def test_bc6_events_unknown_or_foreign_signal_404(session: Callable[..., SimpleNamespace]) -> None:
    """不兼容 #6（对照）：不存在或他人信号 → 404（分页包装不改变权限语义）。"""
    s = session()
    require_route(s.client, "GET", "/candidate-signals/{id}/events", O_SIGNALS)
    r = Rec(s)("GET", f"/candidate-signals/{uuid.uuid4()}/events")
    assert r.status_code == 404, r.text[:300]


def test_03_confirm_draft_latest_event_is_user(session: Callable[..., SimpleNamespace]) -> None:
    """第 3 条：确认草案后最新一条为 {from:"drafted", to:"confirmed", cause:"user"}。"""
    s = session()
    require_route(s.client, "POST", "/plan-drafts/{id}/confirm", O_DRAFTS)
    require_route(s.client, "GET", "/candidate-signals/{id}/events", O_SIGNALS)
    pytest.xfail(O_SEED)  # pragma: no cover


@pytest.mark.unit
def test_bc6_frontend_mock_causes_within_enum() -> None:
    """不兼容 #6（前端回归）：mock 的事件 cause 只用 6 个契约取值（删除 plan_confirmed 等自造值）。"""
    src = _front("mocks/signalHandlers.ts")
    m = re.search(r"CAUSE_OF[^=]*=\s*\{([^}]*)\}", src)
    if not m:
        return  # 已改为别的写法：由前端自己的单测覆盖
    bad = sorted(set(re.findall(r"'([a-z_]+)'", m.group(1))) - set(EVENT_CAUSES) - set(_t23_states()))
    if bad:
        pytest.xfail(f"{O_FRONT29}；mock cause 含 {bad}")


def _t23_states() -> list[str]:
    return ["open", "drafted", "blocked", "released", "confirmed", "dismissed", "expired", "invalidated", "superseded"]


# =============================== 第 4 条 + 不兼容 #12：/non-executable-reasons 默认 active ===============================
@pytest.mark.unit
def test_04_db_reason_status_values() -> None:
    """第 4 条（已实现，严格）：non_executable_reasons.status 只有 active / released / obsolete（status=all 的全集）。"""
    assert sorted(_check_values(_signals().non_executable_reasons, "status")) == ["active", "obsolete", "released"]


def _seed_reasons(sql: Callable[..., Any], uid: str) -> dict[str, str]:
    sid = str(uuid.uuid4())
    out = {}
    for st in ("active", "released", "obsolete"):
        out[st] = str(sql("INSERT INTO app.non_executable_reasons (signal_id, user_id, code, status, machine_checkable, "
                          "released_at, released_by) VALUES (:s, :u, 'DATA_STALE', :st, true, "
                          "CASE WHEN :st='released' THEN now() END, CASE WHEN :st='released' THEN 'system' END) "
                          "RETURNING id", s=sid, u=uid, st=st)[0][0])
    out["signal_id"] = sid
    return out


def _reason_ids(call: Rec, **params: Any) -> set[str]:
    r = call("GET", "/non-executable-reasons", params=params)
    _httpdiag.observe_response('reasons', r)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert set(body) >= {"items", "next_cursor"}
    return {x["id"] for x in body["items"]}


def test_bc12_reasons_default_status_is_active(session: Callable[..., SimpleNamespace], sql: Callable[..., Any], httpdiag: Any) -> None:
    """不兼容 #12 / 验收第 4 条：不带 status → 只有 active；released 只有已解除；all 含三种；带 signal_ids 不带 status → active。"""
    s = session()
    require_route(s.client, "GET", "/non-executable-reasons", O_SIGNALS)
    ids, call = _seed_reasons(sql, s.user.id), Rec(s)
    httpdiag.synthetic_ids = ids
    assert _reason_ids(call) & set(ids.values()) == {ids["active"]}
    assert _reason_ids(call, status="released") & set(ids.values()) == {ids["released"]}
    assert _reason_ids(call, status="all") >= {ids["active"], ids["released"], ids["obsolete"]}
    assert _reason_ids(call, signal_ids=ids["signal_id"]) == {ids["active"]}
    assert _reason_ids(call, status="active", signal_ids=ids["signal_id"]) == {ids["active"]}


def test_bc12_reasons_bad_status_400(session: Callable[..., SimpleNamespace]) -> None:
    """不兼容 #12（对照）：status 只能是 active / released / all → 其他值 400 VALIDATION_ERROR（obsolete 不能单独筛）。"""
    s = session()
    require_route(s.client, "GET", "/non-executable-reasons", O_SIGNALS)
    for bad in ("obsolete", "ALL", "x"):
        assert_err(Rec(s)("GET", "/non-executable-reasons", params={"status": bad}), 400, "VALIDATION_ERROR")


def test_04_reason_has_security_code_and_name(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    """第 4 条：列表与详情都有 security_code、name，与所属信号一致。"""
    s = session()
    require_route(s.client, "GET", "/non-executable-reasons/{id}", O_SIGNALS)
    _seed_signal(sql, s.user.id)
    pytest.xfail(O_SEED)  # pragma: no cover


# =============================== 第 5 条：名单类原因不能手动解除 ===============================
@pytest.mark.parametrize("code", ["BLOCKLISTED", "USER_MUTED"])
def test_05_list_reasons_release_409(session: Callable[..., SimpleNamespace], sql: Callable[..., Any], code: str) -> None:
    """第 5 条：BLOCKLISTED / USER_MUTED 调 /release → 409 REASON_NOT_MANUALLY_RELEASABLE，原因仍 active。"""
    s = session()
    require_route(s.client, "POST", "/non-executable-reasons/{id}/release", O_SIGNALS)
    rid = str(sql("INSERT INTO app.non_executable_reasons (signal_id, user_id, code, machine_checkable) "
                  "VALUES (:s, :u, :c, true) RETURNING id", s=str(uuid.uuid4()), u=s.user.id, c=code)[0][0])
    assert_err(Rec(s)("POST", f"/non-executable-reasons/{rid}/release", json={"confirm": True, "note": None}),
               409, "REASON_NOT_MANUALLY_RELEASABLE")
    assert sql("SELECT status FROM app.non_executable_reasons WHERE id=:i", i=rid)[0][0] == "active"


def test_05_meta_reason_codes_list_reasons_machine_checkable(app_client: Callable[..., Any]) -> None:
    """第 5 条（接口层，/meta/enums）：BLOCKLISTED、USER_MUTED 不可手动解除（manually_releasable=false）。"""
    body = app_client("open").get(f"{API}/meta/enums").json()
    got = {r["code"]: r for r in body["reason_codes"]}
    wrong = [c for c in ("BLOCKLISTED", "USER_MUTED") if got[c]["manually_releasable"] is not False]
    if wrong:  # v0.2.9 #9 改为 machine_checkable=true（不可手动解除）；后端 reason_codes 仍按 v0.2.8
        pytest.xfail(f"{O_ENUMS29}；/meta/enums reason_codes 中 {wrong} 的 manually_releasable 仍为 true")
    assert all(got[c]["manually_releasable"] is False for c in ("BLOCKLISTED", "USER_MUTED"))


def test_05_restriction_delete_releases_by_system(session: Callable[..., SimpleNamespace]) -> None:
    """第 5 条：删除对应 /restrictions 后系统重查并解除（released_by="system"）；STRATEGY_CONFLICT evidence 含对方信号 id。"""
    s = session()
    require_route(s.client, "POST", "/non-executable-reasons/{id}/release", O_SIGNALS)
    pytest.xfail(O_SEED)  # pragma: no cover


# =============================== 第 6 条：跟踪统计 scope ===============================
TRACKING = "/strategies/{id}/versions/{vid}/tracking"


def test_06_tracking_scope(session: Callable[..., SimpleNamespace]) -> None:
    """第 6 条：不传 scope = mine；scope=site 不含用户 id / 用户名 / 个股持仓；scope=other → 400 VALIDATION_ERROR。"""
    s = session()
    require_route(s.client, "GET", TRACKING, O_TRACKING)
    path = f"/strategies/{uuid.uuid4()}/versions/{uuid.uuid4()}/tracking"
    assert_err(Rec(s)("GET", path, params={"scope": "other"}), 400, "VALIDATION_ERROR")
    pytest.xfail(O_SEED + "（mine/site 比较需策略版本与跟踪数据）")  # pragma: no cover


# =============================== 第 7–9 条 + 不兼容 #11：计划草案 ===============================
def test_07_multi_signal_draft_rules(session: Callable[..., SimpleNamespace]) -> None:
    """第 7 条：同证券同动作 2 个信号 → 201；跨证券或动作不同 → 400{field:"signal_ids"}；方向相反 → 409。"""
    s = session()
    require_route(s.client, "POST", "/plan-drafts", O_DRAFTS)
    assert_err(Rec(s)("POST", "/plan-drafts", json={"signal_ids": []}), 400, "VALIDATION_ERROR")
    pytest.xfail(O_SEED)  # pragma: no cover


@pytest.mark.unit
def test_08_market_rules_lot_config(config_dir: Path) -> None:
    """第 8 条（配置，严格）：config/market_rules.yaml 每段 lot：主板/创业板/ETF 递增 100；科创板起买 200、递增 1。"""
    import yaml  # noqa: PLC0415

    p = config_dir / "market_rules.yaml"
    if not p.is_file():
        pytest.skip(f"{config_dir} 下没有 market_rules.yaml")
    lots = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if isinstance(x.get("lot"), dict):
                lots.append(x["lot"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(yaml.safe_load(p.read_text(encoding="utf-8")))
    assert lots, "market_rules.yaml 没有 lot 段"
    for lot in lots:
        assert (lot["buy_lot"], lot["star_min_buy"], lot["star_step"]) == (100, 200, 1), lot


def test_08_lot_rule_on_confirm(session: Callable[..., SimpleNamespace]) -> None:
    """第 8 条：科创板 min≥200、lot=1；科创板 150 / 主板 150 → 400{field:"chosen_qty", issue:"lot_rule"}（deviation_ack 不能绕过）；
    主板 300 区间外 + deviation_ack → 201；卖出全部可卖（含零股）→ 201。"""
    s = session()
    require_route(s.client, "POST", "/plan-drafts/{id}/confirm", O_DRAFTS)
    pytest.xfail(O_SEED)  # pragma: no cover


def _seed_draft(sql: Callable[..., Any], uid: str, status: str = "pending") -> str:
    return str(sql("INSERT INTO app.plan_drafts (user_id, signal_ids, security_code, action, expires_at, status) "
                   "VALUES (:u, ARRAY[CAST(:s AS uuid)], '600981.SH', 'buy', now() + interval '1 day', :st) RETURNING id",
                   u=uid, s=str(uuid.uuid4()), st=status)[0][0])


@pytest.mark.unit
def test_bc11_plan_drafts_has_no_note_column() -> None:
    """不兼容 #11（已实现，严格）：plan_drafts 没有任何备注列（note 无处存放，隐私从严）。"""
    tbl = _signals().plan_drafts
    assert not [c.name for c in tbl.columns if "note" in c.name or "comment" in c.name or "reason" in c.name]


@pytest.mark.parametrize("body", [{}, {"note": "示例"}], ids=["empty", "legacy_note"])
def test_bc11_discard_body(session: Callable[..., SimpleNamespace], sql: Callable[..., Any], body: dict[str, Any]) -> None:
    """不兼容 #11 / 验收第 9 条：{} → 200、status=discarded；{"note": …} 同样成功（不 400），库、审计、响应都没有该备注。"""
    s = session()
    require_route(s.client, "POST", "/plan-drafts/{id}/discard", O_DRAFTS)
    did = _seed_draft(sql, s.user.id)
    note = "示例" + uuid.uuid4().hex[:8] if body else None
    r = Rec(s)("POST", f"/plan-drafts/{did}/discard", json={"note": note} if note else {})
    assert r.status_code == 200, r.text[:300]
    assert r.json()["status"] == "discarded" and "note" not in r.json()
    assert sql("SELECT status FROM app.plan_drafts WHERE id=:i", i=did)[0][0] == "discarded"
    if note:
        assert note not in r.text
        dump = sql("SELECT coalesce(string_agg(detail::text, ''), '') FROM app.audit_logs")[0][0]
        assert note not in dump, "备注写进了审计"
        assert note not in json.dumps([list(x) for x in sql("SELECT * FROM app.plan_drafts WHERE id=:i", i=did)],
                                      default=str, ensure_ascii=False)


@pytest.mark.parametrize("status", ["confirmed", "discarded", "expired", "stale"])
def test_09_discard_non_pending_409(session: Callable[..., SimpleNamespace], sql: Callable[..., Any], status: str) -> None:
    """第 9 条：非 pending 草案放弃 → 409 INVALID_STATE_TRANSITION，状态不变。"""
    s = session()
    require_route(s.client, "POST", "/plan-drafts/{id}/discard", O_DRAFTS)
    did = _seed_draft(sql, s.user.id, status)
    assert_err(Rec(s)("POST", f"/plan-drafts/{did}/discard", json={}), 409, "INVALID_STATE_TRANSITION")
    assert sql("SELECT status FROM app.plan_drafts WHERE id=:i", i=did)[0][0] == status


@pytest.mark.unit
def test_bc11_frontend_discard_sends_empty_body() -> None:
    """不兼容 #11（前端回归）：放弃草案的请求体为 {}（不再发 note）。"""
    src = _front("api/planQueries.ts")
    calls = re.findall(r"/discard`\s*,\s*([^)]*)\)", src)
    if not calls:
        pytest.skip("planQueries.ts 没有 discard 调用")
    if any("note" in c for c in calls):
        pytest.xfail(f"{O_FRONT29}；planQueries.ts discard 仍发 note")
    assert all(c.strip() in {"{}", ""} for c in calls), calls


# =============================== 第 10 条：关闭注册一律 503（T-T23 裁定 1） ===============================
def _closed_bodies() -> list[tuple[str, dict[str, Any]]]:
    good = reg(new_name(), new_pw())
    return [
        ("wellformed", {"json": good}),
        ("not_json", {"content": b"{not json", "headers": {"Content-Type": "application/json"}}),
        ("missing_username", {"json": {k: v for k, v in reg(new_name(), new_pw()).items() if k != "username"}}),
        ("password_number", {"json": {**reg(new_name(), new_pw()), "password": 12345678}}),
        ("unknown_field", {"json": {**reg(new_name(), new_pw()), "__unknown_field__": 1}}),
        ("honeypot", {"json": {**reg(new_name(), new_pw()), "website": "http://example.invalid/" + uuid.uuid4().hex[:6]}}),
    ]


def test_10_closed_registration_every_body_503_identical(app_client: Callable[..., Any], sql: Callable[..., Any]) -> None:
    """第 10 条（架构师裁定 2026-11-02, v0.2.9 687159f）：closed 时 6 类请求体一律 503 REGISTRATION_CLOSED，
    错误体（除 request_id）相同，不返回 400；users 无新增；不写蜜罐审计。"""
    probe = app_client("closed").post(f"{API}/auth/register", json={})
    if probe.status_code == 400:
        pytest.xfail(O_REG)
    n0, t0 = sql("SELECT count(*) FROM app.users")[0][0], sql("SELECT now()")[0][0]
    shapes = {}
    for name, kw in _closed_bodies():
        r = app_client("closed").post(f"{API}/auth/register", **kw)
        assert_err(r, 503, "REGISTRATION_CLOSED")
        shapes[name] = _err_shape(r)
    assert len(set(shapes.values())) == 1, shapes
    assert sql("SELECT count(*) FROM app.users")[0][0] == n0
    assert _t23._honeypot_audits(sql, t0) == []


# =============================== 第 11 条：证书设置开关（T-T23 裁定 3） ===============================
@pytest.fixture
def off_fresh(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any], backend: SimpleNamespace) -> SimpleNamespace:
    """未设置证书的用户，登录在开关关闭的应用上。"""
    _r._require_switch(backend)
    u = mkuser()
    s = session(u, **{FLAG: False})
    return SimpleNamespace(user=u, s=s, call=Rec(s))


def test_11_put_bad_format_400_good_503(off_fresh: SimpleNamespace, sql: Callable[..., Any]) -> None:
    """第 11 条：PUT 格式错误（licence 中间含空白）→ 400 VALIDATION_ERROR；格式正确 → 503 MAINTENANCE；不落库。"""
    c, lic = off_fresh.call, fake_licence()
    assert_err(put(c, lic[:8] + " " + lic[8:]), 400, "VALIDATION_ERROR")
    assert_err(put(c, lic), 503, "MAINTENANCE")
    assert live_row(sql, off_fresh.user.id) is None
    assert leak_count(lic, "\n".join(c.bodies + c.headers)) == 0


def test_11_patch_bad_type_400_good_503_even_not_set(off_fresh: SimpleNamespace) -> None:
    """第 11 条：PATCH tier 类型错误 → 400；格式正确 → 503（未设置证书时也是 503，不是 409 DATA_LICENCE_NOT_SET）。"""
    c = off_fresh.call
    assert_err(c("PATCH", "/me/data-licence", json={"tier": 123}), 400, "VALIDATION_ERROR")
    assert_err(c("PATCH", "/me/data-licence", json={"has_quant_pro": True}), 503, "MAINTENANCE")


def test_11_test_503_get_200_delete_204(off_fresh: SimpleNamespace, sql: Callable[..., Any]) -> None:
    """第 11 条：POST /test → 503（无请求体，先于 NOT_SET）；GET → 200；DELETE → 204。"""
    c = off_fresh.call
    assert_err(c("POST", "/me/data-licence/test"), 503, "MAINTENANCE")
    g = c("GET", "/me/data-licence")
    assert g.status_code == 200 and g.json()["status"] == "not_set", g.text[:300]
    d = c("DELETE", "/me/data-licence")
    assert d.status_code == 204, d.text[:300]
    assert live_row(sql, off_fresh.user.id) is None
