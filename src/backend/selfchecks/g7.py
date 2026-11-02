# ruff: noqa: E501  自检脚本：检查描述保持单行，便于对照输出
"""G-7 自检（T-live-83a031c §8.4；隔离 PG/Redis，见 ``_common``）：

``GET /imports?account_id=`` 与 ``GET /trades?account_id=``：账户不是本人（他人账户 / 不存在）→
``404 NOT_FOUND``，错误体与 ``GET /portfolio?account_id=`` 的 404 同形；本人账户 / 不带 account_id → 200。
"""

from __future__ import annotations

import secrets
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis as redislib
from _common import DB, RURL, check, err_code, finish, q
from fastapi.testclient import TestClient

from app.config import AuthAbusePolicy, Settings
from app.main import create_app

redislib.Redis.from_url(RURL).flushdb()
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
)  # type: ignore[call-arg]
app = create_app(st)


def login() -> tuple[TestClient, dict[str, str]]:
    name = "g7_" + secrets.token_hex(4)
    pw = "G7x" + secrets.token_urlsafe(12) + "5a"
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


ca, ha = login()
cb, _hb = login()
r = ca.post(
    "/api/v1/accounts",
    headers=ha | {"Idempotency-Key": str(uuid.uuid4())},
    json={"alias": "g7-acc", "broker_name": "g7-broker"},
)
check(r.status_code == 201, f"A 建账户 201（{r.status_code} {err_code(r)}）")
acc_a = r.json()["id"]
ghost = str(uuid.uuid4())

ref = cb.get("/api/v1/portfolio", params={"account_id": acc_a})
check(
    ref.status_code == 404 and err_code(ref) == "NOT_FOUND",
    "参照：B 查 /portfolio?account_id=A → 404 NOT_FOUND",
)
ref_keys = set(ref.json()["error"]) if ref.status_code == 404 else set()

for path in ("/api/v1/imports", "/api/v1/trades"):
    for label, aid in (("A 的账户", acc_a), ("不存在的账户", ghost)):
        r = cb.get(path, params={"account_id": aid})
        same = r.status_code == 404 and set(r.json().get("error", {})) == ref_keys
        check(
            r.status_code == 404 and err_code(r) == "NOT_FOUND",
            f"B GET {path}?account_id={label} → 404 NOT_FOUND（{r.status_code}）",
        )
        check(same, f"B GET {path}?account_id={label}：错误体字段与 /portfolio 的 404 相同")
        check("items" not in r.text, f"B GET {path}?account_id={label}：不返回列表")
    r = ca.get(path, params={"account_id": acc_a})
    check(
        r.status_code == 200 and r.json()["items"] == [],
        f"A GET {path}?account_id=本人账户 → 200（{r.status_code}）",
    )
    r = cb.get(path)
    check(r.status_code == 200, f"B GET {path}（不带 account_id）→ 200")
    r = cb.get(path, params={"account_id": "not-a-uuid"})
    check(
        r.status_code == 400 and err_code(r) == "VALIDATION_ERROR",
        f"B GET {path}?account_id=非 uuid → 400 VALIDATION_ERROR",
    )
    r = TestClient(app).get(path, params={"account_id": acc_a})
    check(r.status_code == 401, f"未登录 GET {path}?account_id=A → 401（不泄露账户存在性）")

finish()
