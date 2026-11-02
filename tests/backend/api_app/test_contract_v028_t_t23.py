"""T-T23：契约 v0.2.8（T-A09，架构师 6ef79c4）§9 验收第 1–13 条的契约测试（T-A09 报告把这组测试点记为 T-T17 的 §9 引用）。

真实 PG/Redis（复用 ``test_auth_t_b03.py`` / ``test_data_licence_t_t22.py`` 的夹具，独立临时库），进程内 TestClient，
不联网、不调用麦蕊；测试证书由 :func:`fake_licence` 在运行时随机生成，源码里没有任何证书字面量。

门控原则（不放宽断言）：

- 按后端 ``/meta/enums.version`` 门控的行为（第 10–12 条）：后端仍报 v0.2.7 或更早 → imperative ``xfail``（写明责任任务）；
  报 v0.2.8 → 严格断言；
- 端点尚未挂载（第 2、6–9 条的 HTTP 部分）→ ``xfail``（写明责任任务）；挂载后严格断言；
- 领域模块（``app.marketdata.security_types``、``app.strategy.eligibility``、``service.ingest_licences``、迁移 0009 触发器）
  不存在 → ``xfail``；存在 → 严格断言；
- 不依赖 v0.2.8 的条目（第 3 条 ``/admin/data-licences`` 部分、第 5 条）直接断言。

第 1 条的后端 / 文档部分在 ``test_meta_enums.py``（``test_v028_*``），本文件只补前端 ``CONTRACT_VERSION``。
"""

from __future__ import annotations

import base64
import datetime as dt
import importlib
import importlib.util
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_spec = importlib.util.spec_from_file_location("tt23_licence_fixtures", Path(__file__).with_name("test_data_licence_t_t22.py"))
_t22 = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_t22)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:  # 后端缺认证依赖：与认证组同样 skip
    pytest.skip(str(exc), allow_module_level=True)
_auth = _t22._auth

# 夹具复用（本模块独立 module 作用域临时库）
authdb = _auth.authdb
sql = _auth.sql
app_client = _auth.app_client
mkuser = _auth.mkuser
session = _auth.session
make_settings = _t22.make_settings  # 补一次性 X25519 封装公钥（运行时生成，私钥不落盘）
API = _auth.API
assert_err = _auth.assert_err
fields = _auth.fields
reg, new_name, new_pw, random_client_ip = _auth.reg, _auth.new_name, _auth.new_pw, _auth.random_client_ip
fake_licence, body_of, Rec, leak_count = _t22.fake_licence, _t22.body_of, _t22.Rec, _t22.leak_count
STATUS_KEYS, ADMIN_EXTRA = _t22.STATUS_KEYS, _t22.ADMIN_EXTRA

pytestmark = [pytest.mark.integration, pytest.mark.contract]

REPO = Path(__file__).resolve().parents[3]
TESTS_DIR = REPO / "tests"
V028 = "v0.2.8"
#: v0.2.8 规则在之后的版本仍然成立（T-T25：契约 v0.2.9 687159f 无回退）
V028_OR_LATER = (V028, "v0.2.9")
INGEST_STREAM = "ingest:requests"
#: 契约 v0.2.8 §5.1 IngestLicenceStatus 键集合
INGEST_LICENCE_KEYS = {"licence_id", "user_id", "username", "display_name", "status", "tier", "has_quant_pro", "expires_on",
                       "days_left", "calls_today", "daily_limit", "per_minute_limit", "calls_last_minute", "queue_depth",
                       "paused_until", "last_error_code", "last_error_at"}
#: §7.9 排序：status 依次为
INGEST_STATUS_ORDER = ["invalid", "ip_limited", "quota_exceeded", "expired", "paused_by_admin", "pending_verification", "active"]

# ---- 责任人（未实现时的 xfail 原因） ----
O_B02Y = "后端 T-B02y（契约 v0.2.8：枚举、security_types.py、eligibility.py、迁移 0009；已在本地 main 457a211/c55a42e，未推 origin）"
O_B03D = ("后端 T-B03d（契约 v0.2.8 #11–#14：注册蜜罐、管理员暂停按用户记录、重复 PUT 保留状态、AdminDataLicence.licence_id；"
          "已在本地 main 116cb7e，未推 origin）")
O_INGEST_STATUS = ("后端 T-B04a-x / T-B03d（契约 v0.2.8 #1：GET /admin/ingest/status 路由未挂载——本地 main 只有 "
                   "service.ingest_licences()，origin 与 main 都没有该端点）")
O_SEARCH = "后端 T-B06（契约 v0.2.7 #5 / v0.2.8 #4：GET /securities/search 未实现）"
O_PROFILE = "后端 T-B07 / T-B13（契约 v0.2.7 #6–#10 / v0.2.8 #5–#6：GET /securities/{code} 与个股数据接口未实现）"
O_QUOTES = "后端 T-B04a-x / T-B07（契约 v0.2.8 #8：/quotes、/bars、/terminal 未实现）"
O_IMPORT = "后端 T-B02x 后续（契约 v0.2.8 #9：ETF 成交导入、可转债 IMPORT_UNKNOWN_SECURITY；/imports 端点未实现）"
O_STRATEGY = "后端 策略实例 / 分类器 / H-01（契约 v0.2.7 #3 / v0.2.8 #10：/strategy-instances 端点未实现，暂无任务号）"
O_FRONT_ENUMS = "前端 T-F（契约 v0.2.8 #1：src/frontend/src/api/enums.ts CONTRACT_VERSION、security_type 加 etf、gap_reason 加 not_applicable）"
O_FRONT_HOME = "前端 T-F08 m1（契约 v0.2.8 #16：/ 重定向到 /today；d1fccf6 在本地 main，未推 origin）"


# =============================== 工具 ===============================
def backend_version(c: Any) -> str:
    r = c.get(f"{API}/meta/enums")
    assert r.status_code == 200, r.text[:200]
    return str(r.json().get("version", ""))


