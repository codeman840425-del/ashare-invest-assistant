"""契约 v0.2.9 #41 自检（docs 96ea475）：``/securities/*`` 全部响应
``Cache-Control: private, no-store``；``delete_raw`` 在存储根目录不存在时报错（review-028c077 M2）。

只用 TestClient 与临时目录，不连外网、不调用麦蕊。运行（目录 ``src/backend``）::

    env -u MAIRUI_LICENCE PYTHONPATH=$PWD .venv/bin/python selfchecks/c41.py
"""

from __future__ import annotations

import secrets
import tempfile
import uuid
from pathlib import Path

from _common import DB, RURL, check, finish
from fastapi import Response
from fastapi.testclient import TestClient

from app.config import Settings
from app.importing import storage
from app.main import SECURITIES_CACHE_CONTROL, create_app

STORE = Path(tempfile.mkdtemp(prefix="c41_store_"))
st = Settings(
    database_url=DB,
    redis_url=RURL,
    app_env="local",
    app_master_key=secrets.token_urlsafe(32),
    import_storage_path=STORE,
)
app = create_app(st)
P = st.api_prefix
NS = "private, no-store"
check(SECURITIES_CACHE_CONTROL == NS, "常量为 private, no-store")


# 测试专用路由（只挂在本进程的 app 上）：模拟路由自己写了旧的缓存头、304、未捕获异常
def _old_header() -> Response:
    return Response(
        "{}", media_type="application/json", headers={"Cache-Control": "private, max-age=60"}
    )


def _not_modified() -> Response:
    return Response(
        status_code=304, headers={"ETag": 'W/"x"', "Cache-Control": "private, no-cache"}
    )


def _boom() -> Response:
    raise RuntimeError("selfcheck")


app.add_api_route(f"{P}/securities/_c41/old", _old_header)
app.add_api_route(f"{P}/securities/_c41/304", _not_modified)
app.add_api_route(f"{P}/securities/_c41/boom", _boom)
app.add_api_route(f"{P}/securitiesx/_c41", _old_header)

c = TestClient(app, raise_server_exceptions=False)
cases = {
    "路由写 max-age=60 被覆盖": (f"{P}/securities/_c41/old", 200),
    "304 也带": (f"{P}/securities/_c41/304", 304),
    "兜底 500 也带": (f"{P}/securities/_c41/boom", 500),
    "未知子路径 404 也带": (f"{P}/securities/search?q=x", None),
    "前缀本身（?q=）也带": (f"{P}/securities?q=pfyh", None),
    "{code} 子资源也带": (f"{P}/securities/600000.SH/bars", None),
}
for name, (url, code) in cases.items():
    r = c.get(url)
    ok = r.headers.get("cache-control") == NS and (code is None or r.status_code == code)
    check(ok, f"#41①：{name}（{r.status_code} {r.headers.get('cache-control')}）")
r = c.get(f"{P}/securities/_c41/old")
check(r.headers.get_list("cache-control") == [NS], "#41①：只有一个 Cache-Control 头")
r = c.get(f"{P}/securitiesx/_c41")
check(
    r.headers.get("cache-control") == "private, max-age=60", "#41①：相似前缀 /securitiesx 不受影响"
)
r = c.get(f"{P}/meta/enums")
check(r.headers.get("cache-control") != NS, "#41①：其他路径（/meta/enums）不受影响")
big = c.post(f"{P}/securities/_c41/old", content=b"x" * 8, headers={"Content-Length": str(10**9)})
check(big.headers.get("cache-control") == NS, f"#41①：413 等中间件响应也带（{big.status_code}）")

# ---- #41 ②
rel = f"{uuid.uuid4()}/a.bin"
(STORE / rel).parent.mkdir(parents=True)
(STORE / rel).write_bytes(b"x")
storage.delete_raw(st, rel)
check(not (STORE / rel).exists(), "#41②：根目录存在 → 删除文件")
try:
    storage.delete_raw(st, rel)
    ok = True
except OSError:
    ok = False
check(ok, "#41②：根目录存在、文件已不在 → 视为已删（不报错）")
st_missing = Settings(
    database_url=DB,
    redis_url=RURL,
    app_env="local",
    app_master_key=secrets.token_urlsafe(32),
    import_storage_path=STORE / "absent",
)
try:
    storage.delete_raw(st_missing, rel)
    raised = None
except storage.StorageRootMissingError as exc:
    raised = exc
check(raised is not None, "#41②：根目录不存在 → StorageRootMissingError")
check(isinstance(raised, OSError), "#41②：该异常是 OSError（清理任务按失败处理、行保留）")
check(raised is not None and "absent" not in str(raised), "#41②：异常信息不含路径")
check(not (STORE / "absent").exists(), "#41②：不会顺手创建根目录")

finish()
