"""T-T22：每用户麦蕊证书接口（契约 v0.2.6 §7.1 ``/me/data-licence*``、§7.9 ``/admin/data-licences``、§9 v0.2.6 测试点）。

真实 PG/Redis（复用 ``test_auth_t_b03.py`` 的 authdb/session 夹具，独立临时库），进程内 TestClient，不联网。

- 组 1 不回显：证书值及其任意 ≥ 4 位子串不得出现在任何响应体、错误信封、日志（caplog + 标准输出/错误）中；
  响应头、库内全部表（含 ``ops.ingest_request_log``）与 Redis 键/值按 ≥ 8 位子串检查（避免与 argon2 散列、
  会话/CSRF 随机令牌偶然重合）；``DataLicenceStatus`` 无 ``licence``/``masked``/``last4`` 类键。
- 组 2 限速：``PUT`` 10 次/小时、``POST /test`` 5 次/小时（第 11/6 次 ``429 RATE_LIMITED``），另一用户不受影响。
  调度层“每证书令牌桶/DRR”见 ``tests/replay/test_licence_t_t22.py``。
- 组 3 降级（接口层）：本人证书 invalid/expired/未设置 → 行情读接口 200、``data_status ∈ {stale, unavailable}``、
  ``gaps`` 含 ``data_licence_unavailable``；``manual_refresh``（``POST /suggestions/refresh``）→ ``409 DATA_LICENCE_UNAVAILABLE``。

测试证书：运行时由 :func:`fake_licence` 生成（大写辅音字母，32 位），源码中没有任何证书字面量；绝不使用真实麦蕊证书。
T-B45 端点已在 origin（efcd244 起）→ 组 1/2 与形态用例严格断言；仍未实现的（行情降级/409、调度器）xfail(strict=False)，原因写明责任人（后端 T-B45 / T-B04a 扩展）。
"""

from __future__ import annotations

import importlib.util
import logging
import re
import secrets
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_spec = importlib.util.spec_from_file_location("tt22_auth_fixtures", Path(__file__).with_name("test_auth_t_b03.py"))
_auth = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_auth)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:  # 后端无 sessions.py / 缺 argon2 等：与认证组同样 skip
    pytest.skip(str(exc), allow_module_level=True)

# 夹具复用（独立 module 作用域临时库）
authdb = _auth.authdb
sql = _auth.sql
app_client = _auth.app_client
mkuser = _auth.mkuser
session = _auth.session
API = _auth.API
assert_err = _auth.assert_err
fields = _auth.fields

pytestmark = [pytest.mark.integration]


def _fake_seal_public_keys() -> str | None:
    """运行时生成一把一次性 X25519 公钥（SPKI DER，base64），格式同 T-O09 seal-keygen；私钥随即丢弃、从不落盘。
    后端环境没有 cryptography（origin/main 尚无 T-B04a 依赖）时返回 None。"""
    try:
        import base64  # noqa: PLC0415
        import json  # noqa: PLC0415

        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey  # noqa: PLC0415
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: PLC0415
    except ImportError:
        return None
    der = X25519PrivateKey.generate().public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return json.dumps({"1": base64.b64encode(der).decode()})


@pytest.fixture
def make_settings(make_settings: Callable[..., Any], backend: SimpleNamespace) -> Callable[..., Any]:
    """在 conftest 的 make_settings 上补封装公钥（T-B04a：api 未配公钥时证书写接口 503 MAINTENANCE）。"""
    fields_ = getattr(backend.config.Settings, "model_fields", {})
    if "data_licence_seal_public_keys" not in fields_:
        return make_settings
    keys = _fake_seal_public_keys()

    def _make(**overrides: Any) -> Any:
        if keys is not None:
            overrides.setdefault("data_licence_seal_public_keys", keys)
            overrides.setdefault("data_licence_seal_key_version", 1)
        return make_settings(**overrides)

    return _make

T_B45 = "后端 T-B45（T-A07 §5：/me/data-licence* 与 /admin/data-licences 端点、HMAC 防一证多用、列级视图、脱敏、通知、SSE；尚未实现）"
T_B45_B04A = ("后端 T-B45 + T-B04a 扩展（契约 v0.2.6 #8：本人证书不可用时行情接口 data_status/gaps、"
              "写操作 409 DATA_LICENCE_UNAVAILABLE；端点与 source_licence_id 尚未实现，efcd244 上 GET /quotes 仍 404）")
