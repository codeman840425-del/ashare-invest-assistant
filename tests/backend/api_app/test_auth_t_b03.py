"""认证/会话/CSRF/改密/me（T-B03，契约 §1.3、§4、§7.1；plan §3.6）——真实 PostgreSQL + Redis（T-T01d）。

- 后端没有 ``app/auth/sessions.py``（T-B03 未合入）时整组 skip；缺 argon2/alembic/sqlalchemy/redis 时 skip（原因写明）。
- 每个模块新建一个独立数据库（``tt01d_auth_<随机>``），``alembic upgrade head`` 后测试，结束即删除；
  Redis 只按本组用户的键断言，不 ``FLUSHDB``，可与其他用例共用实例。
- 用户名、口令、主密钥全部运行时随机生成，不含任何真实凭据；不连外网、不调用任何行情接口。
- 契约 v0.2.3 #24–#27（T-A05，架构师 7c62f59，尚未推到 origin）：用户名 4–32、会话绝对 30 天 + 改密轮换、
  注册 ``apply_note`` 与邀请码（#26 同意书部分已被 v0.2.5 作废，用例已删除）。
  后端未实现的条目用 ``xfail(strict=True)``，原因写明负责任务（T-B03 跟进 / T-B03c）。
- 契约 v0.2.5（T-A06 bd33f83，用户 2026-11-02 决定不做同意流程与风险测评）：旧的同意书/测评/agreements 用例
  **已删除**（不保留 skip）；CSRF 用例的非安全方法载体从 ``/me/consents`` 改为 ``/auth/logout``、``/auth/password``、
  ``PUT /me/profile``。§8 v0.2.5 的 5 组用例见文末“契约 v0.2.5”一节；后端未同步前标 ``xfail(strict=False)``，
  原因写明负责任务（后端 T-B03b / T-B01 / T-B30，取自 T-A06 §3 后端清单）。
- 契约 v0.2.4（35f4880，未推到 origin）：``apply_note`` ≤ 200；CSRF 双提交以 Cookie 为准（头、Cookie、会话令牌三者一致）。
- 防暴力（限速/渐进锁定，plan §3.6 数值）归 T-B03a：用 ``xfail(strict=True)`` 固化契约预期，实现后会 XPASS 失败提醒转正。
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import secrets
import statistics
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(os.environ.get("AIA_BACKEND_DIR", Path(__file__).resolve().parents[3] / "src" / "backend")).resolve()
if not (BACKEND_DIR / "app" / "auth" / "sessions.py").is_file():
    pytest.skip("后端没有 app/auth/sessions.py（依赖 T-B03 合入，f44b6ee）", allow_module_level=True)
for _pkg in ("argon2", "alembic", "sqlalchemy", "redis", "psycopg", "fastapi"):
    try:
        importlib.import_module(_pkg)
    except ImportError:
        pytest.skip(f"缺少依赖包 {_pkg}（用后端 venv：uv sync --frozen，见 CI backend job）", allow_module_level=True)

API = "/api/v1"
CT_JSON = "application/json; charset=utf-8"
IDLE_TTL_S = 604800  # 契约 §1.3：滑动 7 天
ABSOLUTE_TTL_S = 2592000  # 契约 #25 / plan 6.1 auth.yaml session.absolute_ttl_s：自登录起 30 天，不续期；Cookie Max-Age 取此值
#: 后端未跟上 v0.2.3 #24–#27 的负责任务
T_B03_FU = "T-B03 跟进（契约 v0.2.3 #25/#26，T-A05 7c62f59）：后端尚未实现"
#: 契约 v0.2.5（T-A06 bd33f83）后端未同步时的负责任务（T-A06 §3 后端清单）
B_V025_AUTH = "后端 T-B03b（契约 v0.2.5 / T-A06 §3：删同意与测评端点、表、门槛，注册忽略 agreements，Me 删 consents/risk_assessment）"
B_V025_ENUMS = "后端 T-B01 / T-B03b（契约 v0.2.5 / T-A06 §3：errors.py、schemas/enums.py 删作废码与枚举，version v0.2.5）"
B_V025_INSTANCES = "后端（策略实例 POST，契约 v0.2.5 / T-A06 §1.4、§3：删 fit_ack 校验、加 warnings；接口尚未实现）"
#: 后端未跟上契约 v0.2.4（T-A05 35f4880）的负责任务
T_B03_V024 = "T-B03 跟进（契约 v0.2.4，T-A05 35f4880）：后端尚未实现"
#: 旧客户端的注册 ``agreements``：现后端（f44b6ee）仍必填；v0.2.5 起服务端忽略。默认注册体照发，以兼容两者
AGREEMENTS = ["terms", "privacy", "risk_disclosure"]
#: 契约 §7.1 ``Me``：v0.2.5 删 consents、risk_assessment；v0.2.6 加必填 ``data_licence_status``（T-B45，efcd244 已在 origin/main）
ME_KEYS = {"id", "username", "display_name", "role", "status", "entitlements", "data_licence_status"}
#: 契约 §3 ``data_licence_status`` 取值（v0.2.6）
DATA_LICENCE_STATUSES = {"not_set", "pending_verification", "active", "invalid", "expired", "quota_exceeded", "ip_limited",
                         "paused_by_admin"}
#: v0.2.5 前的 Me 多出的键（后端未同步时允许出现，由 test_v025_me_has_no_consent_or_assessment_keys 跟踪）
ME_RETIRED_KEYS = {"consents", "risk_assessment"}
BJ_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+08:00$")
UNSAFE = [
    ("PUT", "/me/profile", {"version": 0}),
    ("POST", "/auth/password", {"old_password": "x", "new_password": "y"}),
    ("POST", "/auth/logout", None),
]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def new_pw() -> str:
    """运行时随机口令：含字母和数字、19 位，满足口令策略。"""
    return "Tt" + secrets.token_hex(8) + "x9"


def new_name() -> str:
    return "tt01d_" + secrets.token_hex(5)


def reg(username: str, password: str, **kw: Any) -> dict[str, Any]:
    """契约 §7.1 注册体：``{username, password, display_name, invite_code?}``；``agreements`` 为旧字段（v0.2.5 起忽略）。"""
    body: dict[str, Any] = {"username": username, "password": password, "display_name": "测试用户", "agreements": AGREEMENTS}
    body.update(kw)
    return body


def sid_key(sid: str) -> str:
    return "auth:session:" + hashlib.sha256(sid.encode()).hexdigest()


def assert_err(r: Any, status: int, code: str) -> dict[str, Any]:
    """统一错误信封（契约 §4）：``{"error": {code, message, details?, request_id}}``，request_id 与响应头一致。"""
    assert r.status_code == status, (r.status_code, r.text[:300])
    assert r.headers.get("content-type") == CT_JSON
    body = r.json()
    assert set(body) == {"error"}, body
    err = body["error"]
    assert err["code"] == code, err
    assert isinstance(err["message"], str) and err["message"]
    assert err["request_id"] == r.headers.get("x-request-id")
    assert set(err) <= {"code", "message", "details", "request_id"}
    return err


def fields(err: dict[str, Any]) -> list[str]:
    return [f["field"] for f in err.get("details", {}).get("fields", [])]


def set_cookies(r: Any) -> dict[str, str]:
    """``Set-Cookie`` 原文按 cookie 名索引（小写比较属性）。"""
    out: dict[str, str] = {}
    for raw in r.headers.get_list("set-cookie"):
        out[raw.split("=", 1)[0].strip()] = raw
    return out


def attrs(raw: str) -> dict[str, str]:
    parts = [p.strip() for p in raw.split(";")][1:]
    res: dict[str, str] = {}
    for p in parts:
        k, _, v = p.partition("=")
        res[k.strip().lower()] = v.strip()
    return res


# ---------------------------------------------------------------------------
# fixture：独立数据库 + 迁移
# ---------------------------------------------------------------------------
def _with_db(url: str, name: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "/" + name, p.query, p.fragment))


@pytest.fixture(scope="module")
def authdb(pg_url: str, redis_url: str) -> Iterator[SimpleNamespace]:
    import psycopg
    import redis as redislib
    from sqlalchemy import create_engine

    base = pg_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
    name = "tt01d_auth_" + secrets.token_hex(4)
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = _with_db(base, name)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BUSINESS__",))}
    env.update({"DATABASE_URL": url, "APP_ENV": "test", "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("APP_MASTER_KEY", None)
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, "alembic upgrade head 失败：\n" + (proc.stderr or proc.stdout)[-2000:]
    eng = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    rds = redislib.Redis.from_url(redis_url, decode_responses=True)
    try:
        yield SimpleNamespace(url=url, redis_url=redis_url, engine=eng, redis=rds, name=name)
    finally:
        eng.dispose()
        rds.close()
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def sql(authdb: SimpleNamespace) -> Callable[..., Any]:
    from sqlalchemy import text

    def _sql(stmt: str, **params: Any) -> list[Any]:
        with authdb.engine.begin() as c:
            res = c.execute(text(stmt), params)
            return list(res) if res.returns_rows else []

    return _sql


def random_client_ip() -> str:
    """测试用来源 IP（198.18.0.0/15 基准测试网段，不在可信代理内）：每个客户端各用一个，
    使 T-B03a 的按 IP 限速（Redis 键跨用例、跨运行存活）只在用例有意为之时触发。"""
    n = secrets.randbelow(1 << 17)
    return f"198.{18 + (n >> 16)}.{(n >> 8) & 0xFF}.{n & 0xFF}"


@pytest.fixture
def app_client(authdb: SimpleNamespace, backend: SimpleNamespace, make_settings: Callable[..., Any]) -> Iterator[Callable[..., Any]]:
    """``app_client(mode="open", secure=False, ip=None, **settings)`` → TestClient（真实 PG/Redis，进程内）。

    ``ip`` 为直连来源地址；不给则每个客户端随机一个（见 :func:`random_client_ip`）。
    """
    from fastapi.testclient import TestClient

    clients: list[Any] = []

    def _make(mode: str = "open", secure: bool | None = False, base_url: str = "http://testserver",
              ip: str | None = None, **kw: Any) -> Any:
        overrides: dict[str, Any] = {"database_url": authdb.url, "redis_url": authdb.redis_url, "registration_mode": mode}
        if secure is not None:
            overrides["session_cookie_secure"] = secure
        overrides.update(kw)
        app = backend.main.create_app(make_settings(**overrides))
        c = TestClient(app, base_url=base_url, raise_server_exceptions=False, client=(ip or random_client_ip(), 50000))
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def mkuser(app_client: Callable[..., Any], sql: Callable[..., Any]) -> Callable[..., SimpleNamespace]:
    """经 ``/auth/register`` 注册，再用 SQL 设定状态（审批接口属 T-B03b）。"""

    def _mk(status: str = "approved", role: str = "user") -> SimpleNamespace:
        c = app_client("open")
        name, pw = new_name(), new_pw()
        r = c.post(f"{API}/auth/register", json=reg(name, pw))
        assert r.status_code == 201, r.text[:300]
        uid = r.json()["id"]
        sql("UPDATE app.users SET status=:s, role=:r WHERE id=:i", s=status, r=role, i=uid)
        return SimpleNamespace(id=uid, username=name, password=pw)

    return _mk


@pytest.fixture
def session(app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace]) -> Callable[..., SimpleNamespace]:
    """已登录的客户端：``.client``（cookie 已在 jar 中）、``.csrf``、``.sid``、``.user``。"""

    def _login(user: SimpleNamespace | None = None, **kw: Any) -> SimpleNamespace:
        u = user or mkuser()
        c = app_client(**kw)
        r = c.post(f"{API}/auth/login", json={"username": u.username, "password": u.password})
        assert r.status_code == 200, r.text[:300]
        return SimpleNamespace(client=c, csrf=r.json()["csrf_token"], sid=c.cookies.get("sid"), user=u, resp=r)

    return _login


def user_session_keys(authdb: SimpleNamespace, uid: str) -> set[str]:
    return set(authdb.redis.smembers(f"auth:user_sessions:{uid}"))


# ---------------------------------------------------------------------------
# 迁移版本：origin/main 0cb78ad 的 head = 0008（0005 T-B16 契约 v0.2.5、0006 T-B16b caps kind、
# 0007 T-B45 数据证书表、0008 T-B03c 邀请码；aia-t01 运维重建后同为 0008）
# ---------------------------------------------------------------------------
#: DB 自检期望的迁移 head：0008（新迁移推到 origin 时同步此处）。T-T23：契约 v0.2.8 后端在本地 main 带来
#: 0009（T-B02y，ETF/策略类型触发器）与 0010（T-B03d，user_data_licence_holds）；T-T24：本地 main 又有
#: 0011（T-B16 删除用户数据）、0012（T-B03e 证书冷却）、0013（T-B16-core-r2 aia_maint/purging）。
#: 精确集合：origin 0008、main 0016（T-T25 追加：0014 bbf58a0 T-B46 imports/trades、0015 a8e055b T-B03f 评审修复、
#: 0016 83a031c T-B10 research_candidates 部分唯一索引；0017 6670b10 T-B49 data_snapshots purpose=horizon + user_scoped CHECK，
#: 须与 6670b10 一起推送）；中间版本在分批推送时可能成为 head。
#: 评审 d018fad M1：0018 9e693b2 T-B49b（horizon 触发器 on_demand）、0019 1398351 T-B51（证券主表）。
#: 另以被测树 migrations/versions 的 revision/down_revision 链推出唯一 head，库中版本须等于它——以后新增迁移时
#: 本用例会以"head 未登记"的明确信息失败，提醒同步本集合与 DB 自检。
# 0034: T-B133 minute-bars sources; CI migrates this fixed source tree to its unique head.
KNOWN_HEADS = ("0008", "0010", "0011", "0012", "0013", "0014", "0015", "0016", "0017", "0018", "0019", "0034")

_REV_RE = re.compile(r"""^(down_revision|revision)\b[^=]*=\s*(.+)$""", re.MULTILINE)


def _tree_heads() -> set[str]:
    """被测树迁移目录中没有被任何 down_revision 引用的 revision（正常应恰好一个）。"""
    revs: set[str] = set()
    downs: set[str] = set()
    for f in sorted((BACKEND_DIR / "migrations" / "versions").glob("*.py")):
        for key, val in _REV_RE.findall(f.read_text(encoding="utf-8")):
            ids = set(re.findall(r"""['"]([^'"]+)['"]""", val))
            (revs if key == "revision" else downs).update(ids)
    return revs - downs


def test_alembic_head_is_known(authdb: SimpleNamespace, sql: Callable[..., Any]) -> None:
    """head 必须是已登记的版本，且等于被测树迁移链的唯一 head（新迁移落地时同步本用例与 DB 自检）。"""
    assert (BACKEND_DIR / "migrations" / "versions").is_dir()
    heads = _tree_heads()
    assert len(heads) == 1, f"迁移目录应恰好一个 head：{sorted(heads)}"
    v = sql("SELECT version_num FROM alembic_version")[0][0]
    assert v == next(iter(heads)), (v, sorted(heads))
    assert v in KNOWN_HEADS, f"head {v} 未登记到 KNOWN_HEADS（同步本集合与 DB 自检）"


# ---------------------------------------------------------------------------
# 注册（契约 §7.1 /auth/register、/meta/registration）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["closed", "invite", "open"])
def test_meta_registration_reports_mode(app_client: Callable[..., Any], mode: str) -> None:
    r = app_client(mode).get(f"{API}/meta/registration")
    assert r.status_code == 200 and r.json()["mode"] == mode
    assert set(r.json()) == {"mode"}  # v0.2.4 起不再返回 doc_versions


def test_registration_default_is_closed(authdb: SimpleNamespace, make_client: Callable[..., Any]) -> None:
    c = make_client(database_url=authdb.url, redis_url=authdb.redis_url)
    assert c.get(f"{API}/meta/registration").json()["mode"] == "closed"


def test_register_when_closed_is_503_and_writes_nothing(app_client: Callable[..., Any], sql: Callable[..., Any]) -> None:
    name = new_name()
    r = app_client("closed").post(f"{API}/auth/register", json=reg(name, new_pw()))
    assert_err(r, 503, "REGISTRATION_CLOSED")
    assert sql("SELECT count(*) FROM app.users WHERE username=:u", u=name)[0][0] == 0


def test_register_invite_mode_without_code_is_400_and_writes_nothing(
    app_client: Callable[..., Any], sql: Callable[..., Any]
) -> None:
    """#27（T-B03c 已在 origin 0cb78ad）：invite 模式缺邀请码 → ``400 VALIDATION_ERROR``，
    ``invite_code`` 记为 invalid（与错误/过期/已用同一形态）；缺 ``apply_note`` 记为 required；不落库。"""
    name = new_name()
    r = app_client("invite").post(f"{API}/auth/register", json=reg(name, new_pw()))
    err = assert_err(r, 400, "VALIDATION_ERROR")
    got = err["details"]["fields"]
    assert {"field": "invite_code", "issue": "invalid"} in got
    assert {"field": "apply_note", "issue": "required"} in got
    assert sql("SELECT count(*) FROM app.users WHERE username=:u", u=name)[0][0] == 0


# 架构师裁定 2026-11-02, v0.2.9 687159f：closed 模式畸形请求体一律 503 REGISTRATION_CLOSED、绝不 400，注册模式最先判定。
# 更多畸形体见 test_architect_rulings_t_t25.py（裁定 1）。
# T-T25 追加：本地 main f72b8c7（T-B03e 追加）已实现并在 c9e1e73 上核实通过，转为硬断言；origin 0cb78ad 上会失败（400），须随 f72b8c7 推 origin。
def test_register_closed_rejects_even_malformed_body_with_503(app_client: Callable[..., Any], sql: Callable[..., Any]) -> None:
    n0 = sql("SELECT count(*) FROM app.users")[0][0]
    assert_err(app_client("closed").post(f"{API}/auth/register", json={}), 503, "REGISTRATION_CLOSED")
    assert sql("SELECT count(*) FROM app.users")[0][0] == n0


@pytest.mark.parametrize("display_name", ["", "   "], ids=["empty", "blank"])
def test_register_requires_display_name(app_client: Callable[..., Any], display_name: str) -> None:
    r = app_client("open").post(f"{API}/auth/register", json=reg(new_name(), new_pw(), display_name=display_name))
    assert "display_name" in fields(assert_err(r, 400, "VALIDATION_ERROR"))


def test_register_open_creates_pending_user_and_no_session(
    app_client: Callable[..., Any], sql: Callable[..., Any]
) -> None:
    c = app_client("open")
    name, pw = new_name(), new_pw()
    r = c.post(f"{API}/auth/register", json=reg(name.upper(), pw))
    assert r.status_code == 201, r.text[:300]
    body = r.json()
    assert set(body) == {"id", "username", "status"}
    uuid.UUID(body["id"])
    assert body["username"] == name and body["status"] == "pending"
    assert "set-cookie" not in r.headers  # 注册不登录
    (row,) = sql("SELECT password_hash, role, status FROM app.users WHERE id=:i", i=body["id"])
    assert row.password_hash.startswith("$argon2id$") and pw not in row.password_hash
    assert row.role == "user" and row.status == "pending"


def test_register_duplicate_username_case_insensitive_is_409(app_client: Callable[..., Any]) -> None:
    c = app_client("open")
    name = new_name()
    assert c.post(f"{API}/auth/register", json=reg(name, new_pw())).status_code == 201
    r = c.post(f"{API}/auth/register", json=reg(name.upper(), new_pw()))
    err = assert_err(r, 409, "CONFLICT")
    assert err.get("details", {}).get("field") == "username"


@pytest.mark.parametrize(
    "username",
    ["abc", "a" * 33, "bad-name", "has space", "中文名字", "admin", "root", "system", ""],
    ids=["too-short", "too-long", "dash", "space", "non-ascii", "reserved-admin", "reserved-root", "reserved-system", "empty"],
)
def test_register_rejects_bad_username(app_client: Callable[..., Any], username: str) -> None:
    r = app_client("open").post(f"{API}/auth/register", json=reg(username, new_pw()))
    assert "username" in fields(assert_err(r, 400, "VALIDATION_ERROR"))


@pytest.mark.parametrize("length", [4, 32])
def test_register_username_length_bounds_accepted(app_client: Callable[..., Any], length: int) -> None:
    """#24：``^[a-z0-9_]{4,32}$`` 两端可用（3 位、33 位见上一用例）。"""
    name = ("t" + secrets.token_hex(16))[:length]
    r = app_client("open").post(f"{API}/auth/register", json=reg(name, new_pw()))
    assert r.status_code == 201, r.text[:300]


