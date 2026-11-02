"""T-T25 追加（第三批）：三组集成测试，一次性 testcontainers 库（T-T22/T-T23 的 ``authdb``），绝不连共享库。

A. ``test_reg_closed_*``：``registration_mode=closed`` 下 13 种请求体（12 种 → ``503 REGISTRATION_CLOSED``，
   超过框架上限的 1 种 → ``413 PAYLOAD_TOO_LARGE``）。依据：契约 v0.2.9 §7.1 判定顺序 / 变更表 #16（架构师裁定 1）、
   §4 #22 与错误码表 413。原待决问题“/auth/register 上 413 与 503 谁先”已由**追加裁定 E**
   （T-B46-47-rulings.md，提交 4532478）解决：超过全局上限的请求体由中间件在路由之前返回
   ``413 PAYLOAD_TOO_LARGE``，即使 ``registration_mode=closed`` 也先于 ``503 REGISTRATION_CLOSED``；
   契约 #16 的“一律先返回 503”只适用于未超上限的请求。本文件的 413 用例即裁定 E 要求的测试员用例。
B. ``test_cooldown_*`` / ``test_resume_*``：删除后在冷却期内重新提交同一证书（契约 v0.2.8 #13 补充、§7.1 DELETE
   行）——契约规定的不是错误码，而是 ``202`` 并**恢复**删除前的 ``status`` 与 ``paused_until``、到期前不验证；
   换证书照常验证。T-T25 裁定 #5（契约 #32 ①、plan 7.3）：到期判定是半开区间——到期时刻 = ``paused_until``（非 null）
   或删除时刻 + 24h（null），仅当 now < 到期时刻有效，now = 到期时刻即过期；``test_cooldown_boundary_*`` 以注入
   时钟（服务层函数的 ``now`` 参数，固定时刻，不依赖墙钟）覆盖到期前 1µs / 恰好 / 后 1µs。resume 重复调用：结果相同、无重复副作用（暂停记录、验证意图、证书事件、通知、审计）。
C. ``test_purge_attack_*``：删除用户数据 CLI（plan §7.3，迁移 0011/0013）的触发器攻击。威胁模型（按代码理解）：
   不可变表只靠“属主是 purging 用户”这一数据状态门放行删改，所以攻击面是 ① 非 aia_maint 角色把人置 purging、
   ② 以数据库对象（触发器 / 函数 / 关触发器 / session_replication_role）绕过或篡改这道门、
   ③ 有建触发器权限的人在 CLI 删除路径上预埋触发器，借删除把数据另存（窃取）或让删除静默跳过（保留）。
   ①② 用测试容器里的临时角色（aia_maint、普通 DML 角色，测试侧近似运维 grants.sql）验证全部被拒；
   ③ 以库属主身份预埋，断言“保留”类攻击使 CLI 整体回滚。
   T-T25 裁定 #4（docs 46538a6 plan 7.3，reports/T-T25-rulings.md 二.4）：库属主 / 超级用户 / 能执行 DDL 的角色
   **不在**删除 CLI 的威胁模型内，不再要求 CLI 防御属主级攻击；改为防误配的**触发器白名单自检**——清单内表上
   出现白名单（表 + 触发器名 + 函数名）外的非内部触发器时，dry-run 列出差异，``--execute`` 拒绝执行（非零退出、
   不删任何行，无跳过参数）。``test_purge_trigger_allowlist_*`` 按此断言；CLI 尚未实现自检时
   xfail(strict=False)，owner 后端 T-B16。只在一次性 testcontainers 库里预埋 / 清理触发器。

本地 main 已实现、origin 缺对应提交的部分：按能力（而非行为）检测后 imperative xfail，写明依赖的后端提交。
不联网、不调用麦蕊；证书为运行时随机生成的测试值，不输出。
"""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import json
import secrets
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("tt25c_cli_t24", _HERE / "test_delete_user_data_cli_t_t24.py")
_t24 = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_t24)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:
    pytest.skip(str(exc), allow_module_level=True)
_t23 = _t24._t23

authdb, sql, app_client, mkuser, session, make_settings = (
    _t23.authdb, _t23.sql, _t23.app_client, _t23.mkuser, _t23.session, _t23.make_settings)