FAKE_ALPHABET = "BCDFGJKMNQRVWXZ"  # 无元音、无 H/T/L/P/S/Y、无数字与十六进制字母
#: 泄露键/列名检测（架构师评审 m11 收窄：原来的 ``last`` 会误伤契约允许的 last_verified_at / last_error_*）。
#: 只认：证书原值列（以 licence/license 结尾）、掩码、末几位（last4 / last_4）、指纹、HMAC、密文
FORBIDDEN_KEY = re.compile(r"(?i)licen[cs]e$|mask|last_?4|fingerprint|hmac|cipher")
#: 阳性对照样本：真会泄露（或可反推）证书的键名/列名，必须全部命中
LEAK_KEY_SAMPLES = ("licence", "license", "data_licence", "LICENCE", "masked_licence", "licence_mask", "last4", "last_4",
                    "licence_last4", "fingerprint", "licence_fingerprint", "licence_hmac", "hmac", "ciphertext", "cipher_text")
STATUS_KEYS = {"status", "tier", "has_quant_pro", "expires_on", "days_to_expiry", "set_at", "last_verified_at",
               "last_error_code", "last_error_at", "paused_until"}
ADMIN_EXTRA = {"user_id", "username", "display_name", "per_minute_limit", "calls_last_minute", "calls_today", "queue_depth"}
#: 契约 v0.2.8 #2：AdminDataLicence 新增（与 /admin/ingest/status licences[].licence_id 对应，未设置为 null）
ADMIN_EXTRA_V028 = {"licence_id"}
LICENCE_STATUSES = {"not_set", "pending_verification", "active", "invalid", "expired", "quota_exceeded", "ip_limited",
                    "paused_by_admin"}


def fake_licence(n: int = 32) -> str:
    """虚构测试证书：每次运行随机生成，从不写入仓库或报告。"""
    return "".join(secrets.choice(FAKE_ALPHABET) for _ in range(n))


def windows(s: str, k: int) -> set[str]:
    return {s[i : i + k] for i in range(len(s) - k + 1)}


def leak_count(lic: str, hay: str, k: int = 4) -> int:
    """命中的子串个数（只返回计数，绝不输出片段）。"""
    return sum(1 for w in windows(lic, k) if w in hay)


def body_of(lic: str, tier: str = "annual", **kw: Any) -> dict[str, Any]:
    return {"licence": lic, "tier": tier, "has_quant_pro": False, "expires_on": "2027-12-31", **kw}


class Rec:
    """记录会话内全部响应（体与头），供泄漏检查。"""

    def __init__(self, s: SimpleNamespace) -> None:
        self.s = s
        self.bodies: list[str] = []
        self.headers: list[str] = []

    def __call__(self, method: str, path: str, **kw: Any) -> Any:
        hdr = {"X-CSRF-Token": self.s.csrf} if method not in {"GET", "HEAD"} else {}
        r = self.s.client.request(method, f"{API}{path}", headers=hdr, **kw)
        self.bodies.append(r.text)
        self.headers.append("\n".join(f"{k}: {v}" for k, v in r.headers.items()))
        return r


def walk_keys(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        return [k for k, v in obj.items() for k in [k, *walk_keys(v)]]
    if isinstance(obj, list):
        return [k for v in obj for k in walk_keys(v)]
    return []


def assert_status_shape(d: dict[str, Any]) -> None:
    assert set(d) == STATUS_KEYS, sorted(set(d) ^ STATUS_KEYS)
    assert d["status"] in LICENCE_STATUSES
    assert not [k for k in walk_keys(d) if FORBIDDEN_KEY.search(k)]


def db_hits(sql: Callable[..., Any], lic: str, k: int = 8) -> list[str]:
    """库内所有业务表整行文本中含证书 ≥ k 位子串的表名（不输出取值）。"""
    rx = "|".join(sorted(windows(lic, k)))
    tables = sql("SELECT table_schema, table_name FROM information_schema.tables WHERE table_type='BASE TABLE' "
                 "AND table_schema NOT IN ('pg_catalog','information_schema') AND table_schema NOT LIKE '\\_timescaledb%' "
                 "AND table_schema NOT LIKE 'timescaledb%'")
    hits = []
    for schema, name in tables:
        n = sql(f'SELECT count(*) FROM "{schema}"."{name}" t WHERE t::text ~ :rx', rx=rx)[0][0]
        if n:
            hits.append(f"{schema}.{name}")
    return hits


def redis_hits(rds: Any, lic: str, k: int = 8) -> int:
    ws = windows(lic, k)
    n = 0
    for key in rds.scan_iter(count=500):
        blob = key
        if rds.type(key) == "string":
            blob += "\n" + (rds.get(key) or "")
        elif rds.type(key) == "hash":
            blob += "\n" + "\n".join(f"{a}={b}" for a, b in rds.hgetall(key).items())
        elif rds.type(key) == "stream":
            blob += "\n" + repr(rds.xrange(key, count=1000))
        elif rds.type(key) in {"set", "list"}:
            blob += "\n" + repr(rds.smembers(key) if rds.type(key) == "set" else rds.lrange(key, 0, -1))
        n += sum(1 for w in ws if w in blob)
    return n


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]) -> Callable[[], str]:
    caplog.set_level(logging.DEBUG)

    def _all() -> str:
        out = capfd.readouterr()
        return "\n".join([caplog.text, out.out, out.err])

    return _all


