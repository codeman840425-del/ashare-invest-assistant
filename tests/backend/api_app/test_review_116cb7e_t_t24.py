"""T-T24（编排补充 c）：review-116cb7e.md m7 要求补的三组用例——蜜罐、用户级暂停（holds）、改密限速。

T-T23 已覆盖：蜜罐 website / 1 秒前 / 未来时间命中、未命中、未知字段 400、不耗邀请码、计入 IP 限速、closed 503；
暂停期 PUT / DELETE / test / resume、证书已删 resume → not_set。本文件补上评审表中仍缺的断言：

- 蜜罐：两者都中 → ``trigger=both``；审计 detail **恰好**是 ``{"trigger": …}``、actor 为空；
  蜜罐 + 重名 → 409、蜜罐 + 无效邀请码 → 400（校验顺序与 §7.1 一致，都不建用户、不耗码、不写蜜罐审计）。
- holds（``app.user_data_licence_holds``，review M1 / 迁移 0010）：pause 写一条暂停记录（user_id 主键）；
  DELETE 证书后记录仍在；resume 删除记录；证书已删时 resume → 204 not_set 且记录清空；
  重复 pause 幂等 204（契约 v0.2.8 #17⑤，T-B03e be607b3）——不改状态、不写审计与事件，记录只有一条；
  证书已删时重复 pause 也是 204（review m4）。
- 冷却继承（review m1 → T-B03e，迁移 0012）：quota_exceeded 冷却中 DELETE 再 PUT 同一证书 → 恢复原状态与
  paused_until，不入队验证；换一张证书 → pending_verification。
- 改密限速（review M5，``ensure_not_limited``）：同一用户旧密码错 5 次各 400，第 6 次 429 RATE_LIMITED + Retry-After；
  超限后用**正确**旧密码也是 429 且密码未改；限速按用户——另一个用户不受影响。

版本 / 功能门：后端 /meta/enums.version < v0.2.8 → imperative xfail（owner 见各常量）；T-B03e 的行为以
``app.user_data_licence_cooldowns`` 表（迁移 0012）是否存在为门。
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_spec = importlib.util.spec_from_file_location("tt24_t23_helpers", Path(__file__).with_name("test_contract_v028_t_t23.py"))
_t23 = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_t23)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:
    pytest.skip(str(exc), allow_module_level=True)

authdb, sql, app_client, mkuser, session, make_settings = (
    _t23.authdb, _t23.sql, _t23.app_client, _t23.mkuser, _t23.session, _t23.make_settings)
API, assert_err, reg, new_name, new_pw = _t23.API, _t23.assert_err, _t23.reg, _t23.new_name, _t23.new_pw
Rec, fake_licence, put, live_row, licence_ids = _t23.Rec, _t23.fake_licence, _t23.put, _t23.live_row, _t23.licence_ids
verify_intents, set_status, leak_count = _t23.verify_intents, _t23.set_status, _t23.leak_count
require_v028, _db_now, _honeypot_audits, _user_count, _now_ms = (
    _t23.require_v028, _t23._db_now, _t23._honeypot_audits, _t23._user_count, _t23._now_ms)
O_B03D = _t23.O_B03D

O_B03E = ("后端 T-B03e（契约 v0.2.8 #17 补充：重复暂停幂等、冷却中删除后重提恢复状态；be607b3 / 迁移 0012，"
          "在本地 main，未推 origin）")
O_M5 = "后端 T-B03d（review M5：改密先查限速 ensure_not_limited，超限后正确旧密码也 429；116cb7e，未推 origin）"

pytestmark = [pytest.mark.integration, pytest.mark.contract]


def _has_table(sql: Callable[..., Any], qualified: str) -> bool:
    return sql("SELECT to_regclass(:t) IS NOT NULL", t=qualified)[0][0]


def require_b03e(sql: Callable[..., Any]) -> None:
    if not _has_table(sql, "app.user_data_licence_cooldowns"):
        pytest.xfail(O_B03E + "；库中无 app.user_data_licence_cooldowns")


def holds(sql: Callable[..., Any], uid: str) -> list[Any]:
    return sql("SELECT user_id::text, paused_at FROM app.user_data_licence_holds WHERE user_id = :u", u=uid)


def _pause(acall: Any, uid: str, pause: bool) -> Any:
    return acall("POST", f"/admin/data-licences/{uid}/{'pause' if pause else 'resume'}", json={"reason": "T-T24"})


def _audits_for(sql: Callable[..., Any], uid: str, since: Any) -> list[str]:
    return [r[0] for r in sql("SELECT action FROM app.audit_logs WHERE target_id = :u AND at >= :t ORDER BY at",
                              u=uid, t=since)]


def _licence_events(sql: Callable[..., Any], uid: str) -> int:
    return sql("SELECT count(*) FROM ops.data_licence_events WHERE user_id = :u", u=uid)[0][0]


# =============================== 蜜罐 ===============================
def test_honeypot_both_trigger_and_exact_audit_detail(app_client: Callable[..., Any], sql: Callable[..., Any]) -> None:
    """website 非空且 1 秒前提交 → trigger=both；审计 detail 恰好 {"trigger": "both"}，actor 为空；不建用户。"""
    c = app_client("open")
    require_v028(c, O_B03D)
    name = new_name()
    t0 = _db_now(sql)
    r = c.post(f"{API}/auth/register", json=reg(name, new_pw(), website="x", form_started_at=_now_ms() - 1000))
    assert r.status_code == 201 and set(r.json()) == {"id", "username", "status"}, r.text[:300]
    assert _user_count(sql, name) == 0
    rows = sql("SELECT detail, actor_id, actor_role FROM app.audit_logs "
               "WHERE action='auth.register_honeypot' AND at >= :t", t=t0)
    assert len(rows) == 1
    assert rows[0].detail == {"trigger": "both"} and rows[0].actor_id is None


@pytest.mark.parametrize("trap,expect", [({"website": "x"}, "website"), ({"form_started_at": "FAST"}, "too_fast")])
def test_honeypot_single_trigger_detail_is_exact(app_client: Callable[..., Any], sql: Callable[..., Any],
                                                 trap: dict[str, Any], expect: str) -> None:
    c = app_client("open")
    require_v028(c, O_B03D)
    if trap.get("form_started_at") == "FAST":
        trap = {"form_started_at": _now_ms() - 1000}
    t0 = _db_now(sql)
    assert c.post(f"{API}/auth/register", json=reg(new_name(), new_pw(), **trap)).status_code == 201
    rows = sql("SELECT detail FROM app.audit_logs WHERE action='auth.register_honeypot' AND at >= :t", t=t0)
    assert [r.detail for r in rows] == [{"trigger": expect}]


def test_honeypot_with_taken_username_is_409(session: Callable[..., SimpleNamespace], app_client: Callable[..., Any],
                                             sql: Callable[..., Any]) -> None:
    """蜜罐 + 重名 → 409（重名检查先于蜜罐，顺序与 §7.1 一致），不写蜜罐审计、不多建用户。"""
    s = session()
    c = app_client("open")
    require_v028(c, O_B03D)
    t0 = _db_now(sql)
    r = c.post(f"{API}/auth/register", json=reg(s.user.username, new_pw(), website="x"))
    assert r.status_code == 409, r.text[:300]
    assert _user_count(sql, s.user.username) == 1
    assert _honeypot_audits(sql, t0) == []


def test_honeypot_with_invite_409_and_bad_code_400_do_not_consume(session: Callable[..., SimpleNamespace],
                                                                  mkuser: Callable[..., Any],
                                                                  app_client: Callable[..., Any],
                                                                  sql: Callable[..., Any]) -> None:
    """invite 模式：蜜罐 + 无效码 → 400；蜜罐 + 重名（有效码）→ 409；两者都不耗码、不建用户。"""
    admin = session(mkuser(role="admin"))
    require_v028(admin.client, O_B03D)
    other = mkuser()
    inv = Rec(admin)("POST", "/admin/invites", json={"ttl_h": 24})
    assert inv.status_code == 201, inv.text[:300]
    code, inv_id = inv.json()["code"], inv.json()["id"]
    bad = app_client("invite").post(f"{API}/auth/register", json=reg(new_name(), new_pw(), invite_code="Z" * len(code),
                                                                     apply_note="说明", website="x"))
    assert bad.status_code == 400, bad.text[:300]
    dup = app_client("invite").post(f"{API}/auth/register", json=reg(other.username, new_pw(), invite_code=code,
                                                                     apply_note="说明", website="x"))
    assert dup.status_code == 409, dup.text[:300]
    assert sql("SELECT used_count, used_at FROM app.invite_codes WHERE id=:i", i=inv_id)[0] == (0, None)


# =============================== 用户级暂停（holds） ===============================
def test_holds_written_on_pause_kept_on_delete_cleared_on_resume(session: Callable[..., SimpleNamespace],
                                                                  mkuser: Callable[..., Any],
                                                                  sql: Callable[..., Any]) -> None:
    s = session()
    require_v028(s.client, O_B03D)
    call, admin = Rec(s), Rec(session(mkuser(role="admin")))
    assert holds(sql, s.user.id) == []
    assert put(call, fake_licence()).status_code == 202
    assert holds(sql, s.user.id) == [], "仅设置证书不应写暂停记录"
    assert _pause(admin, s.user.id, True).status_code == 204
    h = holds(sql, s.user.id)
    assert len(h) == 1 and h[0][1] is not None
    assert live_row(sql, s.user.id).status == "paused_by_admin"
    assert call("DELETE", "/me/data-licence").status_code == 204
    assert len(holds(sql, s.user.id)) == 1, "DELETE 证书不得解除暂停记录"
    assert _pause(admin, s.user.id, False).status_code == 204
    assert holds(sql, s.user.id) == []
    assert call("GET", "/me/data-licence").json()["status"] == "not_set"


def test_holds_resume_with_live_licence_goes_pending(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                                     sql: Callable[..., Any], authdb: SimpleNamespace) -> None:
    s = session()
    require_v028(s.client, O_B03D)
    call, admin = Rec(s), Rec(session(mkuser(role="admin")))
    assert put(call, fake_licence()).status_code == 202
    assert _pause(admin, s.user.id, True).status_code == 204
    assert _pause(admin, s.user.id, False).status_code == 204
    assert holds(sql, s.user.id) == []
    assert live_row(sql, s.user.id).status == "pending_verification"


def test_holds_pause_without_licence_is_409_not_set_and_no_hold(session: Callable[..., SimpleNamespace],
                                                                 mkuser: Callable[..., Any],
                                                                 sql: Callable[..., Any]) -> None:
    s = session()
    require_v028(s.client, O_B03D)
    admin = Rec(session(mkuser(role="admin")))
    assert_err(_pause(admin, s.user.id, True), 409, "DATA_LICENCE_NOT_SET")
    assert holds(sql, s.user.id) == []


def test_holds_repeat_pause_idempotent_204_no_audit_no_event(session: Callable[..., SimpleNamespace],
                                                             mkuser: Callable[..., Any],
                                                             sql: Callable[..., Any]) -> None:
    """契约 v0.2.8 #17⑤（T-B03e）：已暂停再 pause → 204，状态不变，不写审计、不写事件，暂停记录仍一条、paused_at 不变；
    证书已删后再 pause 也是 204（review m4）。"""
    s = session()
    require_v028(s.client, O_B03D)
    require_b03e(sql)
    call, admin = Rec(s), Rec(session(mkuser(role="admin")))
    assert put(call, fake_licence()).status_code == 202
    assert _pause(admin, s.user.id, True).status_code == 204
    h0, ev0, t0 = holds(sql, s.user.id), _licence_events(sql, s.user.id), _db_now(sql)
    assert _pause(admin, s.user.id, True).status_code == 204
    assert holds(sql, s.user.id) == h0
    assert _licence_events(sql, s.user.id) == ev0
    assert _audits_for(sql, s.user.id, t0) == [], "重复暂停不得写审计"
    assert live_row(sql, s.user.id).status == "paused_by_admin"
    assert call("DELETE", "/me/data-licence").status_code == 204
    t1 = _db_now(sql)
    assert _pause(admin, s.user.id, True).status_code == 204, "证书已删后重复暂停应幂等 204（review m4）"
    assert holds(sql, s.user.id) == h0 and _audits_for(sql, s.user.id, t1) == []


def test_holds_legacy_paused_row_without_hold_is_backfilled_on_repeat_pause(session: Callable[..., SimpleNamespace],
                                                                            mkuser: Callable[..., Any],
                                                                            sql: Callable[..., Any]) -> None:
    """T-B03e：0010 之前的旧数据（行已 paused_by_admin、无暂停记录）再 pause → 204 并补上暂停记录。"""
    s = session()
    require_v028(s.client, O_B03D)
    require_b03e(sql)
    call, admin = Rec(s), Rec(session(mkuser(role="admin")))
    assert put(call, fake_licence()).status_code == 202
    set_status(sql, s.user.id, "paused_by_admin")
    assert holds(sql, s.user.id) == []
    assert _pause(admin, s.user.id, True).status_code == 204
    assert len(holds(sql, s.user.id)) == 1


# =============================== 冷却继承（review m1 → T-B03e） ===============================
def test_cooldown_survives_delete_then_put_same_licence(session: Callable[..., SimpleNamespace], sql: Callable[..., Any],
                                                        authdb: SimpleNamespace) -> None:
    import datetime as dt

    s = session()
    require_v028(s.client, O_B03D)
    require_b03e(sql)
    call, lic = Rec(s), fake_licence()
    assert put(call, lic).status_code == 202
    until = dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)
    set_status(sql, s.user.id, "quota_exceeded", until)
    pu0 = live_row(sql, s.user.id).paused_until
    assert call("DELETE", "/me/data-licence").status_code == 204
    n0 = verify_intents(authdb.redis, licence_ids(sql, s.user.id))
    r = put(call, lic)
    assert r.status_code == 202 and r.json()["status"] == "quota_exceeded", r.text[:300]
    row = live_row(sql, s.user.id)
    assert (row.status, row.paused_until) == ("quota_exceeded", pu0)
    assert verify_intents(authdb.redis, licence_ids(sql, s.user.id)) == n0, "冷却中重提不得入队验证"
    # 对照：换一张证书不继承冷却
    assert call("DELETE", "/me/data-licence").status_code == 204
    r2 = put(call, fake_licence())
    assert r2.status_code == 202 and r2.json()["status"] == "pending_verification", r2.text[:300]
    assert leak_count(lic, "\n".join(call.bodies)) == 0


# =============================== 改密限速（review M5） ===============================
def _chpw(s: SimpleNamespace, old: str, new: str) -> Any:
    return s.client.post(f"{API}/auth/password", json={"old_password": old, "new_password": new},
                         headers={"X-CSRF-Token": s.csrf})


def test_change_password_wrong_old_5x400_then_429(session: Callable[..., SimpleNamespace],
                                                  app_client: Callable[..., Any]) -> None:
    """契约 §7.1：旧密码错误按用户计数——5 次 400，第 6 次 429 RATE_LIMITED + Retry-After；另一用户不受影响。"""
    s, other = session(), session()
    for _ in range(5):
        assert_err(_chpw(s, new_pw(), new_pw()), 400, "VALIDATION_ERROR")
    r = _chpw(s, new_pw(), new_pw())
    assert_err(r, 429, "RATE_LIMITED")
    assert int(r.headers.get("retry-after", "0")) > 0
    assert _chpw(other, new_pw(), new_pw()).status_code == 400, "限速应按用户，不殃及他人"
    # 密码未变：原密码仍可登录
    assert app_client().post(f"{API}/auth/login",
                             json={"username": s.user.username, "password": s.user.password}).status_code == 200


def test_change_password_correct_old_after_limit_is_429_and_unchanged(session: Callable[..., SimpleNamespace],
                                                                      app_client: Callable[..., Any]) -> None:
    """review M5：先查限速——超限后即使旧密码正确也 429，密码不变（新密码不能登录）。"""
    s = session()
    require_v028(s.client, O_M5)
    for _ in range(5):
        assert _chpw(s, new_pw(), new_pw()).status_code == 400
    new = new_pw()
    r = _chpw(s, s.user.password, new)
    assert_err(r, 429, "RATE_LIMITED")
    assert int(r.headers.get("retry-after", "0")) > 0
    c = app_client()
    assert c.post(f"{API}/auth/login", json={"username": s.user.username, "password": new}).status_code == 401
    assert app_client().post(f"{API}/auth/login",
                             json={"username": s.user.username, "password": s.user.password}).status_code == 200