roles, cli, victim = _t24.roles, _t24.cli, _t24.victim
API, assert_err, Rec, fake_licence, put = _t23.API, _t23.assert_err, _t23.Rec, _t23.fake_licence, _t23.put
leak_count, live_row, set_status, licence_ids, verify_intents = (
    _t23.leak_count, _t23.live_row, _t23.set_status, _t23.licence_ids, _t23.verify_intents)
_run, _footprint, MAINT = _t24._run, _t24._footprint, _t24.MAINT

pytestmark = [pytest.mark.integration]

O_REG_GATE = ("后端 T-B03e 追加 f72b8c7（closed 模式先于请求体校验，架构师裁定 1）：在本地 main，未推 origin；"
              "所测后端没有 _RegistrationGateRoute")
O_COOLDOWN = ("后端 T-B04a-x / T-B03e（契约 v0.2.8 #13 补充：删除后重新提交同一证书不能跳过冷却；迁移 0012 "
              "licence_cooldowns 在本地 main，未推 origin）")
O_F22_IDEMP = ("后端 T-B45 / T-B03e（契约 v0.2.9 439746e #26①：resume 幂等——已设置未暂停时 resume 仍写审计；"
               "改 be607b3 的 _admin_transition）")
O_PURGE_TRIGGERS = ("后端 T-B16（T-T25 裁定 #4 / plan 7.3：删除 CLI 在 dry-run 与 --execute 前只读列出清单内表上的"
                    "非内部触发器并与白名单比对——dry-run 报差异，--execute 遇白名单外触发器拒绝执行、非零退出；"
                    "所测 CLI 尚未实现）")


# ============================== A. 关闭注册：13 种请求体 ==============================
def _valid() -> dict[str, Any]:
    return {"username": "tt25c_" + uuid.uuid4().hex[:8], "password": "Tt25cPassw0rd!", "display_name": "示例"}


def _json(o: Any) -> bytes:
    return json.dumps(o, ensure_ascii=False).encode("utf-8")


CT = {"content-type": "application/json"}
#: id → (bytes 请求体, 头)。前 12 种期望 503，最后一种（超过 imports.max_request_bytes）期望 413。
CLOSED_BODIES: dict[str, Callable[[], tuple[bytes, dict[str, str]]]] = {
    "empty": lambda: (b"", CT),
    "empty_object": lambda: (b"{}", CT),
    "invalid_json": lambda: (b'{"username": "abc", ', CT),
    "wrong_content_type": lambda: (_json(_valid()), {"content-type": "text/plain"}),
    "missing_fields": lambda: (_json({"username": "tt25c_only"}), CT),
    "wrong_types": lambda: (_json({"username": 123, "password": ["x"], "display_name": {"a": 1}}), CT),
    "overlong_fields": lambda: (_json({**_valid(), "username": "a" * 5000, "display_name": "长" * 5000,
                                       "apply_note": "n" * 10000}), CT),
    "extra_fields": lambda: (_json({**_valid(), "is_admin": True, "role": "admin"}), CT),
    "json_array": lambda: (_json([_valid()]), CT),
    "json_null": lambda: (b"null", CT),
    "valid_body": lambda: (_json(_valid()), CT),
    "wrong_encoding": lambda: ('{"username": "测试用户", "password": "x", "display_name": "名"}'.encode("gbk"),
                               {"content-type": "application/json; charset=utf-8"}),
}


def _require_reg_gate() -> None:
    auth = importlib.import_module("app.api.v1.auth")
    if not hasattr(auth, "_RegistrationGateRoute"):
        pytest.xfail(O_REG_GATE)


def _users(sql: Callable[..., Any]) -> int:
    return sql("SELECT count(*) FROM app.users")[0][0]


def _honeypot(sql: Callable[..., Any], t0: Any) -> int:
    return sql("SELECT count(*) FROM app.audit_logs WHERE action = 'auth.register_honeypot' AND at >= :t", t=t0)[0][0]


def test_reg_closed_case_table_has_12_plus_413() -> None:
    assert len(CLOSED_BODIES) == 12