@pytest.mark.parametrize("length", [10, 128])
def test_register_password_length_bounds_accepted(app_client: Callable[..., Any], length: int) -> None:
    """#27 / plan 6.1 auth.yaml password：10–128 两端可用。"""
    pw = ("Tt9" + secrets.token_hex(64))[:length]
    r = app_client("open").post(f"{API}/auth/register", json=reg(new_name(), pw))
    assert r.status_code == 201, r.text[:300]


def test_register_accepts_apply_note(app_client: Callable[..., Any], sql: Callable[..., Any]) -> None:
    """#27：注册体增加 ``apply_note``（open 模式可选）；v0.2.4 #2 上限由 500 改为 200。"""
    c = app_client("open")
    for note in ("测试申请说明", "x" * 200, None):
        r = c.post(f"{API}/auth/register", json=reg(new_name(), new_pw(), apply_note=note))
        assert r.status_code == 201, r.text[:300]


def test_register_apply_note_over_200_is_400(app_client: Callable[..., Any]) -> None:
    """契约 v0.2.4 §9：``apply_note`` 201 字 → 400（现后端因未知字段返回 400，字段名同样是 apply_note）。"""
    r = app_client("open").post(f"{API}/auth/register", json=reg(new_name(), new_pw(), apply_note="x" * 201))
    assert "apply_note" in fields(assert_err(r, 400, "VALIDATION_ERROR"))


