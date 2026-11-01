"""认证/会话/CSRF/同意书（T-B03，契约 §1.3、§4、§7.1；plan §3.6）——真实 PostgreSQL + Redis（T-T01d）。

- 后端没有 ``app/auth/sessions.py``（T-B03 未合入）时整组 skip；缺 argon2/alembic/sqlalchemy/redis 时 skip（原因写明）。
- 每个模块新建一个独立数据库（``tt01d_auth_<随机>``），``alembic upgrade head`` 后测试，结束即删除；
  Redis 只按本组用户的键断言，不 ``FLUSHDB``，可与其他用例共用实例。
- 用户名、口令、主密钥全部运行时随机生成，不含任何真实凭据；不连外网、不调用任何行情接口。
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
AGREEMENTS = ["terms", "privacy", "risk_disclosure"]
ME_KEYS = {"id", "username", "display_name", "role", "status", "entitlements", "consents", "risk_assessment"}
BJ_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+08:00$")
UNSAFE = [
    ("POST", "/me/consents", {"key": "privacy", "version": "v-tt01d"}),
    ("PUT", "/me/profile", {"version": 0}),
    ("POST", "/auth/password", {"old_password": "x", "new_password": "y"}),
    ("POST", "/me/risk-assessment", {"answers": {}}),
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
    """契约 §7.1 注册体：``{username, password, display_name, invite_code?, agreements}``。"""
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


@pytest.fixture
def app_client(authdb: SimpleNamespace, make_client: Callable[..., Any]) -> Callable[..., Any]:
    """``app_client(mode="open", secure=False, **settings)`` → TestClient（真实 PG/Redis，进程内）。"""

    def _make(mode: str = "open", secure: bool | None = False, base_url: str = "http://testserver", **kw: Any) -> Any:
        overrides: dict[str, Any] = {"database_url": authdb.url, "redis_url": authdb.redis_url, "registration_mode": mode}
        if secure is not None:
            overrides["session_cookie_secure"] = secure
        overrides.update(kw)
        c = make_client(**overrides)
        c.base_url = base_url  # type: ignore[assignment]
        return c

    return _make


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
# 迁移版本（DB 自检同步改为 0004）
# ---------------------------------------------------------------------------
def test_alembic_head_is_0004_and_terms_consent_kind(authdb: SimpleNamespace, sql: Callable[..., Any]) -> None:
    assert (BACKEND_DIR / "migrations" / "versions").is_dir()
    assert sql("SELECT version_num FROM alembic_version")[0][0] == "0004"
    (cdef,) = sql(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_consents_kind'"
    )[0]
    assert "'terms'" in cdef


# ---------------------------------------------------------------------------
# 注册（契约 §7.1 /auth/register、/meta/registration）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["closed", "invite", "open"])
def test_meta_registration_reports_mode(app_client: Callable[..., Any], mode: str) -> None:
    r = app_client(mode).get(f"{API}/meta/registration")
    assert r.status_code == 200 and r.json() == {"mode": mode}


def test_registration_default_is_closed(authdb: SimpleNamespace, make_client: Callable[..., Any]) -> None:
    c = make_client(database_url=authdb.url, redis_url=authdb.redis_url)
    assert c.get(f"{API}/meta/registration").json() == {"mode": "closed"}


@pytest.mark.parametrize("mode", ["closed", "invite"])
def test_register_when_not_open_is_503_and_writes_nothing(
    app_client: Callable[..., Any], sql: Callable[..., Any], mode: str
) -> None:
    name = new_name()
    r = app_client(mode).post(f"{API}/auth/register", json=reg(name, new_pw()))
    assert_err(r, 503, "REGISTRATION_CLOSED")
    assert sql("SELECT count(*) FROM app.users WHERE username=:u", u=name)[0][0] == 0


@pytest.mark.xfail(strict=True, reason="契约 §7.1“closed 一律 503”；后端先做 schema 校验，畸形请求体返回 400（待架构师裁定）")
def test_register_closed_rejects_even_malformed_body_with_503(app_client: Callable[..., Any]) -> None:
    assert_err(app_client("closed").post(f"{API}/auth/register", json={}), 503, "REGISTRATION_CLOSED")


@pytest.mark.parametrize("display_name", ["", "   "], ids=["empty", "blank"])
def test_register_requires_display_name(app_client: Callable[..., Any], display_name: str) -> None:
    r = app_client("open").post(f"{API}/auth/register", json=reg(new_name(), new_pw(), display_name=display_name))
    assert "display_name" in fields(assert_err(r, 400, "VALIDATION_ERROR"))


def test_register_open_creates_pending_user_with_consents_and_no_session(
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
    kinds = {k for (k,) in sql("SELECT kind FROM app.consents WHERE user_id=:i AND granted", i=body["id"])}
    assert kinds == {"terms", "privacy_policy", "risk_disclosure"}


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


@pytest.mark.parametrize(
    "agreements", [[], ["terms", "privacy"], ["terms", "privacy", "risk_disclosure", "marketing"], None],
    ids=["empty", "missing-risk", "unknown-extra", "absent"],
)
def test_register_requires_exact_agreements(app_client: Callable[..., Any], agreements: list[str] | None) -> None:
    payload = reg(new_name(), new_pw())
    del payload["agreements"]
    if agreements is not None:
        payload["agreements"] = agreements
    r = app_client("open").post(f"{API}/auth/register", json=payload)
    assert "agreements" in fields(assert_err(r, 400, "VALIDATION_ERROR"))


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
    assert set(body["user"]) == ME_KEYS
    assert body["user"]["username"] == s.user.username and body["user"]["status"] == "approved"
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
    assert int(sid["max-age"]) == IDLE_TTL_S
    assert "httponly" not in csrf and csrf["samesite"].lower() == "lax" and csrf["path"] == "/"
    assert "secure" not in sid and "secure" not in csrf
    assert "domain" not in sid  # 只发给本站


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


def test_status_change_revokes_live_sessions(
    session: Callable[..., SimpleNamespace], authdb: SimpleNamespace, sql: Callable[..., Any]
) -> None:
    """禁用即失效（plan §3.6）：已登录用户被禁用后下一次请求 403，会话全部吊销，恢复后也需重新登录。"""
    s = session()
    sql("UPDATE app.users SET status='disabled' WHERE id=:i", i=s.user.id)
    err = assert_err(s.client.get(f"{API}/me"), 403, "ACCOUNT_NOT_APPROVED")
    assert err["details"]["status"] == "disabled"
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
    r = s.client.post(f"{API}/me/consents", json={"key": "privacy", "version": "v-forged"}, headers={"X-CSRF-Token": forged})
    assert_err(r, 403, "CSRF_FAILED")


def test_csrf_failure_has_no_side_effect(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    r = s.client.post(f"{API}/me/consents", json={"key": "signal_risk_disclosure", "version": "v-csrf"})
    assert_err(r, 403, "CSRF_FAILED")
    assert sql("SELECT count(*) FROM app.consents WHERE user_id=:i AND doc_version='v-csrf'", i=s.user.id)[0][0] == 0


@pytest.mark.parametrize("method,path", [("GET", "/me"), ("HEAD", "/me"), ("GET", "/me/profile"), ("GET", "/meta/registration")])
def test_safe_methods_exempt_from_csrf(session: Callable[..., SimpleNamespace], method: str, path: str) -> None:
    s = session()
    r = s.client.request(method, f"{API}{path}")
    assert r.status_code != 403, r.text[:300]
    if r.status_code >= 400 and method != "HEAD":  # HEAD 无响应体（FastAPI 不自动提供 HEAD → 405）
        assert r.json()["error"]["code"] != "CSRF_FAILED"


def test_unsafe_without_session_is_401_not_csrf(app_client: Callable[..., Any]) -> None:
    r = app_client().post(f"{API}/me/consents", json={"key": "privacy", "version": "v1"})
    assert_err(r, 401, "AUTH_REQUIRED")


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
    assert s.client.get(f"{API}/me").status_code == 200  # 当前会话保留
    for o in (other1, other2):
        assert_err(o.client.get(f"{API}/me"), 401, "AUTH_REQUIRED")
    assert user_session_keys(authdb, s.user.id) == {hashlib.sha256(s.sid.encode()).hexdigest()}
    assert_err(
        app_client().post(f"{API}/auth/login", json={"username": s.user.username, "password": s.user.password}),
        401, "INVALID_CREDENTIALS",
    )
    assert app_client().post(f"{API}/auth/login", json={"username": s.user.username, "password": newp}).status_code == 200
    (changed,) = sql("SELECT password_changed_at FROM app.users WHERE id=:i", i=s.user.id)[0]
    assert changed is not None


def test_change_password_requires_auth(app_client: Callable[..., Any]) -> None:
    r = app_client().post(f"{API}/auth/password", json={"old_password": new_pw(), "new_password": new_pw()})
    assert_err(r, 401, "AUTH_REQUIRED")


# ---------------------------------------------------------------------------
# /me 与同意书
# ---------------------------------------------------------------------------
def test_me_requires_auth(app_client: Callable[..., Any]) -> None:
    assert_err(app_client().get(f"{API}/me"), 401, "AUTH_REQUIRED")


def test_me_shape(session: Callable[..., SimpleNamespace]) -> None:
    s = session()
    me = s.client.get(f"{API}/me").json()
    assert set(me) == ME_KEYS
    assert me["id"] == s.user.id and me["username"] == s.user.username
    assert me["role"] == "user" and me["status"] == "approved"
    assert isinstance(me["entitlements"], dict)
    assert me["risk_assessment"] is None
    assert set(me["consents"]) == set(AGREEMENTS)
    for v in me["consents"].values():
        assert set(v) == {"version", "accepted_at"} and BJ_RE.match(v["accepted_at"])
    assert "password_hash" not in json.dumps(me) and "failed_login_count" not in me


@pytest.mark.parametrize("key", ["signal_risk_disclosure", "privacy", "terms"])
def test_post_consent_and_me_reflects_latest(session: Callable[..., SimpleNamespace], sql: Callable[..., Any], key: str) -> None:
    s = session()
    ver = "v-tt01d-" + secrets.token_hex(2)
    r = s.client.post(f"{API}/me/consents", json={"key": key, "version": ver}, headers={"X-CSRF-Token": s.csrf})
    assert r.status_code == 201, r.text[:300]
    body = r.json()
    assert set(body) == {"key", "version", "accepted_at"} and body["key"] == key and body["version"] == ver
    assert BJ_RE.match(body["accepted_at"])
    me = s.client.get(f"{API}/me").json()
    assert me["consents"][key]["version"] == ver
    (n,) = sql("SELECT count(*) FROM app.audit_logs WHERE actor_id=:i AND action='consent.granted'", i=s.user.id)[0]
    assert n >= 1


@pytest.mark.parametrize(
    "payload",
    [{"key": "marketing", "version": "v1"}, {"key": "privacy"}, {"version": "v1"}, {"key": "privacy", "version": "v1", "granted": False}],
    ids=["unknown-key", "no-version", "no-key", "extra-field"],
)
def test_post_consent_invalid_is_400(session: Callable[..., SimpleNamespace], payload: dict[str, Any]) -> None:
    s = session()
    r = s.client.post(f"{API}/me/consents", json=payload, headers={"X-CSRF-Token": s.csrf})
    assert_err(r, 400, "VALIDATION_ERROR")


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
    assert all(r.action.startswith(("auth.", "consent.")) for r in rows)
    blob = json.dumps([list(r) for r in rows], default=str)
    for secret in (s.user.password, bad, s.sid, s.csrf, "testclient"):
        assert secret not in blob


# ---------------------------------------------------------------------------
# 防暴力 / 限速（plan §3.6 数值；契约 §1.3、§7.1）——T-B03a 未实现
# ---------------------------------------------------------------------------
T_B03A = "T-B03a：限速/渐进锁定/可信代理尚未实现（T-B03 报告声明延后）"


@pytest.mark.xfail(strict=True, reason=T_B03A)
def test_bruteforce_5_failures_lock_15_minutes(app_client: Callable[..., Any], mkuser: Callable[..., SimpleNamespace]) -> None:
    u = mkuser()
    c = app_client()
    for _ in range(5):
        c.post(f"{API}/auth/login", json={"username": u.username, "password": new_pw()})
    r = c.post(f"{API}/auth/login", json={"username": u.username, "password": u.password})
    err = assert_err(r, 403, "ACCOUNT_LOCKED")
    assert 800 <= err["details"]["retry_after_s"] <= 900


@pytest.mark.xfail(strict=True, reason=T_B03A)
def test_login_rate_limited_per_ip(app_client: Callable[..., Any]) -> None:
    c = app_client()
    codes = [c.post(f"{API}/auth/login", json={"username": new_name(), "password": new_pw()}) for _ in range(11)]
    last = codes[-1]
    assert_err(last, 429, "RATE_LIMITED")
    assert int(last.headers["retry-after"]) > 0


@pytest.mark.xfail(strict=True, reason=T_B03A)
def test_register_rate_limited_per_ip(app_client: Callable[..., Any]) -> None:
    c = app_client("open")
    rs = [c.post(f"{API}/auth/register", json=reg(new_name(), new_pw())) for _ in range(6)]
    assert_err(rs[-1], 429, "RATE_LIMITED")
    assert int(rs[-1].headers["retry-after"]) > 0


@pytest.mark.xfail(strict=True, reason=T_B03A + "；nginx 也未设置/覆盖 X-Real-IP")
def test_client_supplied_x_real_ip_not_trusted(
    session: Callable[..., SimpleNamespace], app_client: Callable[..., Any], sql: Callable[..., Any]
) -> None:
    """直连客户端自带的 X-Real-IP 不应改变审计/限速用的来源 IP（否则可伪造来源绕过按 IP 限速）。"""
    s = session()
    for hdr in ({}, {"X-Real-IP": "203.0.113." + str(secrets.randbelow(250) + 1)}):
        app_client().post(f"{API}/auth/login", json={"username": s.user.username, "password": new_pw()}, headers=hdr)
    hashes = [h for (h,) in sql(
        "SELECT ip_hash FROM app.audit_logs WHERE (actor_id=:i OR target_id=:t) AND action LIKE 'auth.login%' ORDER BY at DESC LIMIT 2",
        i=s.user.id, t=s.user.id,
    )]
    assert len(hashes) == 2 and hashes[0] == hashes[1]