@pytest.mark.parametrize("case", list(CLOSED_BODIES))
def test_reg_closed_every_body_is_503(app_client: Callable[..., Any], sql: Callable[..., Any], case: str) -> None:
    """注册模式最先判定：任何请求体都是同一个 503 REGISTRATION_CLOSED，不出现 400/415/422，不建用户、不写蜜罐审计。"""
    _require_reg_gate()
    n0, t0 = _users(sql), sql("SELECT now()")[0][0]
    body, hdr = CLOSED_BODIES[case]()
    c = app_client("closed")
    r = c.post(f"{API}/auth/register", content=body, headers=hdr)
    err = assert_err(r, 503, "REGISTRATION_CLOSED")
    ref = assert_err(c.post(f"{API}/auth/register", json=_valid()), 503, "REGISTRATION_CLOSED")
    assert {k: v for k, v in err.items() if k != "request_id"} == {k: v for k, v in ref.items() if k != "request_id"}, \
        "响应体须与正常请求体相同（除 request_id）"
    assert "set-cookie" not in r.headers
    assert _users(sql) == n0 and _honeypot(sql, t0) == 0


def test_reg_closed_oversized_is_413_before_mode(app_client: Callable[..., Any], sql: Callable[..., Any],
                                                 config_dir: Path) -> None:
    """超过框架层上限（config/imports.yaml max_request_bytes）→ 413 PAYLOAD_TOO_LARGE {max_bytes}，先于注册模式判定。
    裁定 E（T-B46-47-rulings.md）：closed 模式下超大请求体期望 413，先于 503 REGISTRATION_CLOSED（原待决问题已解决）；
    用户数不变（未进入注册路由）。"""
    import yaml

    limit = int(yaml.safe_load((config_dir / "imports.yaml")
                               .read_text(encoding="utf-8"))["max_request_bytes"])
    n0 = _users(sql)
    body = b'{"username": "' + b"a" * (limit + 1) + b'"}'
    r = app_client("closed").post(f"{API}/auth/register", content=body, headers=CT)
    err = assert_err(r, 413, "PAYLOAD_TOO_LARGE")
    assert err.get("details", {}).get("max_bytes") == limit
    assert _users(sql) == n0


# ============================== B. 冷却与 resume 幂等 ==============================
def _require_cooldown(sql: Callable[..., Any]) -> None:
    if not sql("SELECT to_regclass('app.user_data_licence_cooldowns') IS NOT NULL")[0][0]:
        pytest.xfail(O_COOLDOWN + "：库里没有 app.user_data_licence_cooldowns")


def _side_effects(sql: Callable[..., Any], authdb: SimpleNamespace, uid: str, t0: Any) -> dict[str, int]:
    return {
        "holds": sql("SELECT count(*) FROM app.user_data_licence_holds WHERE user_id = :u", u=uid)[0][0],
        "licence_rows": sql("SELECT count(*) FROM app.user_data_licences WHERE user_id = :u", u=uid)[0][0],
        "events": sql("SELECT count(*) FROM ops.data_licence_events WHERE user_id = :u", u=uid)[0][0],
        "cooldowns": sql("SELECT count(*) FROM app.user_data_licence_cooldowns WHERE user_id = :u", u=uid)[0][0]
        if sql("SELECT to_regclass('app.user_data_licence_cooldowns') IS NOT NULL")[0][0] else 0,
        "notifications": sql("SELECT count(*) FROM app.notifications WHERE user_id = :u", u=uid)[0][0],
        "verify_intents": verify_intents(authdb.redis, licence_ids(sql, uid)),
        "audit": sql("SELECT count(*) FROM app.audit_logs WHERE target_id = CAST(:u AS text) AND at >= :t",
                     u=uid, t=t0)[0][0],
    }