# ======================= 检测器自检（评审 m11：阳性/阴性对照） =======================
@pytest.mark.unit
def test_leak_key_regex_positive_and_negative_controls() -> None:
    """阳性对照：泄露类键名样本全部命中；阴性对照：契约 DataLicenceStatus / AdminDataLicence 夹具键（含 last_verified_at、
    last_error_code、last_error_at）与 Me 键一个都不命中。"""
    assert [k for k in LEAK_KEY_SAMPLES if not FORBIDDEN_KEY.search(k)] == []
    clean = STATUS_KEYS | ADMIN_EXTRA | _auth.ME_KEYS | {"consecutive_failures", "created_at", "deleted_at", "id", "key_version"}
    assert {"last_verified_at", "last_error_code", "last_error_at"} <= clean
    assert [k for k in sorted(clean) if FORBIDDEN_KEY.search(k)] == []


@pytest.mark.unit
def test_leak_window_detector_positive_and_negative_controls() -> None:
    """证书值子串检测：阳性对照（原值、任一 4 位片段、夹在 JSON 里）必中；阴性对照（仓库 tests/fixtures 全部文本、
    另一张虚构证书的 4 位窗口集合差）不中。计数只看个数，不输出片段。"""
    lic = fake_licence()
    assert leak_count(lic, lic) == len(windows(lic, 4))
    assert leak_count(lic, f'{{"detail": "x{lic[7:11]}y"}}') >= 1
    fixtures = Path(__file__).resolve().parents[2] / "fixtures"
    texts = [p.read_text(encoding="utf-8", errors="ignore") for p in sorted(fixtures.rglob("*")) if p.is_file()]
    assert texts, "tests/fixtures 为空，阴性对照无样本"
    # 夹具里偶有全由 FAKE_ALPHABET 组成的 4 字符片段（当前 1 个）；虚构证书与之撞上的概率约 0.06%，
    # 为免偶发失败，阴性对照所用证书重抽到与这些片段不相交为止（检测器本身不变）
    bare = {w for t in texts for w in windows(t, 4) if set(w) <= set(FAKE_ALPHABET)}
    neg = next(c for c in iter(fake_licence, None) if not windows(c, 4) & bare)
    assert sum(leak_count(neg, t) for t in texts) == 0
    assert sum(leak_count(neg, t) for t in texts + [neg[3:9]]) >= 1  # 同一组样本混入片段 → 立即命中
    other = fake_licence()
    assert leak_count(lic, "\n".join(w for w in windows(other, 4) if w not in windows(lic, 4))) == 0


