# ruff: noqa: E501  自检脚本：检查描述保持单行，便于对照输出
"""T-B49 补充（T-B49c）自检（隔离 PG/Redis，见 ``_common``；不调用任何行情接口）：

- m1 今日收盘价不算过期：``latest_close_at`` 按交易日历 / 周一至五回退取“最近已收盘交易日 15:00”；
  持仓现价时点不早于它 → FRESH，更早 → STALE；
- m3 迁移 0017 降级预检查：有 horizon 快照 → 中文报错、不改约束；无 → 正常降级；
- #30 / 契约 §1.3：非法 JSON 不得先于认证 / CSRF（未登录 → 401；已登录缺 CSRF → 403；
  /admin 非管理员 → 404；认证 + CSRF 都通过 → 400）；不需登录的端点照旧 400。
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import secrets
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis as redislib
from _common import DB, RURL, check, engine, err_code, finish, q
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v1.portfolio import build_portfolio, latest_close_at
from app.config import AuthAbusePolicy, Settings
from app.main import create_app

BJ = ZoneInfo("Asia/Shanghai")
rds = redislib.Redis.from_url(RURL)
rds.flushdb()

# ---------------------------------------------------------------- m1 latest_close_at
with engine().connect() as c:
    tx = c.begin()
    c.execute(text("delete from market.trading_calendar"))
    mon = dt.datetime(2026, 11, 2, 16, 0, tzinfo=BJ)  # 周一收盘后
    check(
        latest_close_at(c, mon) == dt.datetime(2026, 11, 2, 15, 0, tzinfo=BJ),
        "m1：无日历、周一 16:00 → 当天 15:00",
    )
    check(
        latest_close_at(c, mon.replace(hour=15)) == dt.datetime(2026, 11, 2, 15, 0, tzinfo=BJ),
        "m1：周一恰 15:00 → 当天（收盘即算）",
    )
    check(
        latest_close_at(c, mon.replace(hour=10)) == dt.datetime(2026, 10, 30, 15, 0, tzinfo=BJ),
        "m1：无日历、周一 10:00 → 上周五 15:00",
    )
    check(
        latest_close_at(c, dt.datetime(2026, 11, 1, 12, 0, tzinfo=BJ))
        == dt.datetime(2026, 10, 30, 15, 0, tzinfo=BJ),
        "m1：周日 → 周五",
    )
    check(
        latest_close_at(c, dt.datetime(2026, 11, 2, 1, 0, tzinfo=dt.UTC))
        == dt.datetime(2026, 10, 30, 15, 0, tzinfo=BJ),
        "m1：UTC 时点先换算北京时间（UTC 01:00 = 北京 09:00）",
    )
    # 国庆：9/30 开市，10/1–10/8 休市，10/9 开市
    for i in range(0, 12):
        d = dt.date(2026, 9, 28) + dt.timedelta(days=i)
        c.execute(
            text("insert into market.trading_calendar(date, is_open) values (:d, :o)"),
            {
                "d": d,
                "o": d.weekday() < 5 and not (dt.date(2026, 10, 1) <= d <= dt.date(2026, 10, 8)),
            },
        )
    check(
        latest_close_at(c, dt.datetime(2026, 10, 5, 12, 0, tzinfo=BJ))
        == dt.datetime(2026, 9, 30, 15, 0, tzinfo=BJ),
        "m1：日历覆盖的节假日 → 节前最后交易日",
    )
    check(
        latest_close_at(c, dt.datetime(2026, 10, 9, 14, 59, tzinfo=BJ))
        == dt.datetime(2026, 9, 30, 15, 0, tzinfo=BJ),
        "m1：节后首日收盘前 → 仍是节前最后交易日",
    )
    check(
        latest_close_at(c, dt.datetime(2026, 10, 9, 15, 1, tzinfo=BJ))
        == dt.datetime(2026, 10, 9, 15, 0, tzinfo=BJ),
        "m1：节后首日收盘后 → 当天",
    )
    check(
        latest_close_at(c, dt.datetime(2026, 11, 3, 16, 0, tzinfo=BJ))
        == dt.datetime(2026, 11, 3, 15, 0, tzinfo=BJ),
        "m1：超出日历范围 → 退回周一至五",
    )
    tx.rollback()

# ---------------------------------------------------------------- m1 持仓 data_status
CODE = "600951.SH"
q(
    "insert into market.securities(code, type, name, exchange, board, listing_status) "
    "values (:c, 'stock', '自检鲜', 'SH', 'main', 'listed') on conflict (code) do nothing",
    c=CODE,
)
uid = uuid.uuid4()
q(
    "insert into app.users(id, username, password_hash, role, status) values (:i, :n, 'x', 'user', 'approved')",
    i=uid,
    n="tb49c_" + uid.hex[:12],
)
aid = uuid.uuid4()
q("insert into app.accounts(id, user_id, name) values (:a, :u, 'tb49c')", a=aid, u=uid)
q(
    "insert into app.trades(account_id, user_id, security_code, side, quantity, price, trade_date, source, cash_balance_after) "
    "values (:a, :u, :c, 'buy', 100, 10, date '2026-09-01', 'manual', 1000)",
    a=aid,
    u=uid,
    c=CODE,
)
q(
    "insert into app.holdings(account_id, security_code, quantity, avg_cost) values (:a, :c, 100, 10)",
    a=aid,
    c=CODE,
)


def status_with_bar(day: dt.date) -> tuple[str, str]:
    q("delete from market.daily_bars where code = :c", c=CODE)
    q(
        "insert into market.daily_bars(code, trade_date, adj_type, close) values (:c, :d, 'none', 11)",
        c=CODE,
        d=day,
    )
    with engine().connect() as c:
        out = build_portfolio(c, [aid])
    check(
        len(out["positions"]) == 1 and out["positions"][0]["security_code"] == CODE,
        f"m1：持仓含 {CODE}（{day}）",
    )
    return out["data_status"], [g["key"] for g in out["gaps"]].__repr__()


with engine().connect() as c:
    last = latest_close_at(c, dt.datetime.now(BJ)).date()
st_now, gaps_now = status_with_bar(last)
check(
    st_now == "fresh",
    f"m1：现价 = 最近已收盘交易日（{last}）的收盘价 → fresh（得 {st_now}，gaps={gaps_now}）",
)
st_old, _ = status_with_bar(last - dt.timedelta(days=7))
check(st_old == "stale", f"m1：现价早于最近已收盘交易日 → stale（得 {st_old}）")
q("delete from market.daily_bars where code = :c", c=CODE)

# ---------------------------------------------------------------- m3 0017 降级预检查
_spec = importlib.util.spec_from_file_location(
    "m0017",
    Path(__file__).resolve().parents[1] / "migrations/versions/0017_t_b49_snapshot_purpose.py",
)
assert_ok = _spec is not None and _spec.loader is not None
check(assert_ok, "m3：0017 迁移文件存在")
if _spec is not None and _spec.loader is not None:
    m17 = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(m17)
    calls: list[str] = []

    class _Res:
        def __init__(self, n: int) -> None:
            self.n = n

        def scalar_one(self) -> int:
            return self.n

    def _op(n: int) -> SimpleNamespace:
        return SimpleNamespace(
            get_bind=lambda: SimpleNamespace(execute=lambda _s: _Res(n)),
            f=lambda s: s,
            drop_constraint=lambda name, *a, **k: calls.append("drop:" + name),
            create_check_constraint=lambda name, *a, **k: calls.append("create:" + name),
        )

    m17.op = _op(2)  # type: ignore[attr-defined]
    try:
        m17.downgrade()
        msg = ""
    except RuntimeError as exc:
        msg = str(exc)
    check(
        "0017 降级拒绝" in msg and "2 行" in msg and "horizon" in msg and not calls,
        "m3：有 horizon 快照 → 中文报错（含行数）且不改约束",
    )
    m17.op = _op(0)  # type: ignore[attr-defined]
    m17.downgrade()
    check(
        calls
        == [
            "drop:ck_data_snapshots_user_scoped",
            "drop:ck_data_snapshots_purpose",
            "create:ck_data_snapshots_purpose",
        ],
        "m3：无 horizon 快照 → 正常降级",
    )
    with engine().connect() as c:
        n = c.execute(text(m17.HORIZON_ROWS)).scalar_one()
    check(isinstance(n, int), "m3：预检查 SQL 在真实库上可执行")

# ---------------------------------------------------------------- #30 非法 JSON 与认证顺序
st = Settings(
    database_url=DB,
    redis_url=RURL,
    app_env="local",
    app_master_key=secrets.token_urlsafe(32),
    registration_mode="open",
    session_cookie_secure=False,
    auth_abuse=AuthAbusePolicy(
        register_ip_per_hour=500, register_ip_per_day=500, login_ip_per_minute=500
    ),
)
app = create_app(st)
BAD = {"content": b"{bad", "headers": {"Content-Type": "application/json"}}
anon = TestClient(app)
r = anon.post("/api/v1/accounts", **BAD)
check(
    r.status_code == 401 and err_code(r) == "AUTH_REQUIRED",
    f"#30：未登录 + 非法 JSON → 401（得 {r.status_code} {err_code(r)}）",
)
r = anon.patch("/api/v1/me/data-licence", **BAD)
check(r.status_code == 401, f"#30：未登录 PATCH 非法 JSON → 401（得 {r.status_code}）")
r = anon.post(f"/api/v1/admin/users/{uuid.uuid4()}/approve", **BAD)
check(
    r.status_code == 404 and err_code(r) == "NOT_FOUND",
    f"#30：/admin 未登录 + 非法 JSON → 404（得 {r.status_code}）",
)
r = anon.post("/api/v1/auth/login", **BAD)
check(
    r.status_code == 400 and err_code(r) == "VALIDATION_ERROR",
    f"#30：无需登录的端点非法 JSON 照旧 400（得 {r.status_code}）",
)


# #30 ④ 白名单端点的 Origin 校验（登录 CSRF；架构师评审跟进）：先于请求体解析
def _post(c: TestClient, path: str, origin: str | None, body: bytes = b"{bad") -> Any:  # noqa: ANN401
    h = {"Content-Type": "application/json"}
    if origin is not None:
        h["Origin"] = origin
    return c.post(path, content=body, headers=h)


r = _post(anon, "/api/v1/auth/login", "https://evil.example")
check(
    r.status_code == 403 and err_code(r) == "CSRF_FAILED",
    f"#30④：login 带外站 Origin → 403 CSRF_FAILED，先于非法 JSON（得 {r.status_code} {err_code(r)}）",
)
r = _post(anon, "/api/v1/auth/login", "null")
check(r.status_code == 403 and err_code(r) == "CSRF_FAILED", "#30④：Origin: null → 403")
r = _post(anon, "/api/v1/auth/login", "http://testserver")
check(
    r.status_code == 400, f"#30④：同源 Origin（未配置 SITE_ORIGINS）照常处理（得 {r.status_code}）"
)
r = _post(anon, "/api/v1/auth/login", "http://testserver.evil.example")
check(r.status_code == 403, "#30④：主机名前缀相同的外站 → 403")
r = _post(
    anon, "/api/v1/auth/login", "https://evil.example", b'{"username":"nouser","password":"x"}'
)
check(r.status_code == 403 and err_code(r) == "CSRF_FAILED", "#30④：合法请求体 + 外站 Origin → 403")
r = _post(anon, "/api/v1/auth/register", "https://evil.example")
check(
    r.status_code == 403 and err_code(r) == "CSRF_FAILED",
    f"#30④：open 时 register 带外站 Origin → 403（得 {r.status_code}）",
)
closed_app = create_app(st.model_copy(update={"registration_mode": "closed"}))
r = _post(TestClient(closed_app), "/api/v1/auth/register", "https://evil.example")
check(
    r.status_code == 503 and err_code(r) == "REGISTRATION_CLOSED",
    f"#30④⑤：closed 时带外站 Origin 的注册 → 503 REGISTRATION_CLOSED（得 {r.status_code}）",
)
site_app = create_app(st.model_copy(update={"site_origins": ("https://aia.example",)}))
sc = TestClient(site_app)
r = _post(sc, "/api/v1/auth/login", "https://AIA.example/")
check(r.status_code == 400, f"#30④：配置的 SITE_ORIGINS 照常处理（得 {r.status_code}）")
r = _post(sc, "/api/v1/auth/login", "http://testserver")
check(r.status_code == 403, "#30④：配置 SITE_ORIGINS 后不再按 Host 同源放行")
try:
    Settings(app_env="local", site_origins=("https://aia.example/app",))
    bad_ok = False
except ValueError:
    bad_ok = True
check(bad_ok, "#30④：SITE_ORIGINS 带路径 → 启动失败")

name = "tb49c_" + secrets.token_hex(4)
pw = "Tb49" + secrets.token_urlsafe(12) + "5a"
anon.post("/api/v1/auth/register", json={"username": name, "password": pw, "display_name": "T"})
q("update app.users set status = 'approved' where username = :u", u=name)
cl = TestClient(app)
r = cl.post("/api/v1/auth/login", json={"username": name, "password": pw})
hdr = {"X-CSRF-Token": r.json().get("csrf_token", "")}
r = cl.post("/api/v1/accounts", **BAD)
check(
    r.status_code == 403 and err_code(r) == "CSRF_FAILED",
    f"#30：已登录、缺 CSRF、非法 JSON → 403 CSRF_FAILED（得 {r.status_code} {err_code(r)}）",
)
r = cl.post(
    "/api/v1/accounts", content=b"{bad", headers={"Content-Type": "application/json", **hdr}
)
check(
    r.status_code == 400 and err_code(r) == "VALIDATION_ERROR",
    f"#30：认证 + CSRF 通过后非法 JSON → 400（得 {r.status_code}）",
)
r = cl.post(
    f"/api/v1/admin/users/{uuid.uuid4()}/approve",
    content=b"{bad",
    headers={"Content-Type": "application/json", **hdr},
)
check(r.status_code == 404, f"#30：普通用户 /admin 非法 JSON → 404（得 {r.status_code}）")
r = cl.post("/api/v1/accounts", json={"name": 1}, headers=hdr)
check(r.status_code == 400, "#30：合法 JSON 的字段校验错误照旧 400")
r = anon.post("/api/v1/accounts", json={"name": 1})
check(r.status_code == 401, "#30：未登录 + 字段校验错误 → 401（依赖先于字段校验，原本即如此）")

q("update app.users set status = 'rejected' where username like 'tb49c_%'")
finish()