@pytest.mark.parametrize("status", ["quota_exceeded", "ip_limited", "active"])
def test_cooldown_delete_then_resubmit_same_licence_keeps_state(session: Callable[..., SimpleNamespace],
                                                                sql: Callable[..., Any], authdb: SimpleNamespace,
                                                                status: str) -> None:
    """冷却中（quota_exceeded / ip_limited / active 且 paused_until 未到期）DELETE，再于到期前 PUT 同一证书
    → 202，恢复删除前的 status 与 paused_until，不入队验证。契约规定的是 202 + 恢复，而不是错误码。"""
    _require_cooldown(sql)
    s = session()
    call, lic = Rec(s), fake_licence()
    assert put(call, lic).status_code == 202
    until = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)).replace(microsecond=0)
    set_status(sql, s.user.id, status, until)
    g0 = call("GET", "/me/data-licence").json()
    assert call("DELETE", "/me/data-licence").status_code == 204
    assert call("GET", "/me/data-licence").json()["status"] == "not_set"
    n0 = verify_intents(authdb.redis, licence_ids(sql, s.user.id))
    r = put(call, lic)
    assert r.status_code == 202, r.text[:300]
    assert r.json()["status"] == status and r.json()["paused_until"] == g0["paused_until"], r.text[:300]
    row = live_row(sql, s.user.id)
    assert row.status == status and row.paused_until == until
    assert verify_intents(authdb.redis, licence_ids(sql, s.user.id)) == n0, "冷却到期前不得验证"
    assert leak_count(lic, "\n".join(call.bodies)) == 0


def test_cooldown_resubmit_different_licence_verifies(session: Callable[..., SimpleNamespace], sql: Callable[..., Any],
                                                      authdb: SimpleNamespace) -> None:
    """对照：冷却中删除后换成不同证书 → 照常 pending_verification 并入队一次验证。"""
    _require_cooldown(sql)
    s = session()
    call = Rec(s)
    assert put(call, fake_licence()).status_code == 202
    set_status(sql, s.user.id, "quota_exceeded", dt.datetime.now(dt.UTC) + dt.timedelta(hours=2))
    assert call("DELETE", "/me/data-licence").status_code == 204
    n0 = verify_intents(authdb.redis, licence_ids(sql, s.user.id))
    r = put(call, fake_licence())
    assert r.status_code == 202 and r.json()["status"] == "pending_verification", r.text[:300]
    assert r.json()["paused_until"] is None
    assert verify_intents(authdb.redis, licence_ids(sql, s.user.id)) == n0 + 1


def test_cooldown_resubmit_after_expiry_verifies(session: Callable[..., SimpleNamespace], sql: Callable[..., Any],
                                                 authdb: SimpleNamespace) -> None:
    """对照：保留的指纹到 paused_until 为止；到期后再提交同一证书 → 正常验证（把到期时间改到过去模拟）。"""
    _require_cooldown(sql)
    s = session()
    call, lic = Rec(s), fake_licence()
    assert put(call, lic).status_code == 202
    set_status(sql, s.user.id, "quota_exceeded", dt.datetime.now(dt.UTC) + dt.timedelta(hours=2))
    assert call("DELETE", "/me/data-licence").status_code == 204
    assert sql("SELECT count(*) FROM app.user_data_licence_cooldowns WHERE user_id = :u", u=s.user.id)[0][0] == 1
    sql("UPDATE app.user_data_licence_cooldowns SET paused_until = now() - interval '1 minute' WHERE user_id = :u",
        u=s.user.id)
    n0 = verify_intents(authdb.redis, licence_ids(sql, s.user.id))
    r = put(call, lic)
    assert r.status_code == 202 and r.json()["status"] == "pending_verification", r.text[:300]
    assert verify_intents(authdb.redis, licence_ids(sql, s.user.id)) == n0 + 1


#: 冷却边界用例的固定到期时刻（注入时钟；带微秒，验证 1µs 粒度）
EXPIRY = dt.datetime(2031, 3, 4, 5, 6, 7, 123456, tzinfo=dt.UTC)
US = dt.timedelta(microseconds=1)
#: (到期前 1µs, 恰好到期, 到期后 1µs) → 是否仍有效（半开区间 [起点, 到期)）
BOUNDARY = [(-US, True), (dt.timedelta(0), False), (US, False)]
BOUNDARY_IDS = ["minus_1us_valid", "exact_expired", "plus_1us_expired"]


def _cooldown_svc() -> Any:
    svc = importlib.import_module("app.licences.service")
    if not all(hasattr(svc, n) for n in ("purge_expired_cooldowns", "_take_cooldown", "keeps_state")):
        pytest.xfail(O_COOLDOWN + "：所测后端没有可注入时钟的冷却判定函数")
    return svc


