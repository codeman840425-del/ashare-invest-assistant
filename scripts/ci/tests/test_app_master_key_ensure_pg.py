"""评审 8cf9771 n2：app-master-key-ensure.sh 的③（查库判定是否空库）对真实 PostgreSQL 跑一遍。

test_app_master_key_ensure.py 用假 docker 只验证了 SQL 文本和输出解析；这里起一次性 timescale 容器（与 compose 同一镜像、
--network none、trust 认证、无口令），挂一个本测试专用的 <前缀>_pgdata 卷，让脚本用真 docker exec + psql 执行它自己的 SQL：
表不存在 / 表为空 → 生成；任一表有行、llm_providers 有密文 → 拒绝；llm_providers 没有密文列 → 算 0；会话确实是只读。
不碰任何现有容器和卷；结束时删除本测试的容器、卷和临时密钥目录。没有 docker 时跳过（CI 设 AIA_CI_REQUIRE_DOCKER=1 则改为失败）。
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
ENSURE = REPO / "deploy/scripts/app-master-key-ensure.sh"
COMPOSE = REPO / "deploy/compose/docker-compose.yml"


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


if not _docker_ok():
    if os.environ.get("AIA_CI_REQUIRE_DOCKER") == "1":
        raise RuntimeError("AIA_CI_REQUIRE_DOCKER=1 但 docker 不可用：真实 PG 用例不能跳过")
    pytest.skip("没有 docker，跳过真实 PG 用例", allow_module_level=True)

IMAGE = re.search(r"^\s*image:\s*(timescale/\S+)", COMPOSE.read_text(encoding="utf-8"), re.M).group(1)


def _d(*args: str, check: bool = True, inp: str | None = None) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(["docker", *args], capture_output=True, text=True, input=inp)
    if check and r.returncode != 0:
        raise AssertionError(f"docker {args[0]} 失败：{r.stderr[-400:]}")
    return r


class PG:
    def __init__(self) -> None:
        self.prefix = "ci-n2-" + secrets.token_hex(4)
        self.vol = f"{self.prefix}_pgdata"
        self.name = f"{self.prefix}-pg"

    def start(self) -> None:
        _d("volume", "create", "--label", "aia.ci=n2", self.vol)
        _d("run", "-d", "--name", self.name, "--label", "aia.ci=n2", "--network", "none",
           "-e", "POSTGRES_USER=aia", "-e", "POSTGRES_DB=aia", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
           "-v", f"{self.vol}:/var/lib/postgresql/data", IMAGE)
        # initdb 阶段的临时服务器只听 unix socket；走 127.0.0.1 能连上才算正式启动完成
        deadline = time.time() + 120
        while time.time() < deadline:
            r = _d("exec", self.name, "psql", "-h", "127.0.0.1", "-U", "aia", "-d", "aia", "-Atc", "select 1", check=False)
            if r.returncode == 0 and r.stdout.strip() == "1":
                return
            time.sleep(1)
        raise AssertionError("一次性 postgres 120 秒内没有就绪：" + _d("logs", "--tail", "20", self.name, check=False).stderr[-400:])

    def sql(self, q: str) -> str:
        return _d("exec", "-i", self.name, "psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-U", "aia", "-d", "aia",
                  inp=q).stdout

    def stop(self) -> None:
        _d("rm", "-f", "-v", self.name, check=False)
        _d("volume", "rm", "-f", self.vol, check=False)


@pytest.fixture(scope="module")
def pg():
    p = PG()
    try:
        p.start()
        yield p
    finally:
        p.stop()


def _ensure(pg: PG, tmp: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    sd = tmp / "secrets"
    env = {k: v for k, v in os.environ.items() if k not in ("APP_MASTER" + "_KEY", "MAIRUI_LICENCE", "DEEPSEEK_API_KEY")}
    env.update(AIA_DOCKER="docker", AIA_APP_UID=str(os.getuid()), AIA_KEYCHECK_IMAGE=IMAGE)
    r = subprocess.run(["bash", str(ENSURE), str(sd), str(tmp / "no.env"), pg.prefix], capture_output=True, text=True, env=env)
    return r, sd / "app_master_key"


def _reset(pg: PG) -> None:
    pg.sql("DROP SCHEMA IF EXISTS app CASCADE;")


SCHEMA = """
CREATE SCHEMA app;
CREATE TABLE app.users (id bigserial PRIMARY KEY, username text);
CREATE TABLE app.invite_codes (id bigserial PRIMARY KEY, code_hmac bytea);
CREATE TABLE app.user_data_licences (id bigserial PRIMARY KEY, fp bytea);
CREATE TABLE app.import_files (id bigserial PRIMARY KEY, path text);
CREATE TABLE app.llm_providers (id bigserial PRIMARY KEY, name text, api_key_ciphertext bytea);
"""


def test_no_app_schema_generates(pg: PG, tmp_path: Path) -> None:
    _reset(pg)
    r, key = _ensure(pg, tmp_path)
    assert r.returncode == 0 and "全新部署" in r.stderr, r.stderr
    assert key.exists() and re.fullmatch(r"[0-9a-f]{64}", key.read_text(encoding="utf-8"))
    assert key.read_text(encoding="utf-8") not in r.stdout + r.stderr


def test_empty_tables_generate(pg: PG, tmp_path: Path) -> None:
    _reset(pg)
    pg.sql(SCHEMA + "INSERT INTO app.llm_providers (name) VALUES ('no-key');")   # 没有密文的行不算数据
    r, key = _ensure(pg, tmp_path)
    assert r.returncode == 0 and "全新部署" in r.stderr, r.stderr
    assert key.exists()


@pytest.mark.parametrize("ins,needle", [
    ("INSERT INTO app.users (username) VALUES ('u');", "app.users=1"),
    ("INSERT INTO app.invite_codes (code_hmac) VALUES ('\\x00'), ('\\x01');", "app.invite_codes=2"),
    ("INSERT INTO app.user_data_licences (fp) VALUES ('\\x00');", "app.user_data_licences=1"),
    ("INSERT INTO app.import_files (path) VALUES ('p');", "app.import_files=1"),
    ("INSERT INTO app.llm_providers (name, api_key_ciphertext) VALUES ('p', '\\x00');", "app.llm_providers 密文=1"),
])
def test_rows_refused(pg: PG, tmp_path: Path, ins: str, needle: str) -> None:
    _reset(pg)
    pg.sql(SCHEMA + ins)
    r, key = _ensure(pg, tmp_path)
    assert r.returncode == 3 and "拒绝启动" in r.stderr and needle in r.stderr, r.stderr
    assert not key.exists()


def test_llm_providers_without_ciphertext_column_counts_zero(pg: PG, tmp_path: Path) -> None:
    _reset(pg)
    pg.sql(SCHEMA.replace(", api_key_ciphertext bytea", "") + "INSERT INTO app.llm_providers (name) VALUES ('p');")
    r, key = _ensure(pg, tmp_path)
    assert r.returncode == 0, r.stderr
    assert key.exists()


def test_session_is_read_only(pg: PG) -> None:
    # 脚本的两道只读（PGOPTIONS + BEGIN READ ONLY）在真实 PG 上确实挡写
    _reset(pg)
    pg.sql(SCHEMA)
    for wrapper in (["-e", "PGOPTIONS=-c default_transaction_read_only=on"], []):
        q = "INSERT INTO app.users (username) VALUES ('w');" if wrapper else "BEGIN READ ONLY;\nINSERT INTO app.users (username) VALUES ('w');\nCOMMIT;"
        r = _d("exec", "-i", *wrapper, pg.name, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", "aia", "-d", "aia",
               inp=q, check=False)
        assert r.returncode != 0 and "read-only transaction" in r.stderr
    assert pg.sql("SELECT count(*) FROM app.users;").strip() == "0"


def test_postgres_stopped_refused(pg: PG, tmp_path: Path) -> None:
    # 卷在、没有运行中的 postgres 挂着 → fail-closed（最后跑：停掉后本模块不再用它）
    _d("stop", pg.name)
    r, key = _ensure(pg, tmp_path)
    assert r.returncode == 3 and "没有运行中的 postgres" in r.stderr, r.stderr
    assert not key.exists()