def test_register_invalid_invite_codes_share_one_response_body(app_client: Callable[..., Any]) -> None:
    """#27：邀请码错误/过期/已用/已吊销统一 ``400 {fields:[{field:"invite_code", issue:"invalid"}]}``，响应体完全相同。

    测试只能构造“不存在”的几种形态（随机、错格式、空白）；过期/已用/已吊销需 ``/admin/invites``（T-B03c）落地后补。
    """
    c = app_client("invite")
    bodies = []
    for code in ("TT01D" + secrets.token_hex(12).upper(), "not-a-code", "  "):
        r = c.post(f"{API}/auth/register", json=reg(new_name(), new_pw(), invite_code=code, apply_note="申请说明"))
        err = assert_err(r, 400, "VALIDATION_ERROR")
        assert err["details"]["fields"] == [{"field": "invite_code", "issue": "invalid"}]
        bodies.append({k: v for k, v in err.items() if k != "request_id"})
    assert all(b == bodies[0] for b in bodies)


def test_admin_invites_hidden_from_non_admin(session: Callable[..., SimpleNamespace], app_client: Callable[..., Any]) -> None:
    """#27 /admin/invites（🛡）：非 admin（含未登录）一律 404，不暴露端点存在。"""
    s = session()
    for c in (s.client, app_client()):
        assert_err(c.get(f"{API}/admin/invites"), 404, "NOT_FOUND")
    r = s.client.post(f"{API}/admin/invites", json={"ttl_h": 24}, headers={"X-CSRF-Token": s.csrf})
    assert_err(r, 404, "NOT_FOUND")
    assert_err(s.client.delete(f"{API}/admin/invites/{uuid.uuid4()}", headers={"X-CSRF-Token": s.csrf}), 404, "NOT_FOUND")