def _seed_cooldown(sql: Callable[..., Any], settings: Any, uid: str, status: str,
                   paused_until: dt.datetime | None, deleted_at: dt.datetime) -> bytes:
    """一次性库里直接写一条冷却记录（指纹按被测设置计算；去重摘要是随机测试值，不是证书）。返回去重摘要。"""
    seal = importlib.import_module("app.licences.seal")
    digest = secrets.token_bytes(32)
    fp = seal.cooldown_fingerprint(settings, uuid.UUID(uid), digest)
    sql("DELETE FROM app.user_data_licence_cooldowns WHERE user_id = :u", u=uid)
    sql("INSERT INTO app.user_data_licence_cooldowns (user_id, fingerprint, status, paused_until, deleted_at) "
        "VALUES (:u, :f, :s, :p, :d)", u=uid, f=fp, s=status, p=paused_until, d=deleted_at)
    return digest


def _probe(authdb: SimpleNamespace, svc: Any, settings: Any, uid: str, digest: bytes,
           now: dt.datetime) -> tuple[bool, bool]:
    """在注入的 now 下：(周期清理 purge_expired_cooldowns 后记录是否仍在, 同一证书能否恢复)。每次探测在事务里
    做完后回滚，库不变。（不用 ``~_cooldown_expired(now)`` 直接查：paused_until 为空时 SQL 三值逻辑得 NULL。）"""
    from sqlalchemy import select

    cd = importlib.import_module("app.db.tables.licences").user_data_licence_cooldowns
    with authdb.engine.connect() as conn:
        tx = conn.begin()
        try:
            svc.purge_expired_cooldowns(conn, now)
            alive = conn.execute(select(cd.c.user_id).where(cd.c.user_id == uuid.UUID(uid))).first() is not None
            restored = svc._take_cooldown(conn, settings, uuid.UUID(uid), digest, now) is not None
        finally:
            tx.rollback()
    return alive, restored


@pytest.mark.parametrize("offset,valid", BOUNDARY, ids=BOUNDARY_IDS)
@pytest.mark.parametrize("kind", ["paused_until", "null_until_24h"])
def test_cooldown_boundary_half_open(authdb: SimpleNamespace, sql: Callable[..., Any], mkuser: Callable[..., Any],
                                     make_settings: Callable[..., Any], kind: str, offset: dt.timedelta,
                                     valid: bool) -> None:
    """T-T25 裁定 #5：到期时刻 = paused_until（非 null）或删除时刻 + 24h（null）；now < 到期 → 有效（同一证书恢复
    删除前状态、不验证），now = 到期 → 已过期（按新提交处理），now > 到期 → 已过期。清理与恢复两处口径一致。"""
    _require_cooldown(sql)
    svc = _cooldown_svc()
    settings = make_settings(database_url=authdb.url, redis_url=authdb.redis_url)
    uid = str(mkuser().id)
    if kind == "paused_until":
        digest = _seed_cooldown(sql, settings, uid, "quota_exceeded", EXPIRY, EXPIRY - dt.timedelta(hours=1))
    else:
        digest = _seed_cooldown(sql, settings, uid, "ip_limited", None, EXPIRY - dt.timedelta(hours=24))
    try:
        assert _probe(authdb, svc, settings, uid, digest, EXPIRY + offset) == (valid, valid)
        assert sql("SELECT count(*) FROM app.user_data_licence_cooldowns WHERE user_id = :u", u=uid)[0][0] == 1, \
            "探测在回滚事务里做，记录应仍在"
    finally:
        sql("DELETE FROM app.user_data_licence_cooldowns WHERE user_id = :u", u=uid)


@pytest.mark.parametrize("offset,valid", BOUNDARY, ids=BOUNDARY_IDS)
def test_cooldown_boundary_put_paused_until_not_expired(offset: dt.timedelta, valid: bool) -> None:
    """T-T25 裁定 #5：PUT 行的“paused_until 未到期”同样指 now < paused_until；恰好相等按到期后的新提交处理。
    （active 行；quota_exceeded / ip_limited 不按时间判定，不在本用例。）纯函数，注入 now。"""
    svc = _cooldown_svc()
    row = SimpleNamespace(status="active", paused_until=EXPIRY)
    assert svc.keeps_state(row, EXPIRY + offset) is valid


