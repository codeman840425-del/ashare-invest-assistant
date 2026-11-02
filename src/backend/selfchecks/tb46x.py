"""T-B46-x / 契约 #35 / T-B56 自检（隔离 PG/Redis，不访问网络；夹具为仓库内虚构样本）。

- #35：放弃批次 → 同一事务删预览行、批次头保留、**原始文件与 import_files 行保留**；
  discarded / failed 的 /rows 为空、errors.csv 只有表头、resolve → 409。
- T-B56：beat 任务名 ``imports.purge_preview_rows``；原始文件按 retained_until
  到期清理（默认每日）。
- m2 reason ≤200；m5 日志脱敏；m7 根目录解析共用；m8 文件头 kek_id；m9 审计不存理由原文；
  M3 两步导入 + 作废 + 他人资源 404。
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import secrets
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis as redislib
from _common import DB, RURL, check, engine, err_code, finish, q
from fastapi.testclient import TestClient

from app.config import AuthAbusePolicy, Settings
from app.importing import pipeline, storage
from app.importing.preview import PreviewContext, PreviewOptions, infer_market, preview_bytes
from app.main import create_app
from app.workers import jobs

rds = redislib.Redis.from_url(RURL)
rds.flushdb()
FX = Path(__file__).resolve().parents[3] / "tests/fixtures/broker_statements/fmt_a"
STORE = Path(tempfile.mkdtemp(prefix="tb46x_store_"))


def mk(**kw: Any) -> Settings:  # noqa: ANN401
    base: dict[str, Any] = {
        "database_url": DB,
        "redis_url": RURL,
        "app_env": "local",
        "app_master_key": secrets.token_urlsafe(32),
        "registration_mode": "open",
        "session_cookie_secure": False,
        "import_storage_path": STORE,
        "auth_abuse": AuthAbusePolicy(
            register_ip_per_hour=500, register_ip_per_day=500, login_ip_per_minute=500
        ),
    }
    base.update(kw)
    return Settings(**base)


st = mk()
app = create_app(st)

# ---- 主数据：trades_sample 的全部代码
names: dict[str, str] = {}
pv0 = preview_bytes(
    (FX / "trades_sample.txt").read_bytes(),
    "trades",
    PreviewOptions(),
    PreviewContext(
        account_id="a",
        today=dt.date.today(),
        uploaded_at=dt.datetime.now(dt.UTC),
        holder_hmac=lambda x: x,
    ),
)
for row in pv0.rows:
    n = row.normalized or {}
    if n.get("security_code") and n.get("name"):
        names.setdefault(n["security_code"], n["name"])
for c6, nm in names.items():
    full = f"{c6}.{infer_market(c6)}"
    board = "star" if c6.startswith("688") else "chinext" if c6.startswith("30") else "main"
    q(
        "insert into market.securities(code,type,name,exchange,board,listing_status) "
        "values (:c,'stock',:n,:e,:b,'listed') on conflict (code) do nothing",
        c=full,
        n=nm,
        e=full[-2:],
        b=board,
    )


def user() -> tuple[TestClient, dict[str, str]]:
    name = "tb46x_" + secrets.token_hex(4)
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


def idem(h: dict[str, str]) -> dict[str, str]:
    return h | {"Idempotency-Key": str(uuid.uuid4())}


cu, hu = user()
co, ho = user()


def acct(c: TestClient, h: dict[str, str]) -> str:
    r = c.post(
        "/api/v1/accounts",
        headers=idem(h),
        json={"alias": "A" + secrets.token_hex(3), "broker_name": "某券商"},
    )
    if r.status_code != 201:
        sys.exit(f"建账户失败：{r.status_code} {err_code(r)}")
    return str(r.json()["id"])


def upload(acc: str, name: str, data: bytes | None = None) -> Any:  # noqa: ANN401
    return cu.post(
        "/api/v1/imports",
        data={"account_id": acc, "kind": "trades"},
        files={
            "file": (name, data if data is not None else (FX / name).read_bytes(), "text/plain")
        },
        headers=hu,
    )


def nrows(b: str) -> int:
    return int(q("select count(*) from app.import_rows where batch_id = :b", b=b).scalar_one())


def file_row(b: str) -> Any:  # noqa: ANN401
    return q(
        "select storage_path, deleted_at, retained_until from app.import_files where batch_id = :b",
        b=b,
    ).one()


acc = acct(cu, hu)

# ---------------------------------------------------------------- #35 放弃
r = upload(acc, "trades_bad_formats.txt")
check(r.status_code == 201, f"#35：上传 201（{r.status_code} {err_code(r)}）")
bd = r.json()["batch_id"]
before = nrows(bd)
fr0 = file_row(bd)
raw_path = STORE / fr0.storage_path
check(before > 0 and raw_path.is_file(), f"#35：预览行 {before} 行，原始文件已落盘")
# 先取一个可处理的提示（放弃后 resolve 应为 409）
items = cu.get(f"/api/v1/imports/{bd}/rows", params={"limit": 200}).json()["items"]
fid = next((f["id"] for it in items for f in it["findings"]), "r1-x")
csv0 = cu.get(f"/api/v1/imports/{bd}/errors.csv").text
check(csv0.count("\r\n") > 1, "#35：previewed 批次 errors.csv 有数据行")
r = cu.post(f"/api/v1/imports/{bd}/discard", headers=idem(hu))
check(
    r.status_code == 200 and r.json()["status"] == "discarded",
    f"#35：discard → 200（{r.status_code}）",
)
fr1 = file_row(bd)
check(nrows(bd) == 0, "#35：同一事务删除预览行")
check(
    fr1.deleted_at is None and fr1.storage_path == fr0.storage_path and raw_path.is_file(),
    "#35：放弃不提前删除原始文件（import_files.deleted_at 空、文件仍在）",
)
check(fr1.retained_until is not None, "#35：原始文件 retained_until 已设置（走留存清理）")
r = cu.get(f"/api/v1/imports/{bd}/rows")
check(
    r.status_code == 200 and r.json()["items"] == [] and r.json().get("next_cursor") is None,
    "#35：discarded 批次 /rows → 200 items [] next_cursor null",
)
r = cu.get(f"/api/v1/imports/{bd}/errors.csv")
body = r.content.decode("utf-8-sig")
check(
    r.status_code == 200 and body == "row_no,code,severity,field,message,raw_masked\r\n",
    "#35：discarded 批次 errors.csv 只有表头",
)
r = cu.post(f"/api/v1/imports/{bd}/findings/{fid}/resolve", headers=idem(hu), json={"choice": "x"})
check(
    r.status_code == 409 and err_code(r) == "INVALID_STATE_TRANSITION",
    f"#35：discarded 批次 resolve → 409 INVALID_STATE_TRANSITION（{r.status_code} {err_code(r)}）",
)
r = cu.get(f"/api/v1/imports/{bd}")
check(r.status_code == 200 and r.json()["status"] == "discarded", "#35：批次头保留可查")

# failed 批次：同样只有表头
bf = cu.post(
    "/api/v1/imports",
    data={"account_id": acc, "kind": "trades"},
    files={"file": ("trades_sample.txt", (FX / "trades_sample.txt").read_bytes(), "text/plain")},
    headers=hu,
).json()["batch_id"]
q(
    "update app.import_batches set status='failed', file_findings="
    '\'[{"id":"f1","code":"IMPORT_PARSE_FAILED","severity":"error","message":"m"}]\'::jsonb '
    "where id = :b",
    b=bf,
)
q("delete from app.import_rows where batch_id = :b", b=bf)
body = cu.get(f"/api/v1/imports/{bf}/errors.csv").content.decode("utf-8-sig")
check(body.count("\r\n") == 1, "#35：failed 批次 errors.csv 只有表头（批次头提示不输出）")
check(file_row(bf).deleted_at is None, "#35：failed 批次原始文件保留")

# ---------------------------------------------------------------- T-B56 任务名 + 原始文件到期清理
check(
    jobs.PURGE_IMPORT_ROWS == "imports.purge_preview_rows",
    "T-B56：预览行清理任务名 imports.purge_preview_rows",
)
check(mk().import_raw_purge_interval_s == 86400, "plan 7.3：原始文件清理默认每日（86400s）")
check(
    jobs.schedule(mk(import_raw_purge_interval_s=120)).get(jobs.PURGE_RAW_FILES) == 120,
    "m6：beat 排程含原始文件清理，间隔取配置",
)
q(
    "update app.import_files set retained_until = now() - interval '1 second' where batch_id = :b",
    b=bd,
)
q("update app.import_files set retained_until = now() + interval '1 day' where batch_id = :b", b=bf)
bx_files = q(
    "insert into app.import_batches(id, user_id, account_id, status, kind) "
    "select gen_random_uuid(), user_id, id, 'discarded', 'trades' from app.accounts "
    "where id = :a returning id",
    a=acc,
).scalar_one()
gone = q(
    "insert into app.import_files(batch_id, storage_path, retained_until) "
    "values (:b, :p, now() - interval '1 day') returning id",
    b=bx_files,
    p=f"{uuid.uuid4()}/missing.bin",
).scalar_one()
with engine().begin() as c:
    n1 = pipeline.purge_expired_raw_files(c, st)
fr = file_row(bd)
check(
    n1 >= 2 and not raw_path.exists() and fr.deleted_at is not None and fr.storage_path is None,
    f"m6：到期文件删除并标记（{n1}）",
)
check(
    file_row(bf).deleted_at is None and (STORE / file_row(bf).storage_path).is_file(),
    "m6：未到期文件保留",
)
check(
    q("select deleted_at from app.import_files where id = :i", i=gone).scalar_one() is not None,
    "m6：磁盘上已不存在的文件视为已删",
)
with engine().begin() as c:
    check(pipeline.purge_expired_raw_files(c, st) == 0, "m6：幂等，第二次 0 个")
esc = q(
    "insert into app.import_files(batch_id, storage_path, retained_until) "
    "values (:b, '../../etc/passwd', now() - interval '1 day') returning id",
    b=bx_files,
).scalar_one()
with engine().begin() as c:
    pipeline.purge_expired_raw_files(c, st)
check(
    q("select deleted_at from app.import_files where id = :i", i=esc).scalar_one() is None,
    "m6：越界路径不删、行保留待重试",
)
q("delete from app.import_files where id = :i", i=esc)

# ---------------------------------------------------------------- m2 / m9 / M3
spec = cu.get("/openapi.json")
if spec.status_code != 200:
    spec = cu.get("/api/v1/openapi.json")
props = spec.json()["components"]["schemas"]["ResolveIn"]["properties"]
check("200" in str(props["reason"]), "m2：OpenAPI ResolveIn.reason maxLength 200")
r = upload(acc, "trades_bad_formats.txt")
b2 = r.json()["batch_id"]
items = cu.get(f"/api/v1/imports/{b2}/rows", params={"limit": 200}).json()["items"]
fid2 = next((f["id"] for it in items for f in it["findings"]), "r1-x")
r = cu.post(
    f"/api/v1/imports/{b2}/findings/{fid2}/resolve",
    headers=idem(hu),
    json={"choice": "x", "reason": "长" * 201},
)
check(r.status_code == 400, f"m2：reason 201 字 → 400（{r.status_code} {err_code(r)}）")

acc2 = acct(cu, hu)
r = upload(acc2, "trades_sample.txt")
b3 = r.json()["batch_id"]
r = cu.post(
    f"/api/v1/imports/{b3}/confirm",
    headers=idem(hu),
    json={"mode": "valid_rows_only", "acknowledge_warnings": True},
)
check(
    r.status_code == 200 and r.json()["written"]["trades"] == 66,
    f"M3：两步导入确认 66 笔（{r.status_code}）",
)
check(co.get(f"/api/v1/imports/{b3}").status_code == 404, "M3：他人批次 → 404")
check(co.get(f"/api/v1/imports/{b3}/rows").status_code == 404, "M3：他人批次 rows → 404")
check(
    co.get(f"/api/v1/imports/{b3}/errors.csv").status_code == 404, "M3：他人批次 errors.csv → 404"
)
tid = cu.get("/api/v1/trades", params={"account_id": acc2, "limit": 1}).json()["items"][0]["id"]
secret_reason = "作废理由" + secrets.token_hex(4)
r = co.post(f"/api/v1/trades/{tid}/void", headers=idem(ho), json={"reason": secret_reason})
check(r.status_code == 404, f"M3：作废他人成交 → 404（{r.status_code}）")
r = cu.post(f"/api/v1/trades/{tid}/void", headers=idem(hu), json={"reason": secret_reason})
check(
    r.status_code == 200 and r.json().get("voided_at"),
    f"M3：作废成交 → 200（{r.status_code} {err_code(r)}）",
)
r = cu.post(f"/api/v1/trades/{tid}/void", headers=idem(hu), json={"reason": secret_reason})
check(r.status_code == 409, f"M3：重复作废 → 409（{r.status_code}）")
det = q(
    "select detail::text from app.audit_logs where action = 'trade.voided' and target_id = :t",
    t=str(tid),
).scalar_one()
check(secret_reason not in det and "reason_given" in det, "m9：trade.voided 审计不含理由原文")
hits = q(
    "select count(*) from app.audit_logs where detail::text like :p", p=f"%{secret_reason}%"
).scalar_one()
check(hits == 0, "m9：审计表任何行都不含理由原文")
check(
    co.get("/api/v1/portfolio", params={"account_id": acc2}).status_code == 404,
    "M3：他人账户持仓 → 404",
)
r = cu.get("/api/v1/portfolio", params={"account_id": acc2})
check(r.status_code == 200, f"M3：本人持仓 → 200（{r.status_code}）")

# ---------------------------------------------------------------- m5 日志脱敏
from app.common.logging import RedactFilter, redact  # noqa: E402

# 虚构样本运行时拼出（避免源码里出现股东代码 / 资金账号形态，secret_scan S5）
HOLDER = "A" + "".join(str(i) for i in range(1, 10))
FUND = "00" + "".join(str(i) for i in range(1, 9))
u = str(uuid.uuid4())
check(redact(f"batch={u}") == f"batch={u}", "m5：UUID 不脱敏")
check(HOLDER not in redact(f"acct {HOLDER} x"), "m5：股东代码脱敏")
check(FUND not in redact(f"fund {FUND}"), "m5：资金账号脱敏")
records: list[str] = []


class _H(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        records.append(self.format(record))


h = _H()
h.addFilter(RedactFilter())
pl = logging.getLogger("app.importing.pipeline")
pl.addHandler(h)


def boom(*_a: Any, **_k: Any) -> None:  # noqa: ANN401
    raise RuntimeError(f"证券代码 {HOLDER} 资金 {FUND}")


bx = q(
    "insert into app.import_batches(id, user_id, account_id, status, kind) "
    "select gen_random_uuid(), user_id, id, 'parsing', 'trades' from app.accounts "
    "where id = :a returning id",
    a=acc,
).scalar_one()
saved = pipeline._run_parse
pipeline._run_parse = boom  # type: ignore[assignment]
try:
    pipeline.run_parse(engine(), st, bx)
finally:
    pipeline._run_parse = saved  # type: ignore[assignment]
    pl.removeHandler(h)
joined = "\n".join(records)
check(
    records and HOLDER not in joined and FUND not in joined and "RuntimeError" in joined,
    "m5：解析失败日志只记批次号与异常类型",
)

# ---------------------------------------------------------------- m7 根目录
from app.cli import delete_user_data as cli  # noqa: E402

check(storage.resolve_imports_root("/x/y", "production") == Path("/x/y"), "m7：配置路径优先")
check(storage.resolve_imports_root(None, "production") is None, "m7：生产未配置 → None（API 503）")
check(
    storage.resolve_imports_root(None, "test") == Path(tempfile.gettempdir()) / "aia-imports",
    "m7：local/test 未配置 → <tmp>/aia-imports",
)
saved_env = {k: os.environ.get(k) for k in ("AIA_IMPORTS_DIR", "IMPORT_STORAGE_PATH", "APP_ENV")}
try:
    for k in saved_env:
        os.environ.pop(k, None)
    os.environ["APP_ENV"] = "production"
    check(
        cli.imports_root() == Path(storage.DEFAULT_IMPORTS_DIR),
        "m7：CLI 生产未配置 → /srv/aia/imports",
    )
    os.environ["IMPORT_STORAGE_PATH"] = str(STORE)
    check(cli.imports_root() == STORE, "m7：CLI 与 API 同用 IMPORT_STORAGE_PATH")
    os.environ["AIA_IMPORTS_DIR"] = "/override"
    check(cli.imports_root() == Path("/override"), "m7：AIA_IMPORTS_DIR 覆盖")
finally:
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

# ---------------------------------------------------------------- m8 kek_id
blob = storage.encrypt_file(st, b"hello", b"aad")
check(
    blob[:4] == storage.MAGIC and storage.file_kek_id(blob) is not None,
    "m8：新文件头 AIA2 + kek_id",
)
check(storage.decrypt_file(st, blob, b"aad") == b"hello", "m8：同 KEK 解密")
other = mk()
try:
    storage.decrypt_file(other, blob, b"aad")
    mism = False
except storage.KekMismatchError:
    mism = True
check(mism, "m8：KEK 不一致 → KekMismatchError（不尝试解密）")
legacy = storage.MAGIC_V1 + blob[4 + storage.KEK_ID_LEN :]
check(storage.decrypt_file(st, legacy, b"aad") == b"hello", "m8：旧格式 AIA1 仍可解密")

rds.flushdb()
finish()