@pytest.mark.parametrize("kind", ["short", "letters-only", "digits-only", "same-as-username", "common", "too-long"])
def test_register_rejects_weak_password(app_client: Callable[..., Any], kind: str) -> None:
    name = new_name()
    candidate = {
        "short": "Ab1" + secrets.token_hex(2),
        "letters-only": "abcdefghij" + "klmnop",
        "digits-only": "".join(secrets.choice("0123456789") for _ in range(14)),
        "same-as-username": name.upper(),
        "common": "qwerty" + "12345",
        "too-long": "a1" * 65,
    }[kind]
    r = app_client("open").post(f"{API}/auth/register", json=reg(name, candidate))
    err = assert_err(r, 400, "VALIDATION_ERROR")
    assert "password" in fields(err)
    assert candidate not in json.dumps(err, ensure_ascii=False)  # 不回显口令


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"status": "approved"}])
def test_register_rejects_privilege_fields(app_client: Callable[..., Any], sql: Callable[..., Any], extra: dict[str, str]) -> None:
    name = new_name()
    r = app_client("open").post(
        f"{API}/auth/register", json={**reg(name, new_pw()), **extra}
    )
    assert_err(r, 400, "VALIDATION_ERROR")
    assert sql("SELECT count(*) FROM app.users WHERE username=:u", u=name)[0][0] == 0


# ---------------------------------------------------------------------------
# 登录 / 账号状态 / 用户枚举
# ---------------------------------------------------------------------------
def test_login_success_returns_me_and_csrf_and_cookies(session: Callable[..., SimpleNamespace]) -> None:
    s = session()
    body = s.resp.json()
    assert set(body) == {"user", "csrf_token"}
    assert ME_KEYS <= set(body["user"]) <= ME_KEYS | ME_RETIRED_KEYS
    assert body["user"]["username"] == s.user.username and body["user"]["status"] == "approved"
    assert body["user"]["data_licence_status"] == "not_set"  # 新用户尚未设置证书（契约 v0.2.6）
    assert len(s.csrf) >= 32 and s.sid and len(s.sid) >= 32
    assert s.client.cookies.get("csrf_token") == s.csrf
    assert s.sid not in s.resp.text  # sid 只在 HttpOnly cookie 里


def test_login_username_is_case_insensitive(app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace]) -> None:
    u = mkuser()
    r = app_client().post(f"{API}/auth/login", json={"username": u.username.upper(), "password": u.password})
    assert r.status_code == 200


@pytest.mark.parametrize("status", ["pending", "rejected", "disabled"])
def test_login_not_approved_is_403_without_session(
    app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace], authdb: SimpleNamespace, status: str
) -> None:
    u = mkuser(status)
    r = app_client().post(f"{API}/auth/login", json={"username": u.username, "password": u.password})
    err = assert_err(r, 403, "ACCOUNT_NOT_APPROVED")
    assert err["details"]["status"] == status
    assert "sid" not in set_cookies(r)
    assert user_session_keys(authdb, u.id) == set()


def test_login_rejected_includes_reason_when_reviewed(
    app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace], sql: Callable[..., Any]
) -> None:
    admin = mkuser("approved", role="admin")
    u = mkuser("rejected")
    sql(
        "INSERT INTO app.account_reviews (user_id, action, reason, admin_id) VALUES (:u, 'reject', :why, :a)",
        u=u.id, why="tt01d 测试驳回理由", a=admin.id,
    )
    r = app_client().post(f"{API}/auth/login", json={"username": u.username, "password": u.password})
    err = assert_err(r, 403, "ACCOUNT_NOT_APPROVED")
    assert err["details"] == {"status": "rejected", "reason": "tt01d 测试驳回理由"}


def test_login_pending_with_wrong_password_does_not_leak_status(
    app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace]
) -> None:
    u = mkuser("pending")
    r = app_client().post(f"{API}/auth/login", json={"username": u.username, "password": new_pw()})
    err = assert_err(r, 401, "INVALID_CREDENTIALS")
    assert "pending" not in json.dumps(err)


def test_login_no_user_enumeration(app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace]) -> None:
    """不存在的用户名与错误口令：状态码、错误码、message、details 完全一致；耗时同量级（都跑 argon2）。"""
    u = mkuser()
    c = app_client()

    def attempt(name: str) -> tuple[Any, float]:
        t0 = time.perf_counter()
        r = c.post(f"{API}/auth/login", json={"username": name, "password": new_pw()})
        return r, time.perf_counter() - t0

    wrong, ghost = [], []
    for _ in range(3):
        wrong.append(attempt(u.username))
        ghost.append(attempt(new_name()))
    for r, _ in wrong + ghost:
        assert_err(r, 401, "INVALID_CREDENTIALS")
        assert "set-cookie" not in r.headers
    strip = lambda r: {k: v for k, v in r.json()["error"].items() if k != "request_id"}  # noqa: E731
    assert strip(wrong[0][0]) == strip(ghost[0][0])
    assert wrong[0][0].headers.get("content-length") == ghost[0][0].headers.get("content-length")
    t_wrong = statistics.median(t for _, t in wrong)
    t_ghost = statistics.median(t for _, t in ghost)
    assert t_ghost >= 0.3 * t_wrong, f"不存在用户明显更快（{t_ghost:.3f}s vs {t_wrong:.3f}s），可据耗时枚举"


@pytest.mark.parametrize(
    "payload", [{}, {"username": "x"}, {"password": "x"}, {"username": 1, "password": 2}],
    ids=["empty", "no-password", "no-username", "wrong-types"],
)
def test_login_malformed_body_is_400(app_client: Callable[..., Any], payload: dict[str, Any]) -> None:
    assert_err(app_client().post(f"{API}/auth/login", json=payload), 400, "VALIDATION_ERROR")


def test_login_locked_account_is_403_with_retry_after(
    app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace], sql: Callable[..., Any], authdb: SimpleNamespace
) -> None:
    u = mkuser()
    until = datetime.now(timezone.utc) + timedelta(minutes=15)
    sql("UPDATE app.users SET locked_until=:t WHERE id=:i", t=until, i=u.id)
    r = app_client().post(f"{API}/auth/login", json={"username": u.username, "password": u.password})
    err = assert_err(r, 403, "ACCOUNT_LOCKED")
    assert 0 < err["details"]["retry_after_s"] <= 900
    assert user_session_keys(authdb, u.id) == set()
    sql("UPDATE app.users SET locked_until=:t WHERE id=:i", t=datetime.now(timezone.utc) - timedelta(seconds=1), i=u.id)
    assert app_client().post(f"{API}/auth/login", json={"username": u.username, "password": u.password}).status_code == 200


# ---------------------------------------------------------------------------
# Cookie 属性（契约 §1.3）
# ---------------------------------------------------------------------------
def test_cookie_flags_when_insecure_dev(session: Callable[..., SimpleNamespace]) -> None:
    s = session(secure=False)
    ck = set_cookies(s.resp)
    sid, csrf = attrs(ck["sid"]), attrs(ck["csrf_token"])
    assert "httponly" in sid and sid["samesite"].lower() == "lax" and sid["path"] == "/"
    assert int(sid["max-age"]) >= IDLE_TTL_S  # #25 起 = absolute_ttl_s，见下方 xfail 用例
    assert "httponly" not in csrf and csrf["samesite"].lower() == "lax" and csrf["path"] == "/"
    assert "secure" not in sid and "secure" not in csrf
    assert "domain" not in sid  # 只发给本站