def require_v028(c: Any, owner: str) -> None:
    """后端声明的契约版本低于 v0.2.8 → imperative xfail（行为属 v0.2.8 新规则）。"""
    v = backend_version(c)
    if v not in V028_OR_LATER:
        pytest.xfail(f"{owner}；后端 /meta/enums.version = {v}")


def app_routes(app: Any) -> set[tuple[str, str]]:
    """应用实际可路由的 (方法, 完整路径)。兼容 FastAPI 新版 ``include_router`` 的惰性包装（``_IncludedRouter`` →
    ``effective_candidates()``）与旧版扁平 ``APIRoute``；只读 ``path`` / ``methods``，不依赖私有字段名之外的结构。"""
    out: set[tuple[str, str]] = set()

    def walk(nodes: Any) -> None:
        for n in nodes:
            if hasattr(n, "effective_candidates"):
                walk(n.effective_candidates())
            elif getattr(n, "path", None) and getattr(n, "methods", None):
                out.update((m, n.path) for m in n.methods)
            elif getattr(n, "routes", None):  # Mount / 子路由
                walk(n.routes)

    walk(getattr(app, "routes", []))
    return out


def has_route(c: Any, method: str, path: str) -> bool:
    return (method, f"{API}{path}") in app_routes(c.app)


def require_route(c: Any, method: str, path: str, owner: str) -> None:
    if not has_route(c, method, path):
        pytest.xfail(f"{owner}；{method} {path} 未挂载")


def admin_items(acall: Callable[..., Any]) -> list[dict[str, Any]]:
    """/admin/data-licences 全部元素（跟随 next_cursor 翻页）。"""
    out: list[dict[str, Any]] = []
    path = "/admin/data-licences"
    for _ in range(50):
        r = acall("GET", path)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        items = body["items"] if isinstance(body, dict) else body
        out += items
        nxt = body.get("next_cursor") if isinstance(body, dict) else None
        if not nxt:
            return out
        path = f"/admin/data-licences?cursor={nxt}"
    raise AssertionError("分页未结束")


def licence_ids(sql: Callable[..., Any], user_id: str) -> set[str]:
    return {r[0] for r in sql("SELECT id::text FROM app.user_data_licences WHERE user_id=:u", u=user_id)}


def live_row(sql: Callable[..., Any], user_id: str) -> Any:
    rows = sql("SELECT id::text AS id, status, paused_until FROM app.user_data_licences "
               "WHERE user_id=:u AND deleted_at IS NULL", u=user_id)
    assert len(rows) <= 1
    return rows[0] if rows else None


def verify_intents(rds: Any, ids: set[str]) -> int:
    """``ingest:requests`` 里指向这些证书行的验证意图条数（只带 licence_id，不含证书值）。"""
    if not rds.exists(INGEST_STREAM):
        return 0
    return sum(1 for _id, f in rds.xrange(INGEST_STREAM) if f.get("licence_id") in ids)


def set_status(sql: Callable[..., Any], user_id: str, status: str, paused_until: dt.datetime | None = None) -> None:
    sql("UPDATE app.user_data_licences SET status=:s, paused_until=:p, status_changed_at=now() "
        "WHERE user_id=:u AND deleted_at IS NULL", s=status, p=paused_until, u=user_id)


def put(call: Rec, lic: str, **kw: Any) -> Any:
    return call("PUT", "/me/data-licence", json=body_of(lic, **kw))


def secret_blobs(sql: Callable[..., Any], user_id: str) -> list[str]:
    """该用户全部证书行的密文与 HMAC 的常见编码（hex / base64 / base64url）。只在测试进程内比较，不输出。"""
    out: list[str] = []
    for ct, hm in sql("SELECT ciphertext, licence_hmac FROM app.user_data_licences WHERE user_id=:u", u=user_id):
        for raw in (ct, hm):
            if raw is None:
                continue
            b = bytes(raw) if not isinstance(raw, str) else raw.encode()
            out += [b.hex(), base64.b64encode(b).decode(), base64.urlsafe_b64encode(b).decode().rstrip("=")]
    return out


def secret_leaks(blobs: list[str], hay: str, k: int = 16) -> int:
    return sum(1 for s in blobs for i in range(0, max(len(s) - k + 1, 1), 4) if s[i : i + k] in hay)


def backend_module(name: str, owner: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError:
        pytest.xfail(f"{owner}；{name} 不存在")


def test_route_table_controls(app_client: Callable[..., Any]) -> None:
    """门控自检：路由表读取对已知端点为真（阳性），对不存在的端点为假（阴性）；否则“未挂载 → xfail”会把真实失败藏起来。"""
    c = app_client()
    for m, p in (("GET", "/meta/enums"), ("POST", "/auth/register"), ("PUT", "/me/data-licence"),
                 ("GET", "/admin/data-licences"), ("POST", "/admin/data-licences/{user_id}/pause")):
        assert has_route(c, m, p), (m, p)
    assert not has_route(c, "GET", "/no-such-endpoint-t-t23")
    assert not has_route(c, "DELETE", "/meta/enums")


# =============================== 第 1 条：前端 CONTRACT_VERSION ===============================
FRONT_ENUMS = REPO / "src" / "frontend" / "src" / "api" / "enums.ts"


@pytest.mark.unit
def test_01_frontend_contract_version_and_enums() -> None:
    """第 1 条（前端部分）：``src/frontend/src/api/enums.ts`` 的 ``CONTRACT_VERSION`` 为 v0.2.8，
    ``security_type`` = stock, cdr, etf, index，``gap_reason`` 含 not_applicable。后端 / 文档部分见 test_meta_enums.py。"""
    if not FRONT_ENUMS.is_file():
        pytest.skip("工作树没有 src/frontend")
    src = FRONT_ENUMS.read_text(encoding="utf-8")
    m = re.search(r"CONTRACT_VERSION\s*=\s*'(v[0-9.]+)'", src)
    assert m, "enums.ts 没有 CONTRACT_VERSION"
    if m.group(1) not in V028_OR_LATER:
        pytest.xfail(f"{O_FRONT_ENUMS}；当前 {m.group(1)}")
    st = re.search(r"security_type:\s*\[([^\]]*)\]", src)
    gr = re.search(r"gap_reason:\s*\[([^\]]*)\]", src)
    assert st and re.findall(r"'([a-z_]+)'", st.group(1)) == ["stock", "cdr", "etf", "index"]
    assert gr and "not_applicable" in re.findall(r"'([a-z_]+)'", gr.group(1))


# =============================== 第 2–4 条：/admin/ingest/status 与 licence_id ===============================
@pytest.fixture
def two_licences(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any], sql: Callable[..., Any]) -> SimpleNamespace:
    """A active、B quota_exceeded（paused_until 1 小时后）、C 未设置；外加管理员会话。证书值只留在内存。"""
    a, b, c = session(), session(), session()
    la, lb = fake_licence(), fake_licence()
    assert put(Rec(a), la).status_code == 202
    assert put(Rec(b), lb).status_code == 202
    set_status(sql, a.user.id, "active")
    set_status(sql, b.user.id, "quota_exceeded", dt.datetime.now(dt.UTC) + dt.timedelta(hours=1))
    admin = session(mkuser(role="admin"))
    return SimpleNamespace(a=a, b=b, c=c, la=la, lb=lb, admin=admin, acall=Rec(admin))