def test_resume_repeated_is_idempotent(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                       sql: Callable[..., Any], authdb: SimpleNamespace) -> None:
    """pause → resume ×3：第一次恢复（pending_verification、入队一次验证、暂停记录解除）；之后每次 204、
    状态与库行不变，不再入队验证，不新增事件 / 通知 / 暂停记录 / 证书行；审计部分见 O_F22_IDEMP。"""
    s = session()
    _t23.require_v028(s.client, _t23.O_B03D)
    call, admin = Rec(s), Rec(session(mkuser(role="admin")))
    assert put(call, fake_licence()).status_code == 202
    assert admin("POST", f"/admin/data-licences/{s.user.id}/pause", json={"reason": "示例理由"}).status_code == 204
    n_paused = verify_intents(authdb.redis, licence_ids(sql, s.user.id))
    assert admin("POST", f"/admin/data-licences/{s.user.id}/resume", json={"reason": "示例理由"}).status_code == 204
    g1 = call("GET", "/me/data-licence").json()
    assert g1["status"] == "pending_verification"
    t0 = sql("SELECT now()")[0][0]
    row1, fx1 = live_row(sql, s.user.id), _side_effects(sql, authdb, s.user.id, t0)
    assert fx1["holds"] == 0 and fx1["verify_intents"] == n_paused + 1
    for _ in range(2):
        r = admin("POST", f"/admin/data-licences/{s.user.id}/resume", json={"reason": "示例理由"})
        assert r.status_code == 204, r.text[:300]
        assert call("GET", "/me/data-licence").json() == g1
    row2, fx2 = live_row(sql, s.user.id), _side_effects(sql, authdb, s.user.id, t0)
    assert (row2.id, row2.status, row2.paused_until) == (row1.id, row1.status, row1.paused_until)
    strict = {k: fx2[k] - fx1[k] for k in fx2 if k != "audit"}
    assert strict == {k: 0 for k in strict}, strict
    if fx2["audit"] != fx1["audit"]:
        pytest.xfail(f"{O_F22_IDEMP}：重复 resume 新增审计 {fx2['audit'] - fx1['audit']} 条")


# ============================== C. 删除 CLI 的触发器攻击 ==============================
ATTACKS = {
    "create_trigger": "CREATE TRIGGER tt25c_evil AFTER DELETE ON app.user_data_licences FOR EACH ROW "
                      "EXECUTE FUNCTION app.reject_mutation()",
    "replace_gate_function": "CREATE OR REPLACE FUNCTION app.purge_permits(tbl text, op text, o jsonb, n jsonb) "
                             "RETURNS boolean LANGUAGE sql AS $$ SELECT true $$",
    "create_function_in_app": "CREATE FUNCTION app.tt25c_evil() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$",
    "create_function_in_public": "CREATE FUNCTION public.tt25c_evil() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$",
    "disable_purging_guard": "ALTER TABLE app.users DISABLE TRIGGER trg_users_purging_guard",
    "disable_all_triggers": "ALTER TABLE app.audit_logs DISABLE TRIGGER ALL",
    "replication_role": "SET session_replication_role = replica",
    "grant_self_superuser": "ALTER ROLE CURRENT_USER SUPERUSER",
    "delete_immutable_audit": "DELETE FROM app.audit_logs WHERE true",
}