def test_cookie_max_age_is_absolute_ttl(session: Callable[..., SimpleNamespace]) -> None:
    """#25 / plan 6.1：Cookie ``Max-Age`` = ``absolute_ttl_s``（30 天）；服务端另按 idle 与 absolute 判定。"""
    ck = set_cookies(session().resp)
    assert int(attrs(ck["sid"])["max-age"]) == ABSOLUTE_TTL_S


def test_cookie_secure_by_default(
    app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace]
) -> None:
    u = mkuser()
    c = app_client(secure=None, base_url="https://testserver")  # 不覆盖 → 默认 SESSION_COOKIE_SECURE=true
    r = c.post(f"{API}/auth/login", json={"username": u.username, "password": u.password})
    assert r.status_code == 200
    ck = set_cookies(r)
    assert "secure" in attrs(ck["sid"]) and "secure" in attrs(ck["csrf_token"])
    assert "httponly" in attrs(ck["sid"])


def test_redis_stores_only_sid_digest(session: Callable[..., SimpleNamespace], authdb: SimpleNamespace) -> None:
    s = session()
    keys = user_session_keys(authdb, s.user.id)
    assert keys == {hashlib.sha256(s.sid.encode()).hexdigest()} or keys == {sid_key(s.sid)}
    raw = authdb.redis.get(sid_key(s.sid))
    assert raw is not None and s.sid not in raw
    assert authdb.redis.get("auth:session:" + s.sid) is None
    payload = json.loads(raw)
    assert payload["user_id"] == s.user.id


# ---------------------------------------------------------------------------
# 会话：过期、滑动续期、轮换（防固定）、伪造
# ---------------------------------------------------------------------------
def test_session_expiry_requires_reauth(session: Callable[..., SimpleNamespace], authdb: SimpleNamespace) -> None:
    s = session()
    assert s.client.get(f"{API}/me").status_code == 200
    authdb.redis.pexpire(sid_key(s.sid), 1)
    time.sleep(0.05)
    assert_err(s.client.get(f"{API}/me"), 401, "AUTH_REQUIRED")


def test_session_ttl_is_sliding_7_days(session: Callable[..., SimpleNamespace], authdb: SimpleNamespace) -> None:
    s = session()
    key = sid_key(s.sid)
    assert IDLE_TTL_S - 60 <= authdb.redis.ttl(key) <= IDLE_TTL_S
    authdb.redis.expire(key, 120)
    assert s.client.get(f"{API}/me").status_code == 200
    assert authdb.redis.ttl(key) > IDLE_TTL_S - 60


def _age_session(authdb: SimpleNamespace, sid: str, days: float) -> None:
    """把会话的 ``created_at`` 改到 ``days`` 天前（保留剩余 TTL），模拟“登录已久但一直活跃”。"""
    key = sid_key(sid)
    ttl = authdb.redis.ttl(key)
    data = json.loads(authdb.redis.get(key))
    data["created_at"] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    authdb.redis.set(key, json.dumps(data), ex=ttl)


def test_session_within_absolute_ttl_still_valid(session: Callable[..., SimpleNamespace], authdb: SimpleNamespace) -> None:
    s = session()
    _age_session(authdb, s.sid, 29)
    assert s.client.get(f"{API}/me").status_code == 200


def test_session_past_absolute_ttl_is_401(session: Callable[..., SimpleNamespace], authdb: SimpleNamespace) -> None:
    """#25：自登录起 30 天绝对过期，不因活跃续期；过期后 401 且会话被清除。"""
    s = session()
    _age_session(authdb, s.sid, 31)
    assert_err(s.client.get(f"{API}/me"), 401, "AUTH_REQUIRED")
    assert authdb.redis.get(sid_key(s.sid)) is None


def test_login_rotates_session_and_csrf(session: Callable[..., SimpleNamespace], authdb: SimpleNamespace) -> None:
    """已带 sid 再登录：签发新 sid/新 CSRF，旧 sid 立即失效（防会话固定）。"""
    s = session()
    old_sid, old_csrf = s.sid, s.csrf
    r = s.client.post(f"{API}/auth/login", json={"username": s.user.username, "password": s.user.password})
    assert r.status_code == 200
    new_sid = s.client.cookies.get("sid")
    assert new_sid and new_sid != old_sid and r.json()["csrf_token"] != old_csrf
    assert authdb.redis.get(sid_key(old_sid)) is None
    assert s.client.get(f"{API}/me").status_code == 200


def test_attacker_planted_sid_is_not_adopted(app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace]) -> None:
    u = mkuser()
    planted = secrets.token_urlsafe(32)
    c = app_client()
    c.cookies.set("sid", planted)
    r = c.post(f"{API}/auth/login", json={"username": u.username, "password": u.password})
    assert r.status_code == 200
    issued = set_cookies(r)["sid"].split(";", 1)[0].split("=", 1)[1]
    assert issued and issued != planted
    probe = app_client()
    probe.cookies.set("sid", planted)
    assert_err(probe.get(f"{API}/me"), 401, "AUTH_REQUIRED")


@pytest.mark.parametrize("sid", ["", "x", "A" * 300, "../../etc/passwd", "%00"], ids=["empty", "short", "overlong", "path", "nul"])
def test_forged_sid_is_401(app_client: Callable[..., Any], sid: str) -> None:
    c = app_client()
    c.cookies.set("sid", sid)
    assert_err(c.get(f"{API}/me"), 401, "AUTH_REQUIRED")


def test_corrupt_session_payload_is_401_and_purged(session: Callable[..., SimpleNamespace], authdb: SimpleNamespace) -> None:
    s = session()
    authdb.redis.set(sid_key(s.sid), "{not json", ex=600)
    assert_err(s.client.get(f"{API}/me"), 401, "AUTH_REQUIRED")
    assert authdb.redis.get(sid_key(s.sid)) is None


@pytest.mark.parametrize("status", ["disabled", "rejected"])
def test_status_change_revokes_live_sessions(
    session: Callable[..., SimpleNamespace], authdb: SimpleNamespace, sql: Callable[..., Any], status: str
) -> None:
    """禁用/驳回即失效（plan §3.6、契约 #25）：下一次请求 403，会话全部吊销，恢复后也需重新登录。

    改角色、管理员重置密码吊销会话要经 /admin 接口触发（T-B03b），待其落地后补用例。"""
    s = session()
    sql("UPDATE app.users SET status=:s WHERE id=:i", s=status, i=s.user.id)
    err = assert_err(s.client.get(f"{API}/me"), 403, "ACCOUNT_NOT_APPROVED")
    assert err["details"]["status"] == status
    assert user_session_keys(authdb, s.user.id) == set()
    sql("UPDATE app.users SET status='approved' WHERE id=:i", i=s.user.id)
    assert_err(s.client.get(f"{API}/me"), 401, "AUTH_REQUIRED")


# ---------------------------------------------------------------------------
# 登出
# ---------------------------------------------------------------------------
def test_logout_clears_cookies_and_kills_session(session: Callable[..., SimpleNamespace], authdb: SimpleNamespace) -> None:
    s = session()
    sid = s.sid
    r = s.client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": s.csrf})
    assert r.status_code == 204 and r.content == b""
    ck = set_cookies(r)
    for name in ("sid", "csrf_token"):
        a = attrs(ck[name])
        assert a.get("max-age") == "0" or "expires" in a, ck[name]
    assert authdb.redis.get(sid_key(sid)) is None
    assert sid_key(sid).split(":")[-1] not in user_session_keys(authdb, s.user.id)
    replay = s.client.__class__(s.client.app, raise_server_exceptions=False)
    replay.cookies.set("sid", sid)
    assert_err(replay.get(f"{API}/me"), 401, "AUTH_REQUIRED")
    replay.close()


def test_logout_only_ends_current_session(session: Callable[..., SimpleNamespace]) -> None:
    a = session()
    b = session(a.user)
    assert a.client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": a.csrf}).status_code == 204
    assert b.client.get(f"{API}/me").status_code == 200