def _check_ingest_rows(rows: list[dict[str, Any]], tl: SimpleNamespace, items: list[dict[str, Any]]) -> None:
    by_user = {}
    for i, row in enumerate(rows):
        assert set(row) == INGEST_LICENCE_KEYS, sorted(set(row) ^ INGEST_LICENCE_KEYS)
        by_user.setdefault(str(row["user_id"]), []).append(i)
    ia, ib = by_user.get(str(tl.a.user.id), []), by_user.get(str(tl.b.user.id), [])
    assert len(ia) == 1 and len(ib) == 1, "A、B 各一行"
    assert str(tl.c.user.id) not in by_user, "not_set 用户不列出"
    assert ib[0] < ia[0], "quota_exceeded 排在 active 前"
    ranks = [INGEST_STATUS_ORDER.index(r["status"]) for r in rows]
    assert ranks == sorted(ranks), "按 §7.9 状态顺序"
    adm = {str(x["user_id"]): x for x in items}
    for who, idx in ((tl.a, ia[0]), (tl.b, ib[0])):
        row, item = rows[idx], adm[str(who.user.id)]
        assert row["queue_depth"] == item["queue_depth"] and row["calls_today"] == item["calls_today"]
        assert row["status"] == item["status"]
        if "licence_id" in item:  # 第 4 条：同一证书 licence_id 一致
            assert row["licence_id"] == item["licence_id"]
    assert rows[ia[0]]["status"] == "active" and rows[ib[0]]["status"] == "quota_exceeded"


def test_02_admin_ingest_status_licences_per_licence(two_licences: SimpleNamespace, sql: Callable[..., Any]) -> None:
    """第 2 条（HTTP）：没有 ``licence`` 键，有 ``licences`` / ``licences_truncated``；A、B 各一行、键集合 = IngestLicenceStatus、
    B 在 A 前、not_set 不出现；queue_depth、calls_today 与 /admin/data-licences 一致。
    第 3 条（ingest/status 部分）：响应全文无测试证书 ≥4 位子串、无密文 / HMAC。"""
    tl = two_licences
    require_route(tl.admin.client, "GET", "/admin/ingest/status", O_INGEST_STATUS)
    r = tl.acall("GET", "/admin/ingest/status")
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert "licence" not in body and isinstance(body["licences"], list) and body["licences_truncated"] is False
    _check_ingest_rows(body["licences"], tl, admin_items(tl.acall))
    for lic, u in ((tl.la, tl.a), (tl.lb, tl.b)):
        assert leak_count(lic, r.text) == 0, "ingest/status 含证书片段"
        assert secret_leaks(secret_blobs(sql, u.user.id), r.text) == 0, "ingest/status 含密文或 HMAC"


def test_02_service_ingest_licences_rules(two_licences: SimpleNamespace, authdb: SimpleNamespace, sql: Callable[..., Any],
                                         make_settings: Callable[..., Any]) -> None:
    """第 2–4 条（领域层，端点未挂载前先验）：``service.ingest_licences`` 返回的行满足第 2 条全部规则，并与
    /admin/data-licences 的 licence_id、queue_depth、calls_today 一致；行内无证书 / 密文 / HMAC 片段。"""
    svc = backend_module("app.licences.service", O_B03D)
    if not hasattr(svc, "ingest_licences"):
        pytest.xfail(f"{O_B03D}；service.ingest_licences 不存在")
    tl = two_licences
    settings = make_settings(database_url=authdb.url, redis_url=authdb.redis_url)
    with authdb.engine.connect() as conn:
        rows, truncated = svc.ingest_licences(conn, authdb.redis, settings)
    assert truncated is False
    items = admin_items(tl.acall)
    assert all("licence_id" in x for x in items), "第 4 条：AdminDataLicence 缺 licence_id"
    _check_ingest_rows(rows, tl, items)
    text = repr(rows)
    for lic, u in ((tl.la, tl.a), (tl.lb, tl.b)):
        assert leak_count(lic, text) == 0
        assert secret_leaks(secret_blobs(sql, u.user.id), text) == 0


