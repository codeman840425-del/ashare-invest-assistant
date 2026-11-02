"""T-T25：架构师对 T-T23 三个未决问题的裁定（架构师裁定 2026-11-02, v0.2.9 687159f）。

1. **closed 模式 + 畸形请求体**：一律 ``503 REGISTRATION_CLOSED``，绝不 400；判定顺序中注册模式最先。
   （架构师裁定 2026-11-02, v0.2.9 687159f）
2. **plan.md:1733 ``IMPORT_LOT_SIZE_IRREGULAR``**：67d123a（v0.2.8 补充裁定 #17①）已把 plan 3.5A-1 第 46 行与契约 §4.1
   同步为“…；ETF 按 100 份整数倍，v0.2.8”。本组断言两处整行一致且含该文字；领域函数按 100 份整数倍判定。
3. **503 MAINTENANCE**：``DATA_LICENCE_SETTINGS_ENABLED=false`` 时 ``PUT`` / ``PATCH /me/data-licence`` 与
   ``POST /me/data-licence/test`` → ``503 MAINTENANCE``，``GET`` / ``DELETE`` 照常；``PUT`` / ``PATCH`` 先校验请求体格式
   （畸形 → 400），之后才判 503。（架构师裁定 2026-11-02, v0.2.9 687159f）

后端未实现的部分：``xfail(strict=False)`` 或 imperative ``xfail``，写明后端责任人；已实现的严格断言。
测试证书由 ``fake_licence`` 运行时随机生成；不联网、不调用麦蕊；独立临时库（testcontainers）。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_spec = importlib.util.spec_from_file_location("tt25_t23_helpers", Path(__file__).with_name("test_contract_v028_t_t23.py"))
_t23 = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_t23)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:
    pytest.skip(str(exc), allow_module_level=True)

authdb, sql, app_client, mkuser, session, make_settings = (
    _t23.authdb, _t23.sql, _t23.app_client, _t23.mkuser, _t23.session, _t23.make_settings)
API, assert_err, reg, new_name, new_pw = _t23.API, _t23.assert_err, _t23.reg, _t23.new_name, _t23.new_pw
Rec, fake_licence, body_of, put, live_row, licence_ids = (
    _t23.Rec, _t23.fake_licence, _t23.body_of, _t23.put, _t23.live_row, _t23.licence_ids)
verify_intents, leak_count, _user_count = _t23.verify_intents, _t23.leak_count, _t23._user_count

RULING = "架构师裁定 2026-11-02, v0.2.9 687159f"
O_REG_ORDER = (f"后端 T-B03c（注册；{RULING}：closed 模式先于请求体校验，畸形体也 503 REGISTRATION_CLOSED——"
               "origin 0cb78ad 上 RegisterIn 由 FastAPI 先校验，返回 400；本地 main f72b8c7（T-B03e 追加）已实现，未推 origin）")
O_SETTINGS_SWITCH = (f"后端 T-B03d（review M4：DATA_LICENCE_SETTINGS_ENABLED 证书设置开关，{RULING}；"
                     "本地 main 已实现，未推 origin）")
O_DOCS = "运维（推送契约 v0.2.8 / 架构师 67d123a 补充裁定到 origin；当前 docs 版本低于 v0.2.8）"

pytestmark = [pytest.mark.integration, pytest.mark.contract]

REPO = Path(__file__).resolve().parents[3]


# =============================== 裁定 1：closed 模式先于请求体校验 ===============================
#: 畸形请求体（都不是合法 RegisterIn）：(id, 关键字参数)
MALFORMED_REGISTER = [
    ("empty_object", {"json": {}}),
    ("json_array", {"json": []}),
    ("not_json", {"content": b"{not json", "headers": {"Content-Type": "application/json"}}),
    ("wrong_types", {"json": {"username": 123, "password": ["x"], "display_name": None}}),
    ("unknown_field", {"json": {"__unknown_field__": "x"}}),
]


@pytest.mark.parametrize("kw", [k for _, k in MALFORMED_REGISTER], ids=[i for i, _ in MALFORMED_REGISTER])
@pytest.mark.xfail(strict=False, reason=O_REG_ORDER)
def test_r1_closed_mode_malformed_body_is_503(app_client: Callable[..., Any], sql: Callable[..., Any],
                                              kw: dict[str, Any]) -> None:
    """裁定 1（架构师裁定 2026-11-02, v0.2.9 687159f）：closed 模式不看请求体，一律 503 REGISTRATION_CLOSED。"""
    n0 = sql("SELECT count(*) FROM app.users")[0][0]
    r = app_client("closed").post(f"{API}/auth/register", **kw)
    assert_err(r, 503, "REGISTRATION_CLOSED")
    assert sql("SELECT count(*) FROM app.users")[0][0] == n0


def test_r1_closed_mode_wellformed_body_is_503_control(app_client: Callable[..., Any], sql: Callable[..., Any]) -> None:
    """对照（已实现，严格）：合法请求体在 closed 模式下 503，不建用户。"""
    name = new_name()
    assert_err(app_client("closed").post(f"{API}/auth/register", json=reg(name, new_pw())), 503, "REGISTRATION_CLOSED")
    assert _user_count(sql, name) == 0


@pytest.mark.parametrize("kw", [k for _, k in MALFORMED_REGISTER], ids=[i for i, _ in MALFORMED_REGISTER])
def test_r1_open_mode_malformed_body_is_400_control(app_client: Callable[..., Any], kw: dict[str, Any]) -> None:
    """对照（严格）：非 closed 模式下畸形请求体仍是 400 VALIDATION_ERROR（裁定只改 closed 的判定顺序）。"""
    assert_err(app_client("open").post(f"{API}/auth/register", **kw), 400, "VALIDATION_ERROR")


# =============================== 裁定 2：IMPORT_LOT_SIZE_IRREGULAR 文档同步 ===============================
_VERSION_RE = re.compile(r"版本：\*\*v(\d+)\.(\d+)(?:\.(\d+))?\*\*")
_ROW46_RE = re.compile(r"^\| 46 \| `IMPORT_LOT_SIZE_IRREGULAR` \|.*\|$", re.M)
ETF_LOT_TEXT = "ETF 按 100 份整数倍"


def _docs() -> SimpleNamespace:
    d = Path(os.environ.get("AIA_DOCS_DIR", REPO / "docs"))
    contract, plan = d / "api-contract.md", d / "plan.md"
    if not (contract.is_file() and plan.is_file()):
        pytest.skip(f"{d} 下没有 api-contract.md / plan.md")
    ct, pt = contract.read_text(encoding="utf-8"), plan.read_text(encoding="utf-8")
    m = _VERSION_RE.search(ct)
    ver = tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    return SimpleNamespace(contract=ct, plan=pt, ver=ver)


def _row46(text: str, where: str) -> str:
    rows = _ROW46_RE.findall(text)
    assert len(rows) == 1, f"{where}：IMPORT_LOT_SIZE_IRREGULAR 行数 {len(rows)}"
    return rows[0]


def test_r2_lot_size_row_plan_equals_contract() -> None:
    """裁定 2：plan 3.5A-1 第 46 行与契约 §4.1 第 46 行整行一致（任何版本都要求一致）。"""
    d = _docs()
    assert _row46(d.plan, "plan.md") == _row46(d.contract, "api-contract.md")


def test_r2_lot_size_row_mentions_etf_100_units() -> None:
    """裁定 2（67d123a）：v0.2.8 起两处都写“ETF 按 100 份整数倍”。"""
    d = _docs()
    if d.ver < (0, 2, 8):
        pytest.xfail(f"{O_DOCS}：docs 版本 v{'.'.join(map(str, d.ver))}")
    for text, where in ((d.contract, "api-contract.md"), (d.plan, "plan.md")):
        assert ETF_LOT_TEXT in _row46(text, where), where


@pytest.mark.unit
def test_r2_etf_lot_irregular_is_multiple_of_100() -> None:
    """裁定 2 的领域规则：ETF 买入数量不是 100 份整数倍 → 不规则（只提示）。"""
    try:
        st = importlib.import_module("app.marketdata.security_types")
    except ModuleNotFoundError:
        pytest.xfail(_t23.O_B02Y)
    for q in (100, 200, 1000, 12300, Decimal("500")):
        assert not st.etf_lot_irregular(q), q
    for q in (1, 50, 99, 101, 150, 1050, Decimal("100.5")):
        assert st.etf_lot_irregular(q), q


# =============================== 裁定 3：证书设置开关 → 503 MAINTENANCE ===============================
FLAG = "data_licence_settings_enabled"


def _require_switch(backend: SimpleNamespace) -> None:
    if FLAG not in getattr(backend.config.Settings, "model_fields", {}):
        pytest.xfail(O_SETTINGS_SWITCH + "；Settings 没有 data_licence_settings_enabled")


def test_r3_switch_defaults(backend: SimpleNamespace, make_settings: Callable[..., Any]) -> None:
    """开关未设时非生产环境开启；显式 false / true 生效。"""
    _require_switch(backend)
    assert make_settings().licence_settings_enabled is True
    assert make_settings(**{FLAG: False}).licence_settings_enabled is False
    assert make_settings(**{FLAG: True}).licence_settings_enabled is True


@pytest.fixture
def off(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any], backend: SimpleNamespace) -> SimpleNamespace:
    """同一用户两个会话：开关开着时设置好证书，再用开关关闭的应用登录。"""
    _require_switch(backend)
    u = mkuser()
    on = session(u, **{FLAG: True})
    lic = fake_licence()
    r = put(Rec(on), lic)
    assert r.status_code == 202, r.text[:300]
    s = session(u, **{FLAG: False})
    return SimpleNamespace(user=u, on=on, s=s, call=Rec(s), lic=lic)


def _state(sql: Callable[..., Any], authdb: SimpleNamespace, call: Rec, uid: str) -> tuple[Any, ...]:
    ids = licence_ids(sql, uid)
    g = call("GET", "/me/data-licence")
    assert g.status_code == 200, g.text[:300]
    row = sql("SELECT id::text, status, tier, has_quant_pro, expires_on FROM app.user_data_licences "
              "WHERE user_id=:u AND deleted_at IS NULL", u=uid)
    return ids, tuple(map(tuple, row)), verify_intents(authdb.redis, ids), g.json()


def test_r3_switch_off_writes_are_503_reads_and_delete_work(off: SimpleNamespace, sql: Callable[..., Any],
                                                             authdb: SimpleNamespace) -> None:
    """裁定 3（架构师裁定 2026-11-02, v0.2.9 687159f）：开关关闭 → PUT / PATCH / test 503 MAINTENANCE 且无副作用；
    GET 200、DELETE 204 照常。"""
    c, uid = off.call, off.user.id
    before = _state(sql, authdb, c, uid)
    assert before[3]["status"] != "not_set"
    assert_err(put(c, fake_licence()), 503, "MAINTENANCE")
    assert_err(put(c, off.lic), 503, "MAINTENANCE")
    assert_err(c("PATCH", "/me/data-licence", json={"has_quant_pro": True}), 503, "MAINTENANCE")
    assert_err(c("POST", "/me/data-licence/test"), 503, "MAINTENANCE")
    assert _state(sql, authdb, c, uid) == before, "503 不得有任何写入或入队"
    r = c("DELETE", "/me/data-licence")
    assert r.status_code == 204, r.text[:300]
    assert live_row(sql, uid) is None
    g = c("GET", "/me/data-licence")
    assert g.status_code == 200 and g.json()["status"] == "not_set", g.text[:300]
    # 删除后再 PUT / test 仍是 503（开关先于 NOT_SET 等业务判断）
    assert_err(put(c, off.lic), 503, "MAINTENANCE")
    assert_err(c("POST", "/me/data-licence/test"), 503, "MAINTENANCE")
    assert live_row(sql, uid) is None
    assert leak_count(off.lic, "\n".join(c.bodies + c.headers)) == 0


#: 畸形 PUT / PATCH 请求体：先 400，开关检查在其后
MALFORMED_PUT = [
    ("empty", {"json": {}}),
    ("licence_not_string", {"json": {"licence": 12345678901234567, "tier": "free", "has_quant_pro": False,
                                     "expires_on": None}}),
    ("unknown_field", "extra"),
    ("not_json", {"content": b"{not json", "headers": {"Content-Type": "application/json"}}),
]
MALFORMED_PATCH = [
    ("bad_tier", {"json": {"tier": "__no_such_tier__"}}),
    ("null_has_quant_pro", {"json": {"has_quant_pro": None}}),
    ("unknown_field", {"json": {"__unknown_field__": 1}}),
    ("bad_date", {"json": {"expires_on": "not-a-date"}}),
]


@pytest.mark.parametrize("kw", [k for _, k in MALFORMED_PUT], ids=[i for i, _ in MALFORMED_PUT])
def test_r3_switch_off_malformed_put_is_400_first(off: SimpleNamespace, sql: Callable[..., Any],
                                                  authdb: SimpleNamespace, kw: Any) -> None:
    """裁定 3：PUT 先校验请求体格式，畸形 → 400 VALIDATION_ERROR（不是 503），且无副作用。"""
    c = off.call
    if kw == "extra":
        kw = {"json": {**body_of(fake_licence()), "__unknown_field__": 1}}
    before = _state(sql, authdb, c, off.user.id)
    if "headers" in kw:  # 非 JSON 体：自带 Content-Type，手动带上 CSRF 头
        r = off.s.client.request("PUT", f"{API}/me/data-licence", content=kw["content"],
                                 headers={**kw["headers"], "X-CSRF-Token": off.s.csrf})
    else:
        r = c("PUT", "/me/data-licence", **kw)
    assert_err(r, 400, "VALIDATION_ERROR")
    assert _state(sql, authdb, c, off.user.id) == before


@pytest.mark.parametrize("kw", [k for _, k in MALFORMED_PATCH], ids=[i for i, _ in MALFORMED_PATCH])
def test_r3_switch_off_malformed_patch_is_400_first(off: SimpleNamespace, sql: Callable[..., Any],
                                                    authdb: SimpleNamespace, kw: dict[str, Any]) -> None:
    """裁定 3：PATCH 先校验请求体格式，畸形 → 400 VALIDATION_ERROR（不是 503），且无副作用。"""
    c = off.call
    before = _state(sql, authdb, c, off.user.id)
    assert_err(c("PATCH", "/me/data-licence", **kw), 400, "VALIDATION_ERROR")
    assert _state(sql, authdb, c, off.user.id) == before


def test_r3_switch_on_control(off: SimpleNamespace, sql: Callable[..., Any]) -> None:
    """对照：同一用户在开关开启的应用上 PATCH 200、test 202（开关是唯一差别）。"""
    c = Rec(off.on)
    r = c("PATCH", "/me/data-licence", json={"has_quant_pro": True})
    assert r.status_code == 200 and r.json()["has_quant_pro"] is True, r.text[:300]
    r = c("POST", "/me/data-licence/test")
    assert r.status_code in (202, 409), r.text[:300]  # 409：验证中/限速等业务态，非 503
    assert r.status_code != 503