def test_logout_unauthenticated_is_401(app_client: Callable[..., Any]) -> None:
    assert_err(app_client().post(f"{API}/auth/logout"), 401, "AUTH_REQUIRED")


# ---------------------------------------------------------------------------
# CSRF（契约 §1.3：非安全方法须带 X-CSRF-Token，与会话内令牌比对）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method,path,body", UNSAFE, ids=[f"{m} {p}" for m, p, _ in UNSAFE])
@pytest.mark.parametrize("variant", ["missing", "wrong", "other-session", "cookie-only", "empty"])
def test_csrf_rejected(
    session: Callable[..., SimpleNamespace], method: str, path: str, body: Any, variant: str
) -> None:
    s = session()
    headers: dict[str, str] = {}
    if variant == "wrong":
        headers["X-CSRF-Token"] = secrets.token_urlsafe(32)
    elif variant == "other-session":
        headers["X-CSRF-Token"] = session().csrf
    elif variant == "empty":
        headers["X-CSRF-Token"] = ""
    elif variant == "cookie-only":
        pass  # 只有 csrf_token cookie（浏览器自动带），没有请求头
    r = s.client.request(method, f"{API}{path}", json=body, headers=headers)
    assert_err(r, 403, "CSRF_FAILED")
    assert s.client.get(f"{API}/me").status_code == 200  # 会话不受影响


def test_csrf_double_submit_cookie_forgery_rejected(session: Callable[..., SimpleNamespace]) -> None:
    """攻击者能写子域 cookie 时：把 csrf_token cookie 和请求头都设成自造值，仍须拒绝（只信会话内令牌）。"""
    s = session()
    forged = secrets.token_urlsafe(32)
    s.client.cookies.set("csrf_token", forged)
    r = s.client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": forged})
    assert_err(r, 403, "CSRF_FAILED")
    assert s.client.get(f"{API}/me").status_code == 200


def test_csrf_header_and_cookie_agree_but_not_session_is_403(session: Callable[..., SimpleNamespace]) -> None:
    """契约 v0.2.4 §9：请求头与 Cookie 一致、但与会话内令牌不符 → ``403 CSRF_FAILED``（用别的会话的真令牌，非随机串）。"""
    s, other = session(), session()
    sid = s.client.cookies.get("sid")
    s.client.cookies.clear()
    s.client.cookies.set("sid", sid)
    s.client.cookies.set("csrf_token", other.csrf)
    r = s.client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": other.csrf})
    assert_err(r, 403, "CSRF_FAILED")
    assert s.client.get(f"{API}/me").status_code == 200


# T-T25 追加：本地 main c9e1e73（T-B47“CSRF 双提交比对 Cookie”）已实现并核实通过，转为硬断言；origin 0cb78ad 上会失败（204），须随 c9e1e73 推 origin。
@pytest.mark.parametrize("cookie", ["mismatch", "absent"])
def test_csrf_double_submit_requires_cookie_to_match(session: Callable[..., SimpleNamespace], cookie: str) -> None:
    """契约 v0.2.4 #13 / §1.3：双提交以 Cookie 为准，头、Cookie、会话令牌三者须一致；头 = 会话令牌但 Cookie 不符或缺失 → 403。"""
    s = session()
    jar = s.client.cookies
    sid = jar.get("sid")
    jar.clear()
    jar.set("sid", sid)
    if cookie == "mismatch":
        jar.set("csrf_token", secrets.token_urlsafe(32))
    r = s.client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": s.csrf})
    assert_err(r, 403, "CSRF_FAILED")


def test_csrf_failure_has_no_side_effect(session: Callable[..., SimpleNamespace], app_client: Callable[..., Any]) -> None:
    """缺 CSRF 头的改密被拒后：旧口令仍可登录、新口令不可登录、会话仍有效。"""
    s = session()
    new = new_pw()
    r = s.client.post(f"{API}/auth/password", json={"old_password": s.user.password, "new_password": new})
    assert_err(r, 403, "CSRF_FAILED")
    assert s.client.get(f"{API}/me").status_code == 200
    assert app_client().post(f"{API}/auth/login", json={"username": s.user.username, "password": s.user.password}).status_code == 200
    assert app_client().post(f"{API}/auth/login", json={"username": s.user.username, "password": new}).status_code == 401


@pytest.mark.parametrize("method,path", [("GET", "/me"), ("HEAD", "/me"), ("GET", "/me/profile"), ("GET", "/meta/registration")])
def test_safe_methods_exempt_from_csrf(session: Callable[..., SimpleNamespace], method: str, path: str) -> None:
    s = session()
    r = s.client.request(method, f"{API}{path}")
    assert r.status_code != 403, r.text[:300]
    if r.status_code >= 400 and method != "HEAD":  # HEAD 无响应体（FastAPI 不自动提供 HEAD → 405）
        assert r.json()["error"]["code"] != "CSRF_FAILED"


def test_unsafe_without_session_is_401_not_csrf(app_client: Callable[..., Any]) -> None:
    r = app_client().post(f"{API}/auth/password", json={"old_password": new_pw(), "new_password": new_pw()})
    assert_err(r, 401, "AUTH_REQUIRED")
    assert_err(app_client().post(f"{API}/auth/logout"), 401, "AUTH_REQUIRED")


# ---------------------------------------------------------------------------
# 修改密码
# ---------------------------------------------------------------------------
def test_change_password_wrong_old_is_400_and_changes_nothing(
    session: Callable[..., SimpleNamespace], app_client: Callable[..., Any]
) -> None:
    s = session()
    other = session(s.user)
    r = s.client.post(
        f"{API}/auth/password", json={"old_password": new_pw(), "new_password": new_pw()}, headers={"X-CSRF-Token": s.csrf}
    )
    assert fields(assert_err(r, 400, "VALIDATION_ERROR")) == ["old_password"]
    assert other.client.get(f"{API}/me").status_code == 200
    assert app_client().post(f"{API}/auth/login", json={"username": s.user.username, "password": s.user.password}).status_code == 200


@pytest.mark.parametrize("kind", ["same-as-old", "weak", "same-as-username"])
def test_change_password_new_must_pass_policy(session: Callable[..., SimpleNamespace], kind: str) -> None:
    s = session()
    new = {"same-as-old": s.user.password, "weak": "short1", "same-as-username": s.user.username}[kind]
    r = s.client.post(
        f"{API}/auth/password", json={"old_password": s.user.password, "new_password": new}, headers={"X-CSRF-Token": s.csrf}
    )
    assert "new_password" in fields(assert_err(r, 400, "VALIDATION_ERROR"))


def test_change_password_revokes_other_sessions_and_old_password(
    session: Callable[..., SimpleNamespace], app_client: Callable[..., Any], authdb: SimpleNamespace, sql: Callable[..., Any]
) -> None:
    s = session()
    other1, other2 = session(s.user), session(s.user)
    assert len(user_session_keys(authdb, s.user.id)) == 3
    newp = new_pw()
    r = s.client.post(
        f"{API}/auth/password", json={"old_password": s.user.password, "new_password": newp}, headers={"X-CSRF-Token": s.csrf}
    )
    assert r.status_code == 204, r.text[:300]
    assert s.client.get(f"{API}/me").status_code == 200  # 当前用户仍登录（#25 起为轮换后的新会话）
    for o in (other1, other2):
        assert_err(o.client.get(f"{API}/me"), 401, "AUTH_REQUIRED")
    current = s.client.cookies.get("sid")
    assert user_session_keys(authdb, s.user.id) == {hashlib.sha256(current.encode()).hexdigest()}
    assert_err(
        app_client().post(f"{API}/auth/login", json={"username": s.user.username, "password": s.user.password}),
        401, "INVALID_CREDENTIALS",
    )
    assert app_client().post(f"{API}/auth/login", json={"username": s.user.username, "password": newp}).status_code == 200
    (changed,) = sql("SELECT password_changed_at FROM app.users WHERE id=:i", i=s.user.id)[0]
    assert changed is not None


