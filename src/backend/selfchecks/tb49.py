# ruff: noqa: E501  自检脚本：SQL 与检查描述保持单行，便于对照输出
"""T-B49 自检（隔离 PG/Redis，见 ``_common``）：

- (a) 研究候选风险文案：delisting / star_st / st；
- (b) beat 排程 → worker 执行 ``purge_expired_cooldowns``（真实 Redis + PG），间隔来自配置；
- 主密钥：SERVICE_NAME 白名单、只对 api/worker 强制、派生函数缺密钥抛错、ingest 拒绝主密钥；
- 迁移 0017：purpose=horizon、用户级快照必须带 user_id（约束 + 预检查 SQL）；
- fund_t_plus：data_source 为 null 时 ETF/LOF 一律 T+1；
- RC4：行业数据未接入 → 研究候选 gaps 含 ``fit_assessment.sector``；
- 删除用户数据 CLI：只认 ``AIA_MAINT_DATABASE_URL_FILE``；dry-run 拒绝属主/服务账号/有写权限角色；
- OpenAPI 声明 414（nginx 信封，code=URI_TOO_LONG）。
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import secrets
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis as redislib
from _common import DB, RURL, check, engine, err_code, finish, q
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import AuthAbusePolicy, MasterKeyMissingError, Settings, master_key_bytes
from app.main import create_app

KEY = secrets.token_urlsafe(32)
rds = redislib.Redis.from_url(RURL)
rds.flushdb()


def mk(**kw: object) -> Settings:
    base: dict[str, object] = {"database_url": DB, "redis_url": RURL}
    return Settings(**(base | kw))  # type: ignore[arg-type]


def refuses(**kw: object) -> bool:
    try:
        mk(**kw)
    except ValidationError:
        return True
    return False


# ---------------------------------------------------------------- (a) 风险文案
from app.research.content import _RISK_TEXT  # noqa: E402

check(
    _RISK_TEXT["delisting"] == "该证券处于退市整理期（简称带“退”）",
    "(a) delisting 文案 = 退市整理期（简称带“退”）",
)
check(_RISK_TEXT["star_st"] == "该证券被实施退市风险警示（*ST）", "(a) star_st 文案不变")
check(_RISK_TEXT["st"] == "该证券被实施其他风险警示（ST）", "(a) st 文案不变")

# ---------------------------------------------------------------- 主密钥矩阵
for env in ("staging", "production"):
    for svc in ("api", "worker"):
        check(refuses(app_env=env, service_name=svc), f"{env}/{svc} 无主密钥 → 拒绝启动")
        check(
            not refuses(app_env=env, service_name=svc, app_master_key=KEY),
            f"{env}/{svc} 有主密钥 → 可启动",
        )
    for svc in ("beat", "signal-rt", "migrate", "maint-cli", "cooldown-purge"):
        check(
            not refuses(app_env=env, service_name=svc), f"{env}/{svc} 无主密钥 → 可启动（不强制）"
        )
    check(
        refuses(app_env=env, service_name="apii", app_master_key=KEY),
        f"{env} 未知 SERVICE_NAME → 拒绝启动",
    )
    check(
        refuses(app_env=env, service_name="ingest", app_master_key=KEY),
        f"{env}/ingest 持有主密钥 → 拒绝启动",
    )
    check(not refuses(app_env=env, service_name="ingest"), f"{env}/ingest 无主密钥 → 可启动")
check(
    not refuses(app_env="local", service_name="whatever"),
    "local 未知 SERVICE_NAME 不拦（开发便利）",
)
check(
    refuses(app_env="local", service_name="ingest", app_master_key=KEY),
    "local/ingest 持有主密钥 → 同样拒绝",
)

s_beat = mk(app_env="production", service_name="beat")
try:
    master_key_bytes(s_beat)
    ok = False
except MasterKeyMissingError:
    ok = True
check(ok, "非 local/test 无主密钥时 master_key_bytes 抛 MasterKeyMissingError")
check(
    master_key_bytes(mk(app_env="local")) is None, "local 无主密钥 → None（调用方用进程内临时密钥）"
)
check(
    master_key_bytes(mk(app_env="production", app_master_key=KEY)) == KEY.encode(),
    "有主密钥 → 原值字节",
)

from app.auth import invites  # noqa: E402
from app.common import pagination  # noqa: E402
from app.importing import keys as import_keys  # noqa: E402
from app.licences import seal  # noqa: E402

derived = {
    "invites._key": lambda s: invites._key(s),
    "pagination._signing_key": lambda s: pagination._signing_key(s),
    "importing.keys.derive": lambda s: import_keys.derive(s, "selfcheck"),
    "seal.dedup_key": lambda s: seal.dedup_key(s),
}
for name, fn in derived.items():
    try:
        fn(s_beat)
        ok = False
    except MasterKeyMissingError:
        ok = True
    except TypeError as exc:  # 签名不同：如实报告
        ok = False
        name += f"（签名不符 {exc}）"
    check(ok, f"派生 {name}：production 无主密钥 → 抛错，不回退临时密钥")

from app.workers import ingest as ingest_mod  # noqa: E402

check(ingest_mod.master_key_present({"APP_MASTER_KEY": "x" * 40}), "ingest 检测到 APP_MASTER_KEY")
check(not ingest_mod.master_key_present({"APP_MASTER_KEY": "  "}), "ingest 空白主密钥视为没有")
_old = os.environ.get("APP_MASTER_KEY")
os.environ["APP_MASTER_KEY"] = "y" * 40
_err = io.StringIO()
with contextlib.redirect_stderr(_err):
    rc = ingest_mod.main()
if _old is None:
    os.environ.pop("APP_MASTER_KEY")
else:
    os.environ["APP_MASTER_KEY"] = _old
check(
    rc != 0 and "y" * 40 not in _err.getvalue(), f"ingest main 有主密钥 → 退出 {rc}，消息不含密钥值"
)

# ---------------------------------------------------------------- (b) beat → worker
from app.workers import jobs  # noqa: E402

s_job = mk(app_env="local", cooldown_purge_interval_s=120)
check(
    jobs.schedule(s_job) == {jobs.PURGE_COOLDOWNS: 120},
    "beat 排程表：purge_expired_cooldowns 间隔取配置 120s",
)
check(refuses(cooldown_purge_interval_s=30), "间隔 < 60 拒绝")
os.environ["COOLDOWN_PURGE_INTERVAL_S"] = "900"
check(Settings().cooldown_purge_interval_s == 900, "环境变量 COOLDOWN_PURGE_INTERVAL_S 生效")
os.environ.pop("COOLDOWN_PURGE_INTERVAL_S")

uid_old, uid_new = uuid.uuid4(), uuid.uuid4()
for u in (uid_old, uid_new):
    q(
        "insert into app.users(id, username, password_hash, role, status) values (:i, :n, 'x', 'user', 'approved')",
        i=u,
        n="tb49_" + u.hex[:12],
    )
now = dt.datetime.now(dt.UTC)
q(
    "insert into app.user_data_licence_cooldowns(user_id, fingerprint, status, paused_until) values (:u, :f, 'quota_exceeded', :p)",
    u=uid_old,
    f=os.urandom(32),
    p=now - dt.timedelta(minutes=5),
)
q(
    "insert into app.user_data_licence_cooldowns(user_id, fingerprint, status, paused_until) values (:u, :f, 'quota_exceeded', :p)",
    u=uid_new,
    f=os.urandom(32),
    p=now + dt.timedelta(hours=2),
)

check(jobs.beat_tick(s_job, rds) == [jobs.PURGE_COOLDOWNS], "beat 首轮排程 1 个任务")
check(jobs.beat_tick(s_job, rds) == [], "beat 间隔内第二轮不重复排程")
ttl = rds.ttl(jobs.DUE_PREFIX + jobs.PURGE_COOLDOWNS)
check(0 < ttl <= 120, f"到期键 TTL = 配置间隔（{ttl}s）")
check(rds.llen(jobs.QUEUE_KEY) == 1, "队列里 1 条任务")
payload = json.loads(rds.lindex(jobs.QUEUE_KEY, 0))
check(set(payload) == {"task", "enqueued_at"}, "队列元素只含 task / enqueued_at")
done = jobs.worker_tick(s_job, rds)
check(done == [(jobs.PURGE_COOLDOWNS, "ok")], f"worker 执行 purge_expired_cooldowns → ok {done}")
left = {
    r[0]
    for r in q(
        "select user_id from app.user_data_licence_cooldowns where user_id = any(:u)",
        u=[uid_old, uid_new],
    )
}
check(left == {uid_new}, "到期冷却记录被删除，未到期的保留")
rds.lpush(jobs.QUEUE_KEY, "not-json", json.dumps({"task": "nope"}))
done = jobs.worker_tick(s_job, rds)
check(
    sorted(x[1] for x in done) == ["bad_payload", "unknown"], f"worker 丢弃坏任务/未知任务 {done}"
)
rds.delete(jobs.DUE_PREFIX + jobs.PURGE_COOLDOWNS)
check(jobs.beat_tick(s_job, rds) == [jobs.PURGE_COOLDOWNS], "到期键过期后 beat 再次排程")
bad_db = mk(app_env="local", database_url="postgresql+psycopg://nobody:x@127.0.0.1:1/none")
done = jobs.worker_tick(bad_db, rds)
check(done == [(jobs.PURGE_COOLDOWNS, "failed")], "任务失败只记 failed，worker 不崩")
q("delete from app.user_data_licence_cooldowns where user_id = any(:u)", u=[uid_old, uid_new])

# ---------------------------------------------------------------- 0017
cons = {
    r[0]: r[1]
    for r in q(
        "select conname, pg_get_constraintdef(oid) from pg_constraint "
        "where conrelid = 'app.data_snapshots'::regclass and contype = 'c'"
    )
}
check("'horizon'" in cons.get("ck_data_snapshots_purpose", ""), "0017：purpose CHECK 含 horizon")
check("ck_data_snapshots_user_scoped" in cons, "0017：ck_data_snapshots_user_scoped 存在")
for purpose in ("candidate", "plan", "horizon"):
    try:
        q(
            "insert into app.data_snapshots(purpose, items, hash) values (:p, '{}', 'selfcheck')",
            p=purpose,
        )
        ok = False
    except IntegrityError:
        ok = True
    check(ok, f"0017：purpose={purpose} 且 user_id 为空 → 拒绝")
with engine().connect() as c:
    tx = c.begin()
    c.execute(
        text(
            "insert into app.data_snapshots(purpose, items, hash, user_id) values ('horizon', '{}', 'selfcheck', :u)"
        ),
        {"u": uid_new},
    )
    c.execute(
        text(
            "insert into app.data_snapshots(purpose, items, hash) values ('screen', '{}', 'selfcheck')"
        )
    )
    tx.rollback()
check(True, "0017：horizon + user_id、screen 无 user_id 可写入（已回滚）")
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "m0017",
    Path(__file__).resolve().parents[1] / "migrations/versions/0017_t_b49_snapshot_purpose.py",
)
if _spec is None or _spec.loader is None:
    sys.exit("找不到迁移 0017")
_m = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_m)
    check(list(q(_m.PRECHECK_SQL)) == [], "0017 预检查 SQL 可执行，当前库 0 行")
except Exception as exc:  # noqa: BLE001
    check(False, f"0017 预检查 SQL：{type(exc).__name__}")

# ---------------------------------------------------------------- fund_t_plus 闸门
from app.market_rules.lots import fund_t_plus  # noqa: E402

real_seg = mk().business.market_rules.segment_for(dt.date(2026, 11, 2))
check(
    real_seg is not None and real_seg.t0_round_trip.data_source is None,
    "仓库配置 t0_round_trip.data_source = null",
)
check(
    fund_t_plus(real_seg, security_type="etf", etf_category="gold") == 1,
    "配置段：data_source=null → 黄金 ETF T+1",
)
if real_seg is not None:
    wired = real_seg.model_copy(
        update={
            "t0_round_trip": real_seg.t0_round_trip.model_copy(update={"data_source": "selfcheck"})
        }
    )
    gold_ok = "gold" in wired.t0_round_trip.fund_categories
    check(
        not gold_ok or fund_t_plus(wired, security_type="etf", etf_category="gold") == 0,
        "data_source 非空（模拟接入）→ 类别规则照常（黄金 ETF T+0）",
    )
check(
    fund_t_plus(None, security_type="etf", etf_category="gold") == 1,
    "data_source=null：黄金 ETF → T+1",
)
check(
    fund_t_plus(None, security_type="etf", etf_category="bond", t0_override=True) == 1,
    "data_source=null：人工覆盖 T+0 也不生效 → T+1",
)
check(
    fund_t_plus(None, security_type="etf", is_lof=True, etf_category="money") == 1,
    "data_source=null：LOF → T+1",
)
check(fund_t_plus(None, security_type="stock") == 1, "股票不受闸门影响（段 t_plus）")

# ---------------------------------------------------------------- RC4 gap（经由 POST /candidates）
st = mk(
    app_env="local",
    app_master_key=KEY,
    registration_mode="open",
    session_cookie_secure=False,
    auth_abuse=AuthAbusePolicy(
        register_ip_per_hour=500, register_ip_per_day=500, login_ip_per_minute=500
    ),
)
app = create_app(st)
c0 = TestClient(app)
name = "tb49_" + secrets.token_hex(4)
pw = "Tb49" + secrets.token_urlsafe(12) + "5a"
r = c0.post("/api/v1/auth/register", json={"username": name, "password": pw, "display_name": "T"})
q("update app.users set status = 'approved' where username = :u", u=name)
cl = TestClient(app)
r = cl.post("/api/v1/auth/login", json={"username": name, "password": pw})
hdr = {"X-CSRF-Token": r.json().get("csrf_token", "")}
q(
    "insert into market.securities(code, type, name, exchange, board, listing_status, risk_flag) "
    "values ('600949.SH', 'stock', '自检退', 'SH', 'main', 'listed', 'delisting') "
    "on conflict (code) do update set risk_flag = excluded.risk_flag, type = excluded.type"
)
r = cl.post(
    "/api/v1/candidates",
    headers=hdr,
    json={
        "origin": "manual",
        "security_code": "600949.SH",
        "conditions_to_hold": [
            {
                "text": "季度营收同比为正",
                "verify_by": "2027-03-31",
                "verify_method": "看季报",
                "confidence": "medium",
            }
        ],
    },
)
body = r.json() if r.status_code == 201 else {}
gaps = json.dumps(body, ensure_ascii=False)
check(
    r.status_code == 201,
    f"POST /candidates 201（{r.status_code} {err_code(r)} {r.text[:300] if r.status_code != 201 else ''}）",
)
check(
    "fit_assessment.sector" in gaps and "no_source" in gaps,
    "RC4 启用 → gaps 含 fit_assessment.sector / no_source",
)
check("该证券处于退市整理期（简称带“退”）" in gaps, "delisting 证券的反证文案为最终文案")

# ---------------------------------------------------------------- OpenAPI 414
oa = app.openapi()
resp = {
    k
    for p in oa["paths"].values()
    for op in p.values()
    if isinstance(op, dict)
    for k in op.get("responses", {})
}
body414 = oa["components"]["schemas"].get("UriTooLongBody", {})
check("414" in resp, "OpenAPI 各路由声明 414")
check(
    body414.get("properties", {}).get("code", {}).get("const") == "URI_TOO_LONG"
    and set(body414.get("required", [])) == {"code", "message", "details", "request_id"},
    "414 信封：error{code=URI_TOO_LONG, message, details, request_id}（同 413 形状）",
)

# ---------------------------------------------------------------- 删除用户数据 CLI
from app.cli import delete_user_data as dud  # noqa: E402

os.environ["AIA_MAINT_DATABASE_URL"] = DB
try:
    dud._maint_url()
    ok = False
except SystemExit as exc:
    ok = DB not in str(exc)
os.environ.pop("AIA_MAINT_DATABASE_URL")
check(ok, "CLI：AIA_MAINT_DATABASE_URL 环境变量 → 拒绝（消息不含 DSN）")
_fd, _tmpname = tempfile.mkstemp(prefix="tb49_maint_")
os.close(_fd)
tmp = Path(_tmpname)
tmp.write_text(DB + "\n", encoding="utf-8")
os.environ["AIA_MAINT_DATABASE_URL_FILE"] = str(tmp)
check(dud._maint_url() == DB, "CLI：AIA_MAINT_DATABASE_URL_FILE 读取文件")
os.environ.pop("AIA_MAINT_DATABASE_URL_FILE")
tmp.unlink()

with engine().connect() as c:
    owner_why = dud.dry_run_refusal(c)
    c.execute(text("SET ROLE aia_maint"))
    maint_why = dud.dry_run_refusal(c)
    c.execute(text("RESET ROLE"))
    c.execute(text("SET ROLE aia_api"))
    api_why = dud.dry_run_refusal(c)
    c.execute(text("RESET ROLE"))
    c.rollback()
check(owner_why is not None, f"dry-run：属主/超级用户 DSN → 拒绝（{owner_why}）")
check(maint_why is None, "dry-run：aia_maint → 允许")
check(api_why is not None, f"dry-run：aia_api 服务账号 → 拒绝（{api_why}）")
ro = "tb49_ro_" + secrets.token_hex(3)
rw = "tb49_rw_" + secrets.token_hex(3)
with engine().begin() as c:
    c.execute(text(f"CREATE ROLE {ro} NOLOGIN"))
    c.execute(text(f"GRANT USAGE ON SCHEMA app TO {ro}"))
    c.execute(text(f"GRANT SELECT ON app.users TO {ro}"))
    c.execute(text(f"CREATE ROLE {rw} NOLOGIN"))
    c.execute(text(f"GRANT USAGE ON SCHEMA app TO {rw}"))
    c.execute(text(f"GRANT SELECT, DELETE ON app.users TO {rw}"))
try:
    with engine().connect() as c:
        c.execute(text(f"SET ROLE {ro}"))
        ro_why = dud.dry_run_refusal(c)
        c.execute(text("RESET ROLE"))
        c.execute(text(f"SET ROLE {rw}"))
        rw_why = dud.dry_run_refusal(c)
        c.rollback()
finally:
    with engine().begin() as c:
        for role in (ro, rw):
            c.execute(text(f"REVOKE ALL ON app.users FROM {role}"))
            c.execute(text(f"REVOKE ALL ON SCHEMA app FROM {role}"))
            c.execute(text(f"DROP ROLE {role}"))
check(ro_why is None, "dry-run：只读角色 → 允许")
check(rw_why is not None, f"dry-run：有 DELETE 权限的角色 → 拒绝（{rw_why}）")
os.environ["DATABASE_URL"] = DB
_err = io.StringIO()
with contextlib.redirect_stderr(_err), contextlib.redirect_stdout(io.StringIO()):
    rc = dud.main(["--user-id", str(uid_new)])
check(rc == 1 and "拒绝" in _err.getvalue(), "CLI main：属主 DSN dry-run → 退出 1")

for u in (uid_old, uid_new):
    with contextlib.suppress(Exception):
        q("delete from app.users where id = :i", i=u)
rds.flushdb()
finish()