def test_03_admin_data_licences_no_licence_ciphertext_or_hmac(two_licences: SimpleNamespace, sql: Callable[..., Any]) -> None:
    """第 3 条（/admin/data-licences 部分，v0.2.6 起即成立）：响应全文无任一测试证书 ≥4 位子串，也无密文或 HMAC（hex/base64）。"""
    tl = two_licences
    r = tl.acall("GET", "/admin/data-licences")
    assert r.status_code == 200, r.text[:300]
    text = "\n".join(tl.acall.bodies)
    for lic, u in ((tl.la, tl.a), (tl.lb, tl.b)):
        assert leak_count(lic, text) == 0, "data-licences 含证书片段"
        blobs = secret_blobs(sql, u.user.id)
        assert blobs, "测试前提：库内有密文与 HMAC"
        assert secret_leaks(blobs, text) == 0, "data-licences 含密文或 HMAC"


@pytest.mark.unit
def test_03_secret_leak_detector_controls() -> None:
    """第 3 条检测器自检：阳性（夹在 JSON 里的 hex/base64 片段）必中；阴性（另一组随机字节）不中。"""
    import os  # noqa: PLC0415

    raw = os.urandom(32)
    blobs = [raw.hex(), base64.b64encode(raw).decode()]
    assert secret_leaks(blobs, '{"x": "' + raw.hex()[8:30] + '"}') >= 1
    assert secret_leaks(blobs, '{"x": "' + base64.b64encode(raw).decode()[4:24] + '"}') >= 1
    other = os.urandom(32)
    assert secret_leaks(blobs, other.hex() + base64.b64encode(other).decode()) == 0


def test_04_admin_data_licences_licence_id(two_licences: SimpleNamespace, sql: Callable[..., Any]) -> None:
    """第 4 条：元素含 ``licence_id``，等于该用户当前证书行 id；未设置证书的用户为 null。"""
    tl = two_licences
    require_v028(tl.admin.client, O_B03D)
    items = {str(x["user_id"]): x for x in admin_items(tl.acall)}
    for u in (tl.a, tl.b):
        assert items[str(u.user.id)]["licence_id"] == live_row(sql, u.user.id).id
    assert items[str(tl.c.user.id)]["licence_id"] is None
    assert set(items[str(tl.c.user.id)]) == STATUS_KEYS | ADMIN_EXTRA | {"licence_id"}


# =============================== 第 5 条：openapi 无 /admin；每个管理端接口有契约测试 ===============================
def test_05_openapi_has_no_admin_paths(app_client: Callable[..., Any]) -> None:
    """第 5 条：``openapi.json`` 的 paths 没有任何 ``/admin``（管理端只在契约文档里描述）。"""
    r = app_client().get(f"{API}/openapi.json")
    assert r.status_code == 200, r.text[:200]
    paths = list(r.json().get("paths", {}))
    assert paths, "openapi 没有 paths"
    assert [p for p in paths if "/admin" in p] == []
    assert "/admin" not in r.text


def _route_regex(path: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}]+\})", path)
    rx = "".join(r"(?:\{[^}]+\}|[^/\s\"'?]+)" if p.startswith("{") else re.escape(p) for p in parts)
    return re.compile(rx + r"(?![A-Za-z0-9_-])")


def test_05_every_mounted_admin_endpoint_has_contract_test(app_client: Callable[..., Any]) -> None:
    """第 5 条：后端挂载的每个 §7.9 ``/admin/*`` 接口（方法 + 路径）都在 tests/ 里有契约结构测试引用（本文件除外）。
    §7.9 中尚未挂载的接口（ingest/status、ingest pause/resume、realtime-settings、llm、plans、evaluation、audit-logs）
    挂载时此用例会要求补测试。"""
    c = app_client()
    admin = sorted((m, p[len(API):]) for m, p in app_routes(c.app) if "/admin" in p and m not in {"HEAD", "OPTIONS"})
    assert admin, "后端没有任何 /admin 路由"
    me = Path(__file__).resolve()
    texts = [p.read_text(encoding="utf-8") for p in sorted(TESTS_DIR.rglob("*.py")) if p.resolve() != me]
    missing = []
    for method, path in admin:
        rx = _route_regex(path)
        verb = method.lower()
        hit = any(rx.search(t) and re.search(rf"\b{verb}\b|\"{method}\"|'{method}'", t, re.I) for t in texts)
        if not hit:
            missing.append(f"{method} {path}")
    assert missing == [], "这些管理端接口没有契约测试：" + ", ".join(missing)


# =============================== 第 6–9 条：ETF ===============================
SEED = [("600981.SH", "stock", "测廿三股份", "main"), ("689981.SH", "cdr", "测廿三存托", "star"),
        ("510981.SH", "etf", "测廿三ETF", None), ("000981.SH", "index", "测廿三指数", None)]
RANK = {"stock": 0, "cdr": 1, "etf": 2, "index": 3}
ETF_CODE = "510981.SH"
CB_CODE = "113981.SH"  # 可转债：本版不收录


def seed_securities(sql: Callable[..., Any]) -> None:
    for code, typ, name, board in SEED:
        sql("INSERT INTO market.securities (code, type, name, exchange, board, listing_status, name_norm) "
            "VALUES (:c, :t, :n, 'SH', :b, 'listed', :n) ON CONFLICT (code) DO NOTHING", c=code, t=typ, n=name, b=board)