def test_change_password_rotates_current_session(
    session: Callable[..., SimpleNamespace], app_client: Callable[..., Any], authdb: SimpleNamespace
) -> None:
    """#25：改密 204 + Set-Cookie 新 ``sid`` 与新 ``csrf_token``；旧 sid 401；新 sid + 新 CSRF 可用。"""
    s = session()
    old_sid, old_csrf = s.sid, s.csrf
    r = s.client.post(
        f"{API}/auth/password", json={"old_password": s.user.password, "new_password": new_pw()}, headers={"X-CSRF-Token": s.csrf}
    )
    assert r.status_code == 204 and r.content == b""
    ck = set_cookies(r)
    assert {"sid", "csrf_token"} <= set(ck)
    new_sid, new_csrf = ck["sid"].split(";", 1)[0].split("=", 1)[1], ck["csrf_token"].split(";", 1)[0].split("=", 1)[1]
    assert new_sid and new_sid != old_sid and new_csrf and new_csrf != old_csrf
    assert authdb.redis.get(sid_key(old_sid)) is None
    old = app_client()
    old.cookies.set("sid", old_sid)
    assert_err(old.get(f"{API}/me"), 401, "AUTH_REQUIRED")
    assert s.client.get(f"{API}/me").status_code == 200
    stale = s.client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": old_csrf})
    assert_err(stale, 403, "CSRF_FAILED")
    ok = s.client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": new_csrf})
    assert ok.status_code == 204


def test_change_password_requires_auth(app_client: Callable[..., Any]) -> None:
    r = app_client().post(f"{API}/auth/password", json={"old_password": new_pw(), "new_password": new_pw()})
    assert_err(r, 401, "AUTH_REQUIRED")


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------
def test_me_requires_auth(app_client: Callable[..., Any]) -> None:
    assert_err(app_client().get(f"{API}/me"), 401, "AUTH_REQUIRED")


def test_me_shape(session: Callable[..., SimpleNamespace]) -> None:
    """契约 ``Me`` 的键齐全（含 v0.2.6 必填 ``data_licence_status``）；作废键（consents/risk_assessment）由 v0.2.5 组单独跟踪，
    这里不因其存在而失败。"""
    s = session()
    me = s.client.get(f"{API}/me").json()
    assert ME_KEYS <= set(me) <= ME_KEYS | ME_RETIRED_KEYS
    assert me["id"] == s.user.id and me["username"] == s.user.username
    assert me["role"] == "user" and me["status"] == "approved"
    assert isinstance(me["entitlements"], dict)
    assert me["data_licence_status"] in DATA_LICENCE_STATUSES and me["data_licence_status"] == "not_set"
    assert "password_hash" not in json.dumps(me) and "failed_login_count" not in me


def test_admin_routes_hidden_from_non_admin(session: Callable[..., SimpleNamespace], app_client: Callable[..., Any]) -> None:
    """契约 v0.2.1：非 admin（含未登录）访问 /admin/* 一律 404。"""
    s = session()
    assert_err(s.client.get(f"{API}/admin/users"), 404, "NOT_FOUND")
    assert_err(app_client().get(f"{API}/admin/users"), 404, "NOT_FOUND")


# ---------------------------------------------------------------------------
# 审计不落敏感值
# ---------------------------------------------------------------------------
def test_audit_logs_contain_no_password_or_raw_ip(
    session: Callable[..., SimpleNamespace], app_client: Callable[..., Any], sql: Callable[..., Any]
) -> None:
    s = session()
    bad = new_pw()
    app_client().post(f"{API}/auth/login", json={"username": s.user.username, "password": bad})
    rows = sql("SELECT action, detail::text AS d, ip_hash FROM app.audit_logs WHERE actor_id=:i OR target_id=:t", i=s.user.id, t=s.user.id)
    assert rows, "登录应写审计"
    assert all(r.action.startswith(("auth.", "consent.")) for r in rows)  # consent.*：v0.2.5 前的后端；见 v0.2.5 组
    blob = json.dumps([list(r) for r in rows], default=str)
    for secret in (s.user.password, bad, s.sid, s.csrf, "testclient"):
        assert secret not in blob


# ---------------------------------------------------------------------------
# 防暴力 / 限速（plan §3.6 数值；契约 §1.3、§7.1）——T-B03a 未实现
# ---------------------------------------------------------------------------
T_B03A = "T-B03a：限速/渐进锁定/可信代理尚未实现（T-B03 报告声明延后）"


def test_bruteforce_5_failures_lock_15_minutes(app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace]) -> None:
    u = mkuser()
    c = app_client()
    for _ in range(5):
        c.post(f"{API}/auth/login", json={"username": u.username, "password": new_pw()})
    r = c.post(f"{API}/auth/login", json={"username": u.username, "password": u.password})
    err = assert_err(r, 403, "ACCOUNT_LOCKED")
    assert 800 <= err["details"]["retry_after_s"] <= 900


def test_login_rate_limited_per_ip(app_client: Callable[..., Any]) -> None:
    c = app_client()
    codes = [c.post(f"{API}/auth/login", json={"username": new_name(), "password": new_pw()}) for _ in range(11)]
    last = codes[-1]
    assert_err(last, 429, "RATE_LIMITED")
    assert int(last.headers["retry-after"]) > 0


def test_register_rate_limited_per_ip(app_client: Callable[..., Any]) -> None:
    c = app_client("open")
    rs = [c.post(f"{API}/auth/register", json=reg(new_name(), new_pw())) for _ in range(6)]
    assert_err(rs[-1], 429, "RATE_LIMITED")
    assert int(rs[-1].headers["retry-after"]) > 0


def test_client_supplied_x_real_ip_not_trusted(
    session: Callable[..., SimpleNamespace], app_client: Callable[..., Any], sql: Callable[..., Any]
) -> None:
    """直连客户端自带的 X-Real-IP 不应改变审计/限速用的来源 IP（否则可伪造来源绕过按 IP 限速）。"""
    s = session()
    ip = random_client_ip()  # 两次请求同一直连来源；只有 X-Real-IP 不同
    for hdr in ({}, {"X-Real-IP": "203.0.113." + str(secrets.randbelow(250) + 1)}):
        app_client(ip=ip).post(f"{API}/auth/login", json={"username": s.user.username, "password": new_pw()}, headers=hdr)
    hashes = [h for (h,) in sql(
        "SELECT ip_hash FROM app.audit_logs WHERE (actor_id=:i OR target_id=:t) AND action LIKE 'auth.login%' ORDER BY at DESC LIMIT 2",
        i=s.user.id, t=s.user.id,
    )]
    assert len(hashes) == 2 and hashes[0] == hashes[1]


# ---------------------------------------------------------------------------
# 契约 v0.2.5（T-A06 bd33f83）§8 测试点：不做同意流程与风险测评
# 后端已在 origin/main 同步（T-B03 跟进 4162abb 等）：原 xfail(strict=False) 已移除，直接断言防回归。
# 分类器 1.2.0 的规则层期望在 tests/backend/unit/test_horizon_cases.py；/meta/enums 与文档码表在 test_meta_enums.py。
# ---------------------------------------------------------------------------
#: 组 1：作废的端点（v0.2.5 → 404）
# 6 个端点在 origin/main 均为 404（直接断言，防回归）。
V025_RETIRED_ENDPOINTS = [
    pytest.param("GET", "/meta/consent-docs", None, id="GET /meta/consent-docs"),
    pytest.param("GET", "/legal/terms", None, id="GET /legal/terms"),
    pytest.param("POST", "/me/consents", {"key": "privacy", "version": "unversioned"}, id="POST /me/consents"),
    pytest.param("GET", "/me/risk-assessment", None, id="GET /me/risk-assessment"),
    pytest.param("POST", "/me/risk-assessment", {"answers": {}}, id="POST /me/risk-assessment"),
    pytest.param("GET", "/me/risk-assessment/questionnaire", None, id="GET /me/risk-assessment/questionnaire"),
]