# ======================= 组 1：证书值永不回显 =======================
def test_full_lifecycle_never_echoes_licence(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                              sql: Callable[..., Any], authdb: SimpleNamespace,
                                              logs: Callable[[], str]) -> None:
    """PUT → GET → /me → PATCH → POST /test → 管理端列表 → 暂停/恢复 → DELETE：任何响应、错误体、日志、库、Redis 都没有证书片段。"""
    lic = fake_licence()
    s = session()
    call = Rec(s)
    r = call("PUT", "/me/data-licence", json=body_of(lic))
    assert r.status_code == 202, r.text[:300]
    assert_status_shape(r.json())
    assert r.json()["status"] == "pending_verification" and r.json()["tier"] == "annual"
    g = call("GET", "/me/data-licence")
    assert g.status_code == 200 and g.json()["status"] in LICENCE_STATUSES
    assert_status_shape(g.json())
    me = call("GET", "/me").json()
    assert me["data_licence_status"] in LICENCE_STATUSES and me["data_licence_status"] != "not_set"
    p = call("PATCH", "/me/data-licence", json={"tier": "diamond", "has_quant_pro": True})
    assert p.status_code == 200 and p.json()["tier"] == "diamond"
    t = call("POST", "/me/data-licence/test")
    assert t.status_code in {202, 503}, t.text[:300]  # 503 INGEST_PAUSED：测试环境无 ingest 心跳
    if t.status_code == 202:
        assert set(t.json()) == {"verification_id"}
    else:
        assert_err(t, 503, "INGEST_PAUSED")
    admin = session(mkuser(role="admin"))
    acall = Rec(admin)
    lst = acall("GET", "/admin/data-licences")
    assert lst.status_code == 200, lst.text[:300]
    items = lst.json()["items"] if isinstance(lst.json(), dict) else lst.json()
    mine = [x for x in items if str(x["user_id"]) == str(s.user.id)]
    # 契约 v0.2.8 #2（T-T23）：AdminDataLicence 加 licence_id；按后端声明的契约版本取期望键集合（各版本都是全等）
    v028 = acall("GET", "/meta/enums").json().get("version") in ("v0.2.8", "v0.2.9")
    assert len(mine) == 1 and set(mine[0]) == STATUS_KEYS | ADMIN_EXTRA | (ADMIN_EXTRA_V028 if v028 else set())
    assert not [k for k in walk_keys(lst.json()) if FORBIDDEN_KEY.search(k)]
    assert acall("POST", f"/admin/data-licences/{s.user.id}/pause", json={"reason": "测试暂停"}).status_code == 204
    assert call("GET", "/me/data-licence").json()["status"] == "paused_by_admin"
    assert acall("POST", f"/admin/data-licences/{s.user.id}/resume", json={"reason": "测试恢复"}).status_code == 204
    assert call("GET", "/me/data-licence").json()["status"] == "pending_verification"
    assert call("DELETE", "/me/data-licence").status_code == 204
    bodies = "\n".join(call.bodies + acall.bodies)
    assert leak_count(lic, bodies) == 0, "响应体含证书片段"
    assert leak_count(lic, "\n".join(call.headers + acall.headers), 8) == 0, "响应头含证书片段"
    assert leak_count(lic, logs()) == 0, "日志含证书片段"
    assert db_hits(sql, lic) == [], "库内有证书明文片段"
    assert redis_hits(authdb.redis, lic) == 0, "Redis 有证书明文片段"


def _bad_values(lic: str) -> dict[str, str]:
    return {"slash": lic[:12] + "/" + lic[12:], "question": lic[:12] + "?" + lic[12:], "hash": lic[:12] + "#" + lic[12:],
            "percent": lic[:12] + "%2F" + lic[12:], "inner_space": lic[:12] + " " + lic[12:],
            "inner_tab": lic[:12] + "\t" + lic[12:], "too_short_15": lic[:15], "too_long_65": (lic * 3)[:65],
            "underscore": lic[:12] + "_" + lic[12:], "non_ascii": lic[:12] + "证" + lic[12:]}


@pytest.mark.parametrize("case", list(_bad_values("X" * 32)))
def test_invalid_format_400_does_not_echo_input(session: Callable[..., SimpleNamespace], logs: Callable[[], str],
                                                case: str) -> None:
    """格式不符（含 ``/ ? # %``、空白、长度 15/65 等）→ ``400 VALIDATION_ERROR``、``field: licence``，消息与日志不含输入值。"""
    lic = fake_licence()
    s = session()
    call = Rec(s)
    r = call("PUT", "/me/data-licence", json=body_of(_bad_values(lic)[case]))
    err = assert_err(r, 400, "VALIDATION_ERROR")
    assert "licence" in fields(err)
    assert leak_count(lic, r.text) == 0, "400 错误信封含输入片段"
    assert leak_count(lic, logs()) == 0, "日志含输入片段"
    assert call("GET", "/me/data-licence").json()["status"] == "not_set"


def test_surrounding_whitespace_is_trimmed_and_accepted(session: Callable[..., SimpleNamespace]) -> None:
    lic = fake_licence(16)
    r = Rec(session())("PUT", "/me/data-licence", json=body_of("  " + lic + "\t"))
    assert r.status_code == 202 and leak_count(lic, r.text) == 0


@pytest.mark.parametrize("n", [16, 64])
def test_length_bounds_accepted(session: Callable[..., SimpleNamespace], n: int) -> None:
    lic = fake_licence(n)
    r = Rec(session())("PUT", "/me/data-licence", json=body_of(lic))
    assert r.status_code == 202 and leak_count(lic, r.text) == 0