@pytest.mark.unit
def test_06_09_security_types_domain_rules() -> None:
    """第 6–8 条（领域层，T-B02y）：默认搜索类型 stock,cdr,etf（不含 index）；排序 stock > cdr > etf > index；
    ETF 资料 null / [] 字段；ETF 四个个股数据集 → not_applicable，指数 financials/fund-flows 仍 no_source；
    价格小数位 ETF 3 / 股票 2；ETF 整手 100。"""
    st = backend_module("app.marketdata.security_types", O_B02Y)
    assert [str(t) for t in st.DEFAULT_SEARCH_TYPES] == ["stock", "cdr", "etf"]
    assert sorted(["index", "etf", "cdr", "stock"], key=st.search_sort_key) == ["stock", "cdr", "etf", "index"]
    assert st.search_sort_key("convertible_bond") > st.search_sort_key("index")
    assert st.ETF_NULL_PROFILE_FIELDS == {"board", "list_date_basis", "risk_flag", "total_shares", "float_shares", "industry"}
    assert st.ETF_EMPTY_PROFILE_FIELDS == {"concepts"}
    for ds in ("financials", "fund-flows", "factors", "announcements"):
        assert st.dataset_gap("etf", ds) == {"key": ds.replace("-", "_"), "reason": "not_applicable"}
        assert st.dataset_gap("stock", ds) is None and st.dataset_gap("cdr", ds) is None
    assert st.dataset_gap("index", "financials")["reason"] == "no_source"
    assert st.dataset_gap("index", "fund-flows")["reason"] == "no_source"
    with pytest.raises(ValueError):
        st.dataset_gap("etf", "quotes")
    assert (st.price_dp("etf"), st.price_dp("stock"), st.price_dp("cdr")) == (3, 2, 2)
    assert st.etf_lot_irregular(150) and not st.etf_lot_irregular(200)


@pytest.mark.unit
def test_09_strategy_eligibility_domain_rules() -> None:
    """第 9 条（领域层，T-B02y）：只有 stock/cdr 运行策略；ETF → 422 INSTANCE_SCOPE_INVALID
    ``{scope, security_code, security_type: etf, issue: security_type_not_supported}``；未知 → issue unknown_security、
    不带 security_type；候选池剔除 ETF / 指数 / 未知（account 范围跳过 ETF 不报错）。"""
    el = backend_module("app.strategy.eligibility", O_B02Y)
    errors = importlib.import_module("app.common.errors")
    assert [el.is_strategy_eligible(t) for t in ("stock", "cdr", "etf", "index", None, "bond")] == [True, True, False, False,
                                                                                                    False, False]
    el.ensure_strategy_eligible("600981.SH", "stock")
    with pytest.raises(errors.AppError) as ei:
        el.ensure_strategy_eligible(ETF_CODE, "etf")
    e = ei.value
    assert (str(e.code), e.status_code) == ("INSTANCE_SCOPE_INVALID", 422)
    assert e.details == {"scope": "security", "security_code": ETF_CODE, "security_type": "etf",
                         "issue": "security_type_not_supported"}
    with pytest.raises(errors.AppError) as ei:
        el.ensure_strategy_eligible(CB_CODE, None)
    assert ei.value.details == {"scope": "security", "security_code": CB_CODE, "issue": "unknown_security"}
    kept, dropped = el.split_strategy_universe(
        ["600981.SH", ETF_CODE, "689981.SH", "000981.SH", CB_CODE, "600981.SH"],
        {"600981.SH": "stock", ETF_CODE: "etf", "689981.SH": "cdr", "000981.SH": "index"})
    assert kept == ["600981.SH", "689981.SH"]
    assert set(dropped) == {ETF_CODE, "000981.SH", CB_CODE}


def test_09_db_trigger_rejects_non_strategy_security(sql: Callable[..., Any]) -> None:
    """第 9 条（数据库兜底，迁移 0009）：``app.reject_non_strategy_security()`` 挂在 strategy_instances 与 candidate_signals。"""
    fn = sql("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
             "WHERE n.nspname='app' AND p.proname='reject_non_strategy_security'")[0][0]
    if not fn:
        pytest.xfail(f"{O_B02Y}；迁移 0009 未应用")
    trg = {(r[0], r[1]) for r in sql(
        "SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_proc p ON p.oid=t.tgfoid "
        "WHERE p.proname='reject_non_strategy_security' AND NOT t.tgisinternal AND t.tgparentid = 0")}
    assert {r for r, _ in trg} == {"strategy_instances", "candidate_signals"}  # 分区上的克隆触发器（tgparentid≠0）不计