@pytest.mark.parametrize("method,path,body", V025_RETIRED_ENDPOINTS)
def test_v025_retired_consent_and_assessment_endpoints_are_404(
    session: Callable[..., SimpleNamespace], method: str, path: str, body: Any
) -> None:
    """v0.2.5 组 1：``/meta/consent-docs``、``/legal/terms``、``POST /me/consents``、``/me/risk-assessment*`` → 404。"""
    s = session()
    r = s.client.request(method, f"{API}{path}", json=body, headers={"X-CSRF-Token": s.csrf})
    assert_err(r, 404, "NOT_FOUND")


def _consent_rows(sql: Callable[..., Any], uid: Any) -> int:
    """v0.2.5 可能删表：表不存在视为 0 行。"""
    if sql("SELECT to_regclass('app.consents')")[0][0] is None:
        return 0
    return sql("SELECT count(*) FROM app.consents WHERE user_id=:i", i=uid)[0][0]


@pytest.mark.parametrize("agreements", ["absent", "legacy"])
def test_v025_register_ignores_agreements_and_writes_no_consent(
    app_client: Callable[..., Any], sql: Callable[..., Any], agreements: str
) -> None:
    """v0.2.5 组 2：注册带或不带 ``agreements`` 都 201，库中不产生同意记录（旧字段服务端忽略，不报错、不记录）。"""
    body = reg(new_name(), new_pw())
    if agreements == "absent":
        body.pop("agreements")
    r = app_client("open").post(f"{API}/auth/register", json=body)
    assert r.status_code == 201, (r.status_code, r.text[:300])
    assert _consent_rows(sql, r.json()["id"]) == 0
    assert sql("SELECT count(*) FROM app.audit_logs WHERE target_id=:i AND action LIKE 'consent.%'", i=r.json()["id"])[0][0] == 0


def test_v025_me_has_no_consent_or_assessment_keys(session: Callable[..., SimpleNamespace]) -> None:
    """v0.2.5 组 2：无 consents、risk_assessment；键集合恰为契约 v0.2.6 ``Me``
    ``{id, username, display_name, role, status, entitlements, data_licence_status}``。"""
    s = session()
    for keys in (set(s.client.get(f"{API}/me").json()), set(s.resp.json()["user"])):
        assert keys == ME_KEYS
        assert not keys & {"consents", "risk_assessment"}


#: 组 3：⚖ 建议类接口与财务写入（v0.2.5 无合规门槛）
V025_UNGATED = [
    ("GET", "/terminal"), ("GET", "/today"), ("GET", "/candidate-signals"), ("GET", "/suggestions"),
    ("GET", "/daily-reports"), ("GET", "/signals"), ("POST", "/plan-drafts"), ("POST", "/suggestions/refresh"),
    ("POST", "/imports"), ("POST", "/trades"),
]
#: 自报画像全部“不满足”（v0.2.5 §7.1 /me/profile 请求体）
V025_LOW_PROFILE = {"horizon_pref": ["long"], "effort": "low", "risk_tolerance": 1, "experience": "novice",
                    "max_single_position_pct": "10"}


@pytest.mark.parametrize("profile", ["none", "unsatisfied"])
def test_v025_no_403_gate_without_or_with_low_profile(session: Callable[..., SimpleNamespace], profile: str) -> None:
    """v0.2.5 组 3：无画像、或画像不满足任何条件时，⚖ 接口、``POST /imports``、``POST /trades`` 均不返回 403。

    现后端尚无这些路由（404），本用例对“没有门槛”成立；路由落地后同一断言继续生效。"""
    s = session()
    hdr = {"X-CSRF-Token": s.csrf}
    if profile == "unsatisfied":
        r = s.client.put(f"{API}/me/profile", json=V025_LOW_PROFILE, headers=hdr)
        if r.status_code != 200:
            pytest.xfail(B_V025_AUTH + f"（PUT /me/profile 拒绝 v0.2.5 画像体：{r.status_code}）")
    for method, path in V025_UNGATED:
        r = s.client.request(method, f"{API}{path}", json={} if method == "POST" else None, headers=hdr)
        assert r.status_code != 403, (method, path, r.text[:200])
        if r.status_code >= 400:
            assert r.json()["error"]["code"] not in {"CONSENT_REQUIRED", "CSRF_FAILED"}, (method, path)


def _route_mounted(app: Any, method: str, path: str) -> bool:
    """路由表里是否挂载 ``method path``（展开 Mount / 子路由 / effective_candidates，同 t23 的 app_routes）。"""
    def walk(nodes: Any) -> bool:
        for n in nodes:
            if hasattr(n, "effective_candidates"):
                if walk(n.effective_candidates()):
                    return True
            elif getattr(n, "path", None) and getattr(n, "methods", None):
                if n.path == path and method in n.methods:
                    return True
            elif getattr(n, "routes", None) and walk(n.routes):
                return True
        return False

    return walk(getattr(app, "routes", []))


#: 评审 d018fad §3 / m2：接口层行为（GET /horizon-assessments、classifier 1.2.0、SH0C/IT0C 仅入 hints）已由
#: 后端 T-B47（c9e1e73）交付并稳定通过 → 严格断言，归属 T-B47。T-B30/T-B30a 的真正验收（f.* 特征、落库真实
#: snapshot_id、三种重算触发、proposed strategy_instances）见 test_horizon_t_b30a_acceptance.py（xfail strict）。
def test_v025_horizon_assessment_has_hints_and_classifier_1_2_0(session: Callable[..., SimpleNamespace]) -> None:
    """v0.2.5 组 4（接口层）：``/horizon-assessments`` 返回 ``hints: HorizonHint[]``（永不为 null）、``classifier_version`` 1.2.0；
    novice 画像 → hints 含 SH0C/IT0C 且 caps 不含二者。规则层期望见 unit/test_horizon_cases.py。"""
    s = session()
    if not _route_mounted(s.client.app, "GET", f"{API}/horizon-assessments"):
        # origin 0cb78ad 尚无 T-B47（c9e1e73 在本地 main）：条件 xfail，不让 origin 变红；路由存在即严格断言
        pytest.xfail("后端 T-B47（c9e1e73：GET /horizon-assessments 未推 origin）")
    hdr = {"X-CSRF-Token": s.csrf}
    assert s.client.put(f"{API}/me/profile", json=V025_LOW_PROFILE, headers=hdr).status_code == 200
    r = s.client.get(f"{API}/horizon-assessments", params={"security_code": "600000"})
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["classifier_version"] == "1.2.0" and isinstance(body["hints"], list)
    for h in body["hints"]:
        assert set(h) == {"horizon", "rule_id", "text"}
    ids = {h["rule_id"] for h in body["hints"]}
    assert {"SH0C", "IT0C"} <= ids
    assert not ids & {c["rule_id"] for c in body["caps"]}


@pytest.mark.xfail(strict=False, reason=B_V025_INSTANCES)
def test_v025_strategy_instance_unsuitable_horizon_is_201_with_warnings(session: Callable[..., SimpleNamespace]) -> None:
    """v0.2.5 组 5：``POST /strategy-instances`` 对不适合的周期 → 201 且 ``warnings`` 非空；请求带 ``fit_ack`` 被忽略。
    （接口落地后需补策略版本/账户夹具；目前路由不存在。）"""
    s = session()
    body = {"strategy_version_id": "00000000-0000-4000-8000-000000000001", "scope": "security", "account_id": None,
            "security_code": "600000", "horizon": "intraday_t", "param_overrides": None, "budget_amount": None,
            "fit_ack": {"rule_ids": ["IT0C"]}}
    r = s.client.post(f"{API}/strategy-instances", json=body, headers={"X-CSRF-Token": s.csrf})
    assert r.status_code == 201, (r.status_code, r.text[:300])
    assert r.json()["warnings"] and all(isinstance(w, str) and w for w in r.json()["warnings"])