def test_same_licence_second_user_409_in_use_then_free_after_delete(session: Callable[..., SimpleNamespace],
                                                                    logs: Callable[[], str]) -> None:
    """§9：两个用户 PUT 同一证书 → 第二个 ``409 DATA_LICENCE_IN_USE``（信封不含证书、不暴露占用者）；第一个 DELETE 后第二个可设置。"""
    lic = fake_licence()
    a, b = session(), session()
    ca, cb = Rec(a), Rec(b)
    assert ca("PUT", "/me/data-licence", json=body_of(lic)).status_code == 202
    r = cb("PUT", "/me/data-licence", json=body_of(lic, tier="free"))
    assert_err(r, 409, "DATA_LICENCE_IN_USE")
    assert leak_count(lic, r.text) == 0 and a.user.username not in r.text and str(a.user.id) not in r.text
    assert cb("GET", "/me/data-licence").json()["status"] == "not_set"
    assert ca("DELETE", "/me/data-licence").status_code == 204
    assert cb("PUT", "/me/data-licence", json=body_of(lic)).status_code == 202
    assert leak_count(lic, "\n".join(ca.bodies + cb.bodies)) == 0 and leak_count(lic, logs()) == 0


def test_not_set_shape_patch_test_409_and_delete_idempotent(session: Callable[..., SimpleNamespace]) -> None:
    s = session()
    call = Rec(s)
    g = call("GET", "/me/data-licence")
    assert g.status_code == 200
    assert_status_shape(g.json())
    assert g.json()["status"] == "not_set" and all(g.json()[k] is None for k in STATUS_KEYS - {"status"})
    assert call("GET", "/me").json()["data_licence_status"] == "not_set"
    assert_err(call("PATCH", "/me/data-licence", json={"tier": "free"}), 409, "DATA_LICENCE_NOT_SET")
    assert_err(call("POST", "/me/data-licence/test"), 409, "DATA_LICENCE_NOT_SET")
    for _ in range(2):
        r = call("DELETE", "/me/data-licence")
        assert r.status_code == 204 and r.content == b""


def test_db_stores_ciphertext_only_and_api_reads_status_view(session: Callable[..., SimpleNamespace],
                                                             sql: Callable[..., Any]) -> None:
    """plan 2.1B-1：只存 HPKE 密文（无末几位或指纹）；``licence_hmac`` 非空；有不含密文的视图 ``user_data_licence_status``。

    注意：这里读基表的是测试夹具的库属主连接（核对落库形态），不是 api；api 角色 ``aia_api`` 读密文列必须被拒，
    见 :func:`test_api_role_cannot_select_ciphertext`。"""
    lic = fake_licence()
    s = session()
    assert Rec(s)("PUT", "/me/data-licence", json=body_of(lic)).status_code == 202
    row = sql("SELECT ciphertext IS NOT NULL, licence_hmac IS NOT NULL, octet_length(ciphertext) "
              "FROM app.user_data_licences WHERE user_id=:u AND deleted_at IS NULL", u=s.user.id)
    assert row and row[0][0] and row[0][1] and row[0][2] > len(lic)
    def columns(table: str) -> set[str]:
        return {c for (c,) in sql("SELECT column_name FROM information_schema.columns WHERE table_name=:t", t=table)}

    # 阳性对照：基表确有密文与 HMAC 列，检测正则必须命中；阴性对照：视图（api 读取面）一个都不命中
    assert {"ciphertext", "licence_hmac"} <= {c for c in columns("user_data_licences") if FORBIDDEN_KEY.search(c)}
    cols = columns("user_data_licence_status")
    assert cols and not {c for c in cols if FORBIDDEN_KEY.search(c)}, sorted(c for c in cols if FORBIDDEN_KEY.search(c))
    assert {"last_verified_at", "last_error_code", "last_error_at"} <= cols  # 契约 DataLicenceStatus 允许的 last_* 列
    assert db_hits(sql, lic) == []