def _plain(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def _require_purge(sql: Callable[..., Any]) -> None:
    _t24._cli()
    _t24._require_0013(sql)


@pytest.mark.parametrize("who", ["maint", "other"])
@pytest.mark.parametrize("attack", list(ATTACKS))
def test_purge_attack_non_owner_cannot_tamper(roles: SimpleNamespace, sql: Callable[..., Any], who: str,
                                              attack: str) -> None:
    """②：aia_maint（CLI 凭据）与普通 DML 角色都不能建 / 换触发器或函数、关触发器、切 replication 角色、提权，
    也不能直接删不可变表；失败后库对象不变。"""
    import psycopg

    _require_purge(sql)
    fn0 = sql("SELECT md5(prosrc) FROM pg_proc WHERE oid = 'app.purge_permits(text,text,jsonb,jsonb)'::regprocedure")
    trg0 = sql("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal")[0][0]
    audits0 = sql("SELECT count(*) FROM app.audit_logs")[0][0]
    with psycopg.connect(_plain(getattr(roles, who))) as c, pytest.raises(psycopg.Error) as ei:
        c.execute(ATTACKS[attack])
        c.execute("SELECT 1")
        c.commit()
    # 42501 权限不足；P0001 / 23001 = 0013 purging 守卫 / 不可变表触发器 RAISE。语法错等其它错误不算“被拒”。
    assert ei.value.sqlstate in {"42501", "P0001", "23001"}, (ei.value.sqlstate, str(ei.value)[:200])
    assert sql("SELECT md5(prosrc) FROM pg_proc WHERE oid = 'app.purge_permits(text,text,jsonb,jsonb)'::regprocedure") == fn0
    assert sql("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal")[0][0] == trg0
    assert sql("SELECT count(*) FROM pg_trigger WHERE NOT tgenabled = 'O' AND NOT tgisinternal")[0][0] == 0
    assert sql("SELECT count(*) FROM pg_proc WHERE proname = 'tt25c_evil'")[0][0] == 0
    assert sql("SELECT rolsuper FROM pg_roles WHERE rolname = :r", r=MAINT if who == "maint" else "tt24_notmaint")[0][0] is False
    assert sql("SELECT count(*) FROM app.audit_logs")[0][0] >= audits0


def test_purge_attack_non_maint_purging_then_delete_immutable(victim: SimpleNamespace, roles: SimpleNamespace,
                                                             sql: Callable[..., Any]) -> None:
    """①：普通角色在同一事务里先把受害人置 purging、再删其审计 / 证书事件——第一步即被拒，整个事务无效。"""
    import psycopg

    _require_purge(sql)
    before = _footprint(sql, victim.uid)
    with psycopg.connect(_plain(roles.other)) as c, pytest.raises(psycopg.Error):
        c.execute("UPDATE app.users SET status = 'purging' WHERE id = %s", (victim.uid,))
        c.execute("DELETE FROM app.audit_logs WHERE target_id = %s", (victim.uid,))
        c.execute("DELETE FROM ops.data_licence_events WHERE user_id = %s", (victim.uid,))
        c.commit()
    assert _footprint(sql, victim.uid) == before
    assert sql("SELECT status FROM app.users WHERE id = :u", u=victim.uid)[0][0] == "approved"


def test_purge_security_definer_functions_pin_search_path(sql: Callable[..., Any]) -> None:
    """删除路径上的函数若是 SECURITY DEFINER，必须固定 search_path（防同名对象劫持后以属主权限执行）。"""
    _require_purge(sql)
    bad = sql("SELECT n.nspname || '.' || p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
              "WHERE n.nspname IN ('app','ops','market') AND p.prosecdef "
              "AND NOT coalesce(array_to_string(p.proconfig, ',') LIKE '%search_path=%', false)")
    assert bad == []


def _plant(sql: Callable[..., Any], body: str, when: str) -> None:
    sql("CREATE TABLE IF NOT EXISTS public.tt25c_loot (licence_id uuid, user_id uuid, at timestamptz DEFAULT now())")
    sql("GRANT INSERT, SELECT ON public.tt25c_loot TO PUBLIC")
    sql(f"CREATE OR REPLACE FUNCTION public.tt25c_plant() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END $$")
    sql("GRANT EXECUTE ON FUNCTION public.tt25c_plant() TO PUBLIC")
    sql(f"CREATE TRIGGER tt25c_plant {when} DELETE ON app.user_data_licences FOR EACH ROW "
        "EXECUTE FUNCTION public.tt25c_plant()")


def _unplant(sql: Callable[..., Any]) -> None:
    sql("DROP TRIGGER IF EXISTS tt25c_plant ON app.user_data_licences")
    sql("DROP FUNCTION IF EXISTS public.tt25c_plant()")
    sql("DROP TABLE IF EXISTS public.tt25c_loot")


def _execute(cli: SimpleNamespace, capsys: pytest.CaptureFixture[str], roles: SimpleNamespace, uid: str) -> Any:
    _t24.use_maint_dsn(cli, roles.maint)
    return _run(cli, capsys, "--user-id", uid, "--execute", confirm=uid)


def test_purge_attack_planted_skip_trigger_rolls_back(cli: SimpleNamespace, victim: SimpleNamespace,
                                                      roles: SimpleNamespace, sql: Callable[..., Any],
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    """③ 保留：预埋 BEFORE DELETE … RETURN NULL 让证书行删除被静默跳过 → CLI 不得报成功、不得半删：
    要么事前拒绝，要么整个事务回滚（用户行仍在、未停在 purging、证书行与暂停记录都在）。"""
    try:
        _plant(sql, "RETURN NULL;", "BEFORE")
        before = _footprint(sql, victim.uid)
        r = _execute(cli, capsys, roles, victim.uid)
        assert r.rc != 0, "删除被静默跳过时 CLI 不得报成功"
        assert _footprint(sql, victim.uid) == before
        assert sql("SELECT status FROM app.users WHERE id = :u", u=victim.uid)[0][0] == "approved"
        assert leak_count(victim.lic, r.text) == 0
    finally:
        _unplant(sql)


def test_purge_trigger_allowlist_dry_run_lists_unlisted(cli: SimpleNamespace, victim: SimpleNamespace,
                                                         sql: Callable[..., Any],
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    """裁定 #4：清单内表（app.user_data_licences）上有白名单外的触发器 → dry-run 仍只读（rc 0、库不变），
    输出列出该触发器（表 + 触发器名 + 函数名中至少触发器名与表）。"""
    try:
        _plant(sql, "RETURN OLD;", "AFTER")
        before = _footprint(sql, victim.uid)
        r = _run(cli, capsys, "--user-id", victim.uid)
        assert leak_count(victim.lic, r.text) == 0
        assert _footprint(sql, victim.uid) == before, "dry-run 必须只读"
        if "tt25c_plant" not in r.text:
            pytest.xfail(f"{O_PURGE_TRIGGERS}：dry-run 未列出白名单外触发器")
        assert r.rc == 0, r.text[-800:]
        assert "app.user_data_licences" in r.text
    finally:
        _unplant(sql)


def test_purge_trigger_allowlist_execute_refuses(cli: SimpleNamespace, victim: SimpleNamespace,
                                                 roles: SimpleNamespace, sql: Callable[..., Any],
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    """裁定 #4：白名单外触发器（这里是一个把被删行另存的 AFTER DELETE 触发器，只含 id）→ ``--execute`` 拒绝执行：
    非零退出、不删任何行（足迹不变、用户未停在 purging）、触发器从未被触发（另存表无行）。"""
    try:
        _plant(sql, "INSERT INTO public.tt25c_loot (licence_id, user_id) VALUES (OLD.id, OLD.user_id); RETURN OLD;",
               "AFTER")
        before = _footprint(sql, victim.uid)
        r = _execute(cli, capsys, roles, victim.uid)
        loot = sql("SELECT count(*) FROM public.tt25c_loot WHERE user_id = :u", u=victim.uid)[0][0]
        assert leak_count(victim.lic, r.text) == 0
        if r.rc == 0:
            pytest.xfail(f"{O_PURGE_TRIGGERS}：--execute 未拒绝（rc 0，另存 {loot} 行，只含 id，测试值）")
        assert loot == 0
        assert _footprint(sql, victim.uid) == before
        assert sql("SELECT status FROM app.users WHERE id = :u", u=victim.uid)[0][0] == "approved"
    finally:
        _unplant(sql)


def test_purge_trigger_allowlist_has_no_skip_flag(cli: SimpleNamespace, capsys: pytest.CaptureFixture[str]) -> None:
    """裁定 #4：自检没有跳过参数——CLI 帮助里不出现 skip/ignore/force 类触发器开关。"""
    with pytest.raises(SystemExit):
        _run(cli, capsys, "--help")
    text = capsys.readouterr().out.lower()
    assert not [w for w in ("--skip-trigger", "--ignore-trigger", "--no-trigger-check", "--force")
                if w in text], text[-800:]