def test_06_etf_search(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    """第 6 条：默认 types 搜得到 ETF（type=etf、board=null）；types=stock,cdr 搜不到；同层 stock > cdr > etf > index；可转债搜不到。"""
    s = session()
    require_route(s.client, "GET", "/securities/search", O_SEARCH)
    seed_securities(sql)
    call = Rec(s)

    def items(q: str, **params: str) -> list[dict[str, Any]]:
        r = call("GET", "/securities/search", params={"q": q, **params})
        assert r.status_code == 200, r.text[:300]
        return r.json()["items"]

    got = [x for x in items("测廿三") if x["code"] in {c for c, *_ in SEED}]
    etf = [x for x in got if x["code"] == ETF_CODE]
    assert len(etf) == 1 and etf[0]["type"] == "etf" and etf[0]["board"] is None
    assert "000981.SH" not in {x["code"] for x in got}, "默认 types 不含 index"
    assert ETF_CODE not in {x["code"] for x in items("测廿三", types="stock,cdr")}
    allt = [x for x in items("测廿三", types="stock,cdr,etf,index") if x["code"] in {c for c, *_ in SEED}]
    ranks = [RANK[x["type"]] for x in allt]
    assert ranks == sorted(ranks) and len(allt) == 4
    assert items(CB_CODE[:6]) == [] or CB_CODE not in {x["code"] for x in items(CB_CODE[:6])}


DATASETS = ("financials", "fund-flows", "factors", "announcements")


def test_07_etf_profile_and_datasets(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    """第 7 条：ETF 资料 board/risk_flag/股本/industry 为 null、concepts=[]、无 gap；四个个股数据集 200、空 items、
    data_status=unavailable、gaps[0].reason=not_applicable；指数 financials 仍 no_source。"""
    s = session()
    require_route(s.client, "GET", "/securities/{code}", O_PROFILE)
    seed_securities(sql)
    call = Rec(s)
    p = call("GET", f"/securities/{ETF_CODE}")
    assert p.status_code == 200, p.text[:300]
    prof = p.json()
    for k in ("board", "risk_flag", "total_shares", "float_shares", "industry"):
        assert prof.get(k, "MISSING") is None, k
    assert prof["concepts"] == [] and not prof.get("gaps")
    for ds in DATASETS:
        require_route(s.client, "GET", f"/securities/{{code}}/{ds}", O_PROFILE)
        r = call("GET", f"/securities/{ETF_CODE}/{ds}")
        assert r.status_code == 200, (ds, r.text[:300])
        b = r.json()
        assert b["items"] == [] and b["data_status"] == "unavailable" and b["gaps"][0]["reason"] == "not_applicable", ds
    r = call("GET", "/securities/000981.SH/financials")
    assert r.status_code == 200 and r.json()["gaps"][0]["reason"] == "no_source"


def test_08_etf_quotes_bars_terminal_three_decimals(session: Callable[..., SimpleNamespace]) -> None:
    """第 8 条：ETF 的 /quotes、/bars、/terminal 与股票同口径，价格为 3 位小数字符串。需要行情夹具（无上游）。"""
    s = session()
    for path in ("/quotes", "/bars", "/terminal"):
        require_route(s.client, "GET", path, O_QUOTES)
    pytest.xfail(f"{O_QUOTES}；端点挂载后补行情夹具再严格断言（3 位小数字符串）")


def test_08_etf_trades_import_and_cb_unknown(session: Callable[..., SimpleNamespace]) -> None:
    """第 8 条：ETF 成交可导入并重建持仓；可转债行 → IMPORT_UNKNOWN_SECURITY。"""
    s = session()
    require_route(s.client, "POST", "/imports", O_IMPORT)
    pytest.xfail(f"{O_IMPORT}；端点挂载后补导入夹具再严格断言")


def test_09_etf_strategy_instance_scope(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    """第 9 条（HTTP）：scope=security 指 ETF → 422 INSTANCE_SCOPE_INVALID{security_type: etf, issue: security_type_not_supported}；
    scope=account → 201 且运行时跳过 ETF；分类器对 ETF 计 0 分不建 proposed；H-01 不挂 ETF。"""
    s = session()
    require_route(s.client, "POST", "/strategy-instances", O_STRATEGY)
    seed_securities(sql)
    r = Rec(s)("POST", "/strategy-instances", json={"scope": "security", "security_code": ETF_CODE, "template_id": "S-01"})
    err = assert_err(r, 422, "INSTANCE_SCOPE_INVALID")
    assert err["details"]["security_type"] == "etf" and err["details"]["issue"] == "security_type_not_supported"
    pytest.xfail(f"{O_STRATEGY}；scope=account / 分类器 / H-01 部分待端点与夹具")


# =============================== 第 10 条：注册蜜罐 ===============================
def _now_ms() -> int:
    return int(time.time() * 1000)


def _user_count(sql: Callable[..., Any], name: str) -> int:
    return sql("SELECT count(*) FROM app.users WHERE username=:u", u=name)[0][0]


def _honeypot_audits(sql: Callable[..., Any], since: Any) -> list[Any]:
    return sql("SELECT detail::text AS detail, actor_id, target_id FROM app.audit_logs "
               "WHERE action='auth.register_honeypot' AND at >= :t ORDER BY at", t=since)


def _db_now(sql: Callable[..., Any]) -> Any:
    return sql("SELECT now()")[0][0]


@pytest.mark.parametrize("trap", ["website", "too_fast_1s", "future"])
def test_10_honeypot_hit_201_same_shape_no_user(app_client: Callable[..., Any], sql: Callable[..., Any], trap: str) -> None:
    """第 10 条：website 非空 / form_started_at 1 秒前 / 未来时间 → 201，键集合与正常注册相同，不建用户；
    一条 auth.register_honeypot 审计，detail 不含用户名、口令、显示名、申请说明。"""
    c = app_client("open")
    require_v028(c, O_B03D)
    name, pw, note = new_name(), new_pw(), "申请说明" + uuid.uuid4().hex[:8]
    extra = {"website": "http://example.invalid/" + uuid.uuid4().hex[:6]} if trap == "website" else {
        "form_started_at": _now_ms() - 1000 if trap == "too_fast_1s" else _now_ms() + 60_000}
    t0 = _db_now(sql)
    r = c.post(f"{API}/auth/register", json=reg(name, pw, apply_note=note, **extra))
    assert r.status_code == 201, r.text[:300]
    body = r.json()
    assert set(body) == {"id", "username", "status"} and body["username"] == name and body["status"] == "pending"
    uuid.UUID(body["id"])
    assert "set-cookie" not in r.headers
    assert _user_count(sql, name) == 0
    assert sql("SELECT count(*) FROM app.users WHERE id=:i", i=body["id"])[0][0] == 0
    audits = _honeypot_audits(sql, t0)
    assert len(audits) == 1
    detail = audits[0].detail or ""
    for secret in (name, pw, note, "测试用户", extra.get("website", "\x00")):
        assert secret not in detail, "审计 detail 含表单内容"
    assert audits[0].actor_id is None


@pytest.mark.parametrize("extra", [{}, {"website": ""}, {"website": "   "}, {"form_started_at": "AGO5"}],
                         ids=["absent", "website_empty", "website_blank", "started_5s_ago"])
def test_10_honeypot_not_hit_registers_normally(app_client: Callable[..., Any], sql: Callable[..., Any],
                                                extra: dict[str, Any]) -> None:
    """第 10 条：两字段不传、website 为空或空白、form_started_at 为 5 秒前 → 正常建用户；两字段不触发 400。"""
    c = app_client("open")
    require_v028(c, O_B03D)
    if extra.get("form_started_at") == "AGO5":
        extra = {"form_started_at": _now_ms() - 5000}
    name = new_name()
    t0 = _db_now(sql)
    r = c.post(f"{API}/auth/register", json=reg(name, new_pw(), **extra))
    assert r.status_code == 201, r.text[:300]
    assert _user_count(sql, name) == 1 and _honeypot_audits(sql, t0) == []


@pytest.mark.parametrize("extra", [{"nickname": "x"}, {"form_started_at": "1700000000000"}, {"form_started_at": 1.5},
                                   {"form_started_at": True}], ids=["unknown_field", "fsa_string", "fsa_float", "fsa_bool"])
def test_10_other_unknown_fields_and_bad_form_started_at_are_400(app_client: Callable[..., Any], sql: Callable[..., Any],
                                                                 extra: dict[str, Any]) -> None:
    """第 10 条：其他未知字段仍 400；form_started_at 不是整数 → 400 VALIDATION_ERROR；不建用户。"""
    c = app_client("open")
    require_v028(c, O_B03D)
    name = new_name()
    assert_err(c.post(f"{API}/auth/register", json=reg(name, new_pw(), **extra)), 400, "VALIDATION_ERROR")
    assert _user_count(sql, name) == 0


def test_10_honeypot_invite_mode_does_not_consume_invite(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                                         app_client: Callable[..., Any], sql: Callable[..., Any]) -> None:
    """第 10 条：invite 模式蜜罐命中 → 201、不建用户、邀请码未消耗（之后同一邀请码仍可正常注册）。"""
    admin = session(mkuser(role="admin"))
    require_v028(admin.client, O_B03D)
    inv = Rec(admin)("POST", "/admin/invites", json={"ttl_h": 24})
    assert inv.status_code == 201, inv.text[:300]
    code, inv_id = inv.json()["code"], inv.json()["id"]
    c = app_client("invite")
    name = new_name()
    r = c.post(f"{API}/auth/register", json=reg(name, new_pw(), invite_code=code, apply_note="说明", website="x"))
    assert r.status_code == 201 and set(r.json()) == {"id", "username", "status"}
    assert _user_count(sql, name) == 0
    assert sql("SELECT used_count, used_at FROM app.invite_codes WHERE id=:i", i=inv_id)[0] == (0, None)
    name2 = new_name()
    r2 = app_client("invite").post(f"{API}/auth/register", json=reg(name2, new_pw(), invite_code=code, apply_note="说明"))
    assert r2.status_code == 201, r2.text[:300]
    assert _user_count(sql, name2) == 1
    assert sql("SELECT used_count FROM app.invite_codes WHERE id=:i", i=inv_id)[0][0] == 1


def test_10_honeypot_hits_count_toward_ip_rate_limit(app_client: Callable[..., Any], sql: Callable[..., Any]) -> None:
    """第 10 条：蜜罐命中同样计入 IP 限速——同一 IP 5 次命中后，第 6 次（即使是正常请求）→ 429 RATE_LIMITED。"""
    ip = random_client_ip()
    c = app_client("open", ip=ip)
    require_v028(c, O_B03D)
    for _ in range(5):
        assert c.post(f"{API}/auth/register", json=reg(new_name(), new_pw(), website="x")).status_code == 201
    name = new_name()
    assert_err(app_client("open", ip=ip).post(f"{API}/auth/register", json=reg(name, new_pw())), 429, "RATE_LIMITED")
    assert _user_count(sql, name) == 0


def test_10_honeypot_closed_mode_is_503(app_client: Callable[..., Any], sql: Callable[..., Any]) -> None:
    """第 10 条：closed 模式先于蜜罐 → 503 REGISTRATION_CLOSED，无审计。"""
    c = app_client("closed")
    require_v028(c, O_B03D)
    t0 = _db_now(sql)
    assert_err(c.post(f"{API}/auth/register", json=reg(new_name(), new_pw(), website="x")), 503, "REGISTRATION_CLOSED")
    assert _honeypot_audits(sql, t0) == []


# =============================== 第 11 条：管理员暂停 ===============================
def _admin_pause(acall: Rec, uid: str, pause: bool) -> None:
    r = acall("POST", f"/admin/data-licences/{uid}/{'pause' if pause else 'resume'}", json={"reason": "T-T23"})
    assert r.status_code == 204, r.text[:300]


def test_11_pause_put_delete_test_resume(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                          sql: Callable[..., Any], authdb: SimpleNamespace) -> None:
    """第 11 条：暂停中 PUT → 202 paused_by_admin、不入队验证；DELETE 后 GET 仍 paused_by_admin，再 PUT 仍暂停；
    POST /test → 409 DATA_LICENCE_UNAVAILABLE{status: paused_by_admin}；resume → pending_verification 且入队验证。"""
    s = session()
    require_v028(s.client, O_B03D)
    call, admin = Rec(s), Rec(session(mkuser(role="admin")))
    l1, l2, l3 = fake_licence(), fake_licence(), fake_licence()
    assert put(call, l1).status_code == 202
    _admin_pause(admin, s.user.id, True)
    before = verify_intents(authdb.redis, licence_ids(sql, s.user.id))
    r = put(call, l2)
    assert r.status_code == 202 and r.json()["status"] == "paused_by_admin", r.text[:300]
    ids = licence_ids(sql, s.user.id)
    assert verify_intents(authdb.redis, ids) == before, "暂停期间 PUT 不得入队验证"
    assert call("DELETE", "/me/data-licence").status_code == 204
    g = call("GET", "/me/data-licence")
    assert g.status_code == 200 and g.json()["status"] == "paused_by_admin"
    assert call("GET", "/me").json()["data_licence_status"] == "paused_by_admin"
    r = put(call, l3)
    assert r.status_code == 202 and r.json()["status"] == "paused_by_admin"
    err = assert_err(call("POST", "/me/data-licence/test"), 409, "DATA_LICENCE_UNAVAILABLE")
    assert err["details"] == {"status": "paused_by_admin"}
    ids = licence_ids(sql, s.user.id)
    assert verify_intents(authdb.redis, ids) == before
    used = sql("SELECT count(*) FROM ops.ingest_request_log WHERE licence_id::text = ANY(:ids)", ids=list(ids))[0][0]
    assert used == 0, "暂停期间不得以该用户任何证书行发出采集请求"
    _admin_pause(admin, s.user.id, False)
    assert call("GET", "/me/data-licence").json()["status"] == "pending_verification"
    live = live_row(sql, s.user.id)
    assert verify_intents(authdb.redis, {live.id}) == 1, "恢复后入队一次验证"
    text = "\n".join(call.bodies + admin.bodies)
    assert all(leak_count(x, text) == 0 for x in (l1, l2, l3))


def test_11_pause_delete_resume_is_not_set(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                           sql: Callable[..., Any]) -> None:
    """第 11 条：暂停 → DELETE → resume → GET 为 not_set（暂停记录解除，不残留）。"""
    s = session()
    require_v028(s.client, O_B03D)
    call, admin = Rec(s), Rec(session(mkuser(role="admin")))
    assert put(call, fake_licence()).status_code == 202
    _admin_pause(admin, s.user.id, True)
    assert call("DELETE", "/me/data-licence").status_code == 204
    assert call("GET", "/me/data-licence").json()["status"] == "paused_by_admin"
    _admin_pause(admin, s.user.id, False)
    assert call("GET", "/me/data-licence").json()["status"] == "not_set"
    assert call("GET", "/me").json()["data_licence_status"] == "not_set"
    assert live_row(sql, s.user.id) is None


# =============================== 第 12 条：重复 PUT 同一证书 ===============================
@pytest.mark.parametrize("status", ["quota_exceeded", "ip_limited"])
def test_12_repeat_put_keeps_cooldown_state(session: Callable[..., SimpleNamespace], sql: Callable[..., Any],
                                            authdb: SimpleNamespace, status: str) -> None:
    """第 12 条：quota_exceeded / ip_limited 时重复 PUT 同一证书 → 202，状态与 paused_until 不变，同一行（licence_id 不变），不入队验证。"""
    s = session()
    require_v028(s.client, O_B03D)
    call, lic = Rec(s), fake_licence()
    assert put(call, lic).status_code == 202
    set_status(sql, s.user.id, status, dt.datetime.now(dt.UTC) + dt.timedelta(hours=2))
    row0 = live_row(sql, s.user.id)
    g0 = call("GET", "/me/data-licence").json()
    n0 = verify_intents(authdb.redis, {row0.id})
    r = put(call, lic, tier="monthly")
    assert r.status_code == 202, r.text[:300]
    assert r.json()["status"] == status and r.json()["paused_until"] == g0["paused_until"] and r.json()["tier"] == "monthly"
    row1 = live_row(sql, s.user.id)
    assert (row1.id, row1.status, row1.paused_until) == (row0.id, status, row0.paused_until)
    assert verify_intents(authdb.redis, licence_ids(sql, s.user.id)) == n0
    assert leak_count(lic, "\n".join(call.bodies)) == 0


def test_12_repeat_put_active_with_future_paused_until_kept(session: Callable[..., SimpleNamespace], sql: Callable[..., Any],
                                                            authdb: SimpleNamespace) -> None:
    """第 12 条：active 且 paused_until 未到期 → 重复 PUT 保留 active 与 paused_until，不验证。"""
    s = session()
    require_v028(s.client, O_B03D)
    call, lic = Rec(s), fake_licence()
    assert put(call, lic).status_code == 202
    set_status(sql, s.user.id, "active", dt.datetime.now(dt.UTC) + dt.timedelta(minutes=30))
    row0 = live_row(sql, s.user.id)
    n0 = verify_intents(authdb.redis, {row0.id})
    r = put(call, lic)
    assert r.status_code == 202 and r.json()["status"] == "active" and r.json()["paused_until"] is not None
    row1 = live_row(sql, s.user.id)
    assert (row1.id, row1.status, row1.paused_until) == (row0.id, "active", row0.paused_until)
    assert verify_intents(authdb.redis, licence_ids(sql, s.user.id)) == n0


def test_12_repeat_put_invalid_goes_pending_and_verifies(session: Callable[..., SimpleNamespace], sql: Callable[..., Any],
                                                         authdb: SimpleNamespace) -> None:
    """第 12 条：invalid 时重复 PUT 同一证书 → pending_verification，并入队一次验证。"""
    s = session()
    require_v028(s.client, O_B03D)
    call, lic = Rec(s), fake_licence()
    assert put(call, lic).status_code == 202
    set_status(sql, s.user.id, "invalid")
    ids0 = licence_ids(sql, s.user.id)
    n0 = verify_intents(authdb.redis, ids0)
    r = put(call, lic)
    assert r.status_code == 202 and r.json()["status"] == "pending_verification", r.text[:300]
    assert verify_intents(authdb.redis, licence_ids(sql, s.user.id)) == n0 + 1


# =============================== 第 13 条：前端首页 ===============================
ROUTES_TSX = REPO / "src" / "frontend" / "src" / "app" / "routes.tsx"


@pytest.mark.unit
def test_13_frontend_root_redirects_to_today() -> None:
    """第 13 条（静态）：根路由 ``/`` 的 index 子路由 ``<Navigate to="/today" replace />``，且存在 ``today`` 子路由。"""
    if not ROUTES_TSX.is_file():
        pytest.skip("工作树没有 src/frontend/src/app/routes.tsx")
    src = ROUTES_TSX.read_text(encoding="utf-8")
    root = re.search(r"path:\s*'/'\s*,[\s\S]*?children:\s*\[([\s\S]*?)\n\s*\]", src)
    assert root, "routes.tsx 没有 path '/' 的外壳路由"
    m = re.search(r"index:\s*true\s*,\s*element:\s*<Navigate\s+to=\"(/[^\"]*)\"", root.group(1))
    assert m, "'/' 没有 index 重定向"
    if m.group(1) != "/today":
        pytest.xfail(f"{O_FRONT_HOME}；当前重定向到 {m.group(1)}")
    assert "replace" in root.group(1)[m.start() : m.start() + 120]
    assert re.search(r"path:\s*'today'", root.group(1))