def test_api_role_cannot_select_ciphertext(authdb: SimpleNamespace, sql: Callable[..., Any]) -> None:
    """T-O10 分库角色（deploy/db/roles/grants.sql，契约 v0.2.6 验收）：``aia_api`` 不能 SELECT 基表的
    ``ciphertext`` / ``licence_hmac`` 列，只能读视图 ``user_data_licence_status``。只查权限目录，不读任何取值。
    本测试库未施加分库角色时 skip（aia-t01 实例上已人工只读核对，见 T-T22.md）。"""
    if not sql("SELECT 1 FROM pg_roles WHERE rolname='aia_api'"):
        pytest.skip("测试库未施加 T-O10 分库角色（aia_api 不存在）；由 deploy/db/roles 在部署时施加")
    if not sql("SELECT 1 FROM information_schema.tables WHERE table_schema='app' AND table_name='user_data_licences'"):
        pytest.xfail(T_B45)
    for col in ("ciphertext", "licence_hmac"):
        assert sql("SELECT has_column_privilege('aia_api', 'app.user_data_licences', :c, 'SELECT')", c=col)[0][0] is False, col
    assert sql("SELECT has_table_privilege('aia_api', 'app.user_data_licence_status', 'SELECT')")[0][0] is True


def test_admin_pause_not_set_409(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any]) -> None:
    target = mkuser()
    admin = Rec(session(mkuser(role="admin")))
    assert_err(admin("POST", f"/admin/data-licences/{target.id}/pause", json={"reason": "x"}), 409, "DATA_LICENCE_NOT_SET")
    user = Rec(session())
    # 契约 §1.3 / §7.9：非管理员访问任何 /admin/* 一律 404 NOT_FOUND，不暴露其存在
    assert_err(user("GET", "/admin/data-licences"), 404, "NOT_FOUND")


# ======================= 组 2：限速按用户/证书（接口层） =======================
def test_put_rate_limit_10_per_hour_other_user_unaffected(session: Callable[..., SimpleNamespace]) -> None:
    a, b = Rec(session()), Rec(session())
    lic = fake_licence()
    for i in range(10):
        r = a("PUT", "/me/data-licence", json=body_of(lic))
        assert r.status_code == 202, (i, r.status_code)
    r = a("PUT", "/me/data-licence", json=body_of(lic))
    assert_err(r, 429, "RATE_LIMITED")
    assert leak_count(lic, r.text) == 0
    assert b("PUT", "/me/data-licence", json=body_of(fake_licence())).status_code == 202


def test_verify_rate_limit_5_per_hour_other_user_unaffected(session: Callable[..., SimpleNamespace]) -> None:
    a, b = Rec(session()), Rec(session())
    assert a("PUT", "/me/data-licence", json=body_of(fake_licence())).status_code == 202
    assert b("PUT", "/me/data-licence", json=body_of(fake_licence())).status_code == 202
    codes = [a("POST", "/me/data-licence/test").status_code for _ in range(5)]
    if set(codes) == {503}:
        pytest.skip("测试环境 ingest 暂停（503 INGEST_PAUSED），无法计数")
    assert codes == [202] * 5
    assert_err(a("POST", "/me/data-licence/test"), 429, "RATE_LIMITED")
    assert b("POST", "/me/data-licence/test").status_code == 202


# ======================= 组 3：证书无效/过期/未设置时的降级（接口层） =======================
@pytest.mark.xfail(strict=False, reason=T_B45_B04A)
@pytest.mark.parametrize("status", ["invalid", "expired", "quota_exceeded", "paused_by_admin", "not_set"])
def test_unusable_licence_reads_degrade_and_refresh_409(session: Callable[..., SimpleNamespace], sql: Callable[..., Any],
                                                        status: str) -> None:
    """§9：B 证书不可用 → ``GET /quotes`` 200、``data_status ∈ {stale, unavailable}``、gaps 含 data_licence_unavailable；
    ``POST /suggestions/refresh`` → ``409 DATA_LICENCE_UNAVAILABLE``、``details.status`` 为当前状态。"""
    s = session()
    call = Rec(s)
    if status != "not_set":
        assert call("PUT", "/me/data-licence", json=body_of(fake_licence())).status_code == 202
        extra = ", expires_on = DATE '2026-01-01'" if status == "expired" else ""
        sql(f"UPDATE app.user_data_licences SET status=:s{extra} WHERE user_id=:u AND deleted_at IS NULL", s=status, u=s.user.id)
    assert call("GET", "/me/data-licence").json()["status"] == status
    q = call("GET", "/quotes", params={"codes": "600000.SH"})
    assert q.status_code == 200, q.text[:300]
    item = q.json()["items"][0]
    assert item["data_status"] in {"stale", "unavailable"}
    assert "data_licence_unavailable" in {g["reason"] for g in item["gaps"]}
    r = call("POST", "/suggestions/refresh", json={"security_code": "600000.SH"})
    err = assert_err(r, 409, "DATA_LICENCE_UNAVAILABLE")
    assert err["details"]["status"] == status
