# ruff: noqa: E501  自检脚本：检查描述保持单行，便于对照输出
"""T-B49b 自检（隔离 PG/Redis，见 ``_common``；不调用任何行情接口）：

- B1 迁移 0018：CHECK 含 on_demand；有 on_demand 行时降级拒绝；
- B2 删除用户数据 CLI：触发器白名单（基线无白名单外触发器；本人数据表上新增触发器 → dry-run 列出、
  --execute 在确认前退出 1；范围外表上的触发器不计）；
- B3 冷却到期半开区间（paused_until == now → 已到期；早 1µs → 保留；空值按 deleted_at+24h；
  ``now`` 缺省用数据库 now()）；
- A3 limit 上限 200（OpenAPI maximum、limit=201 → 400）；
- B5 R11 #9/#10 收紧（数量必须是字符串、证券代码模式、编码别名拒绝）；
- B6 计划草案数量按单笔上限截断；ETF 闸门 data_source 空串 → T+1；
- 架构师裁定（T-live-83a031c §8）：批次 discarded / failed → 同一事务删除预览行、批次头保留；
  每小时清理任务（beat 排程、worker 执行、幂等、间隔取配置）。
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import secrets
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis as redislib
from _common import DB, RURL, check, engine, err_code, finish, q
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import AuthAbusePolicy, Settings
from app.main import create_app

rds = redislib.Redis.from_url(RURL)
rds.flushdb()


def mk(**kw: Any) -> Settings:  # noqa: ANN401
    base: dict[str, Any] = {
        "database_url": DB,
        "redis_url": RURL,
        "app_env": "local",
        "app_master_key": secrets.token_urlsafe(32),
        "registration_mode": "open",
        "session_cookie_secure": False,
        "auth_abuse": AuthAbusePolicy(
            register_ip_per_hour=500, register_ip_per_day=500, login_ip_per_minute=500
        ),
    }
    base.update(kw)
    return Settings(**base)


def refuses(**kw: Any) -> bool:  # noqa: ANN401
    try:
        mk(**kw)
    except ValueError:
        return True
    return False


st = mk()
app = create_app(st)


def new_user() -> uuid.UUID:
    u = uuid.uuid4()
    q(
        "insert into app.users(id, username, password_hash, role, status) values (:i, :n, 'x', 'user', 'approved')",
        i=u,
        n="tb49b_" + u.hex[:12],
    )
    return u


# ---------------------------------------------------------------- B1 迁移 0018
cdef = q(
    "select pg_get_constraintdef(oid) from pg_constraint where conname = 'ck_symbol_horizon_assessments_trigger'"
).scalar_one()
check("on_demand" in cdef, "B1：ck_symbol_horizon_assessments_trigger 含 on_demand")
_ver = (
    q("select version_num from app.alembic_version").scalar_one()
    if q("select to_regclass('app.alembic_version')").scalar_one()
    else q("select version_num from public.alembic_version").scalar_one()
)
check(int(_ver) >= 18, f"B1：隔离库 alembic 版本 ≥ 0018（得 {_ver}；T-B51 起 head 为 0019）")
from app.schemas.enums import HorizonAssessmentTrigger  # noqa: E402

check(HorizonAssessmentTrigger("on_demand").value == "on_demand", "B1：枚举含 on_demand")
_spec = importlib.util.spec_from_file_location(
    "m0018",
    Path(__file__).resolve().parents[1]
    / "migrations/versions/0018_t_b49_horizon_trigger_on_demand.py",
)
assert_ok = _spec is not None and _spec.loader is not None
check(assert_ok, "B1：0018 迁移文件存在")
if _spec is not None and _spec.loader is not None:
    m18 = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(m18)

    class _Res:
        def __init__(self, n: int) -> None:
            self.n = n

        def scalar_one(self) -> int:
            return self.n

    class _Bind:
        def __init__(self, n: int) -> None:
            self.n = n

        def execute(self, _sql: object) -> _Res:
            return _Res(self.n)

    replaced: list[str] = []
    m18._replace = replaced.append  # type: ignore[attr-defined]
    m18.op = SimpleNamespace(get_bind=lambda: _Bind(3))  # type: ignore[attr-defined]
    try:
        m18.downgrade()
        refused = False
    except RuntimeError as exc:
        refused = "3" in str(exc)
    check(refused and not replaced, "B1：库中有 on_demand 行 → 降级拒绝且不改约束")
    m18.op = SimpleNamespace(get_bind=lambda: _Bind(0))  # type: ignore[attr-defined]
    m18.downgrade()
    check(replaced == [m18.OLD], "B1：无 on_demand 行 → 降级恢复旧 CHECK")

# ---------------------------------------------------------------- B3 冷却半开区间
from app.licences import service as lsvc  # noqa: E402

T = dt.datetime(2026, 11, 2, 9, 30, tzinfo=dt.UTC)
us = [new_user() for _ in range(5)]
rows = [
    (us[0], T, T),  # paused_until == now → 已到期
    (us[1], T + dt.timedelta(microseconds=1), T - dt.timedelta(days=2)),  # 晚 1µs → 保留
    (us[2], None, T - dt.timedelta(hours=24)),  # 空 + deleted_at+24h == now → 已到期
    (us[3], None, T - dt.timedelta(hours=24) + dt.timedelta(microseconds=1)),  # 保留
]
for u, p, d in rows:
    q(
        "insert into app.user_data_licence_cooldowns(user_id, fingerprint, status, paused_until, deleted_at) values (:u, :f, 'quota_exceeded', :p, :d)",
        u=u,
        f=os.urandom(32),
        p=p,
        d=d,
    )
with engine().begin() as c:
    n = lsvc.purge_expired_cooldowns(c, T)
left = {
    r[0]
    for r in q(
        "select user_id from app.user_data_licence_cooldowns where user_id = any(:u)", u=us[:4]
    )
}
check(n >= 2 and us[0] not in left, "B3：paused_until == now → 删除（半开区间）")
check(us[1] in left, "B3：paused_until = now + 1µs → 保留")
check(us[2] not in left, "B3：paused_until 空、deleted_at+24h == now → 删除")
check(us[3] in left, "B3：paused_until 空、deleted_at+24h 晚 1µs → 保留")
with engine().begin() as c:
    c.execute(
        text(
            "insert into app.user_data_licence_cooldowns(user_id, fingerprint, status, paused_until, deleted_at) values (:u, :f, 'ip_limited', now(), now())"
        ),
        {"u": us[4], "f": os.urandom(32)},
    )
    lsvc.purge_expired_cooldowns(c)  # now 缺省 → 数据库 now()，同一事务内 now() 相等
    gone = (
        c.execute(
            text("select count(*) from app.user_data_licence_cooldowns where user_id = :u"),
            {"u": us[4]},
        ).scalar_one()
        == 0
    )
    db_now = lsvc.db_now(c)
check(gone, "B3：now 缺省用数据库 now()：paused_until = now() → 删除")
check(db_now.tzinfo is not None, "B3：db_now 带时区")
check(
    not lsvc.keeps_state(SimpleNamespace(paused_until=T, status="active"), T),
    "B3：keeps_state：now == paused_until → 已到期（不保留）",
)
check(
    lsvc.keeps_state(
        SimpleNamespace(paused_until=T, status="active"), T - dt.timedelta(microseconds=1)
    ),
    "B3：keeps_state：now 早 1µs → 保留",
)
check(
    lsvc.keeps_state(SimpleNamespace(paused_until=T, status="ip_limited"), T),
    "B3：keeps_state：冷却状态即使 paused_until 已到期 → 按契约保留（裁定 #3）",
)
check(
    lsvc.keeps_state(SimpleNamespace(paused_until=None, status="ip_limited"), T),
    "B3：keeps_state：冷却状态且 paused_until 空 → 保留",
)
q("delete from app.user_data_licence_cooldowns where user_id = any(:u)", u=us)

# ---------------------------------------------------------------- B2 触发器白名单
from app.cli import delete_user_data as dud  # noqa: E402

victim = new_user()
with engine().connect() as c:
    base_plan = dud.build_plan(c, victim)
    c.rollback()
check(base_plan.unknown_triggers == [], f"B2：基线无白名单外触发器（{base_plan.unknown_triggers}）")
tg = "tb49b_tg_" + secrets.token_hex(3)
fn = "app.tb49b_fn_" + secrets.token_hex(3)
scratch = "app.tb49b_scratch_" + secrets.token_hex(3)
with engine().begin() as c:
    c.execute(
        text(
            f"CREATE FUNCTION {fn}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN OLD; END $$"
        )
    )
    c.execute(
        text(
            f"CREATE TRIGGER {tg} BEFORE DELETE ON app.watchlist_items FOR EACH ROW EXECUTE FUNCTION {fn}()"
        )
    )
    c.execute(text(f"CREATE TABLE {scratch}(id int)"))
    c.execute(
        text(
            f"CREATE TRIGGER {tg}_x BEFORE DELETE ON {scratch} FOR EACH ROW EXECUTE FUNCTION {fn}()"
        )
    )
try:
    with engine().connect() as c:
        plan = dud.build_plan(c, victim)
        c.rollback()
    check(
        any(tg in t and "watchlist_items" in t for t in plan.unknown_triggers),
        f"B2：本人数据表上新增触发器 → 计划列出（{plan.unknown_triggers}）",
    )
    check(
        not any(f"{tg}_x" in t for t in plan.unknown_triggers),
        "B2：范围外表上的触发器不计",
    )
    printed: list[str] = []
    dud.print_plan(plan, printed.append)
    check(any(tg in s for s in printed), "B2：dry-run 输出列出白名单外触发器")
    asked: list[str] = []
    saved = (dud._urls, dud.dry_run_refusal)
    dud._urls = lambda: (DB, None, True)  # type: ignore[assignment]
    dud.dry_run_refusal = lambda _c: None  # type: ignore[assignment]
    try:
        rc = dud.main(
            ["--user-id", str(victim), "--execute"],
            confirm=lambda s: asked.append(s) or "",
        )
    finally:
        dud._urls, dud.dry_run_refusal = saved  # type: ignore[assignment]
    still = q("select count(*) from app.users where id = :u", u=victim).scalar_one() == 1
    check(rc == 1 and not asked and still, "B2：--execute 在确认前退出 1，用户仍在")
finally:
    with engine().begin() as c:
        c.execute(text(f"DROP TRIGGER IF EXISTS {tg} ON app.watchlist_items"))
        c.execute(text(f"DROP TABLE IF EXISTS {scratch}"))
        c.execute(text(f"DROP FUNCTION IF EXISTS {fn}()"))
left_tg = q("select count(*) from pg_trigger where tgname like 'tb49b_tg_%'").scalar_one()
check(left_tg == 0, "B2：植入的触发器已清理")

# ---------------------------------------------------------------- 登录（API 检查用）


def login() -> tuple[TestClient, dict[str, str]]:
    name = "tb49b_" + secrets.token_hex(4)
    pw = "Tb4x" + secrets.token_urlsafe(12) + "9a"
    r = TestClient(app).post(
        "/api/v1/auth/register", json={"username": name, "password": pw, "display_name": "T"}
    )
    if r.status_code not in (201, 202):
        sys.exit(f"注册失败：{r.status_code} {err_code(r)}")
    q("update app.users set status = 'approved' where username = :u", u=name)
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"username": name, "password": pw})
    if r.status_code != 200:
        sys.exit(f"登录失败：{r.status_code} {err_code(r)}")
    return c, {"X-CSRF-Token": r.json().get("csrf_token", "")}


cl, hd = login()
r = cl.post(
    "/api/v1/accounts",
    headers=hd | {"Idempotency-Key": str(uuid.uuid4())},
    json={"alias": "tb49b-acc", "broker_name": "tb49b-broker"},
)
check(r.status_code == 201, f"建账户 201（{r.status_code} {err_code(r)}）")
acc = r.json()["id"]
owner = q("select user_id from app.accounts where id = :a", a=acc).scalar_one()

# ---------------------------------------------------------------- A3 limit ≤ 200
spec = TestClient(app).get("/api/v1/openapi.json")
if spec.status_code != 200:
    spec = TestClient(app).get("/openapi.json")
oa = spec.json()
limits = [
    p.get("schema", {})
    for item in oa["paths"].values()
    for op in item.values()
    if isinstance(op, dict)
    for p in op.get("parameters", [])
    if p.get("name") == "limit"
]
check(
    limits and all(any(x.get("maximum") == 200 for x in [s, *s.get("anyOf", [])]) for s in limits),
    f"A3：OpenAPI {len(limits)} 个 limit 参数 maximum=200",
)
r = cl.get("/api/v1/trades", params={"limit": 201})
check(
    r.status_code == 400 and err_code(r) == "VALIDATION_ERROR",
    f"A3：limit=201 → 400（{r.status_code} {err_code(r)}）",
)
r = cl.get("/api/v1/trades", params={"limit": 200})
check(r.status_code == 200, f"A3：limit=200 → 200（{r.status_code}）")
check(refuses(page_limit_max=201), "A3：配置 page_limit_max > 200 拒绝")

# ---------------------------------------------------------------- B5 R11 #9/#10
tc = oa["components"]["schemas"].get("TradeCreate", {})
qty_s = tc.get("properties", {}).get("qty", {})
check(
    qty_s.get("type") == "string" and "pattern" in qty_s,
    "B5：OpenAPI TradeCreate.qty 为带 pattern 的字符串",
)
check(
    "pattern" in tc.get("properties", {}).get("security_code", {}),
    "B5：OpenAPI TradeCreate.security_code 带 pattern",
)
body = {
    "account_id": acc,
    "trade_date": "2026-10-30",
    "security_code": "600000.SH",
    "side": "buy",
    "qty": "100",
    "price": "10.00",
}


def post_trade(**kw: Any) -> Any:  # noqa: ANN401
    return cl.post(
        "/api/v1/trades",
        headers=hd | {"Idempotency-Key": str(uuid.uuid4())},
        json=body | kw,
    )


for label, kw in (
    ("qty 为数字", {"qty": 100}),
    ("qty = 0", {"qty": "0"}),
    ("price 为数字", {"price": 10.0}),
    ("证券代码前导空格", {"security_code": " 600000.SH"}),
    ("证券代码格式错", {"security_code": "60000X"}),
):
    r = post_trade(**kw)
    check(
        r.status_code == 400 and err_code(r) == "VALIDATION_ERROR",
        f"B5：{label} → 400（{r.status_code} {err_code(r)}）",
    )
r = cl.get("/api/v1/trades", params={"security_code": "abc"})
check(r.status_code == 400, f"B5：GET /trades security_code 不合模式 → 400（{r.status_code}）")
oin = oa["components"]["schemas"].get("OptionsIn", {}).get("properties", {})
enc_txt = str(oin.get("encoding_override", {}))
check(
    "gb18030" in enc_txt and "utf8'" not in enc_txt, "B5：OpenAPI encoding_override 为 4 个枚举值"
)

# ---------------------------------------------------------------- 架构师裁定：discarded/failed 删预览行


def mk_batch(status: str, n_rows: int = 3) -> uuid.UUID:
    b = uuid.uuid4()
    q(
        "insert into app.import_batches(id, user_id, account_id, status, kind) values (:b, :u, :a, :s, 'trades')",
        b=b,
        u=owner,
        a=acc,
        s=status,
    )
    for i in range(n_rows):
        q(
            "insert into app.import_rows(batch_id, row_no, kind, status) values (:b, :n, 'trade', 'ok')",
            b=b,
            n=i + 1,
        )
    return b


def nrows(b: uuid.UUID) -> int:
    return int(q("select count(*) from app.import_rows where batch_id = :b", b=b).scalar_one())


def has_header(b: uuid.UUID) -> bool:
    return q("select count(*) from app.import_batches where id = :b", b=b).scalar_one() == 1


r = cl.put(
    f"/api/v1/imports/{mk_batch('failed', 0)}/options",
    headers=hd | {"Idempotency-Key": str(uuid.uuid4())},
    json={"encoding_override": "utf8"},
)
check(
    r.status_code == 400,
    f"B5：encoding_override=utf8（别名）→ 400（{r.status_code} {err_code(r)}）",
)

b_disc = mk_batch("previewed")
r = cl.post(
    f"/api/v1/imports/{b_disc}/discard", headers=hd | {"Idempotency-Key": str(uuid.uuid4())}
)
check(r.status_code == 200, f"裁定：discard → 200（{r.status_code} {err_code(r)}）")
check(nrows(b_disc) == 0 and has_header(b_disc), "裁定：discard 同一事务删除预览行，批次头保留")
check(
    q("select status from app.import_batches where id = :b", b=b_disc).scalar_one() == "discarded",
    "裁定：批次状态 discarded",
)

from app.importing import pipeline  # noqa: E402

b_parse = mk_batch("parsing")
pipeline.run_parse(engine(), st, b_parse)  # 无原始文件 → failed
check(
    q("select status from app.import_batches where id = :b", b=b_parse).scalar_one() == "failed"
    and nrows(b_parse) == 0
    and has_header(b_parse),
    "裁定：解析转 failed（无原始文件）→ 预览行删除、批次头保留",
)


def boom(*_a: Any, **_k: Any) -> None:  # noqa: ANN401
    raise RuntimeError("selfcheck")


b_exc = mk_batch("parsing")
saved_rp = pipeline._run_parse
pipeline._run_parse = boom  # type: ignore[assignment]
try:
    pipeline.run_parse(engine(), st, b_exc)
finally:
    pipeline._run_parse = saved_rp  # type: ignore[assignment]
check(
    q("select status from app.import_batches where id = :b", b=b_exc).scalar_one() == "failed"
    and nrows(b_exc) == 0,
    "裁定：解析异常 → failed，同一事务删除预览行",
)
b_keep = mk_batch("parsing")
pipeline._run_parse = boom  # type: ignore[assignment]
q("update app.import_batches set status = 'previewed' where id = :b", b=b_keep)
try:
    pipeline.run_parse(engine(), st, b_keep)  # 状态已不是 parsing → 不改状态、不删行
finally:
    pipeline._run_parse = saved_rp  # type: ignore[assignment]
check(nrows(b_keep) == 3, "裁定：状态未转 failed 的批次不删行")

src = Path(pipeline.__file__).read_text(encoding="utf-8")
check(
    "stored = [] if pv.status in ROWS_DROPPED_STATUSES else pv.rows" in src,
    "裁定：预览结果为 failed → 不落预览行（_store_preview）",
)

# ---------------------------------------------------------------- 每小时清理任务
from app.workers import jobs  # noqa: E402

s_job = mk(import_rows_purge_interval_s=600)
check(
    jobs.schedule(s_job).get(jobs.PURGE_IMPORT_ROWS) == 600,
    "清理任务：beat 排程表含 imports.purge_preview_rows（T-B56），间隔取配置",
)
check(mk().import_rows_purge_interval_s == 3600, "清理任务：默认间隔 3600s（每小时）")
check(refuses(import_rows_purge_interval_s=30), "清理任务：间隔 < 60 拒绝")
os.environ["IMPORT_ROWS_PURGE_INTERVAL_S"] = "1200"
check(
    Settings().import_rows_purge_interval_s == 1200,
    "清理任务：环境变量 IMPORT_ROWS_PURGE_INTERVAL_S 生效",
)
os.environ.pop("IMPORT_ROWS_PURGE_INTERVAL_S")

old_f, old_d, live = mk_batch("failed"), mk_batch("discarded"), mk_batch("previewed")
committed = mk_batch("committed")
rds.flushdb()
queued = jobs.beat_tick(s_job, rds)
check(jobs.PURGE_IMPORT_ROWS in queued, f"清理任务：beat 首轮排程（{queued}）")
check(jobs.PURGE_IMPORT_ROWS not in jobs.beat_tick(s_job, rds), "清理任务：间隔内不重复排程")
ttl = rds.ttl(jobs.DUE_PREFIX + jobs.PURGE_IMPORT_ROWS)
check(0 < ttl <= 600, f"清理任务：到期键 TTL = 配置间隔（{ttl}s）")
done = jobs.worker_tick(s_job, rds)
check((jobs.PURGE_IMPORT_ROWS, "ok") in done, f"清理任务：worker 执行 → ok（{done}）")
check(nrows(old_f) == 0 and nrows(old_d) == 0, "清理任务：failed / discarded 残留预览行删除")
check(nrows(live) == 3 and nrows(committed) == 3, "清理任务：previewed / committed 批次的行不动")
check(all(has_header(b) for b in (old_f, old_d)), "清理任务：批次头保留")
with engine().begin() as c:
    again = pipeline.purge_uncommitted_import_rows(c)
check(again == 0, "清理任务：幂等，第二次删除 0 行")

# ---------------------------------------------------------------- B6 截断 + ETF 闸门
from app.market_rules.lots import clamp_draft_qty, fund_t_plus, lot_spec  # noqa: E402

seg = st.business.market_rules.segment_for(dt.date(2026, 11, 2))
for board, qty in (("main", 2_000_050), ("star", 300_000), ("chinext", 900_000)):
    spec_l = lot_spec(seg, board=board, security_type="stock")
    got, notice = clamp_draft_qty(seg, board=board, security_type="stock", qty=qty)
    on_grid = (got - spec_l.min_buy) % spec_l.step == 0
    check(
        got <= spec_l.max_qty
        and on_grid
        and got > spec_l.max_qty - spec_l.step
        and notice
        == {
            "code": "qty_capped_order_limit",
            "original_qty": str(qty),
            "max_qty": str(spec_l.max_qty),
        },
        f"B6：{board} {qty} → {got}（上限 {spec_l.max_qty}，提示 qty_capped_order_limit）",
    )
got, notice = clamp_draft_qty(seg, board="main", security_type="stock", qty=1000)
check(got == 1000 and notice is None, "B6：未超上限 → 原值、无提示")
if seg is not None:
    for ds in ("", "   "):
        blank = seg.model_copy(
            update={"t0_round_trip": seg.t0_round_trip.model_copy(update={"data_source": ds})}
        )
        check(
            fund_t_plus(blank, security_type="etf", etf_category="gold") == 1,
            f"ETF 闸门：data_source={ds!r} → T+1",
        )

finish()
