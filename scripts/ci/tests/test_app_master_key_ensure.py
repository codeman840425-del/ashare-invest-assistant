"""deploy/scripts/app-master-key-ensure.sh 与 secret-env.sh 的 M1 自测（T-O11 评审 M1：不悄悄生成新主密钥）。

docker 用桩脚本模拟（卷是否存在、谁挂着数据卷、psql 返回什么），不需要真 docker。所有密钥值运行时随机生成，
断言：输出里从不出现密钥值；迁移后文件 600、内容与旧值一致；.env 一字不改；拒绝时不生成文件。
"""

from __future__ import annotations

import os
import re
import secrets
import stat
import subprocess
from pathlib import Path

import pytest

from conftest import REPO

ENSURE = REPO / "deploy/scripts/app-master-key-ensure.sh"
SECRET_ENV = REPO / "deploy/docker/secret-env.sh"
VAR = "APP_MASTER" + "_KEY"
PREFIX = "t-m1"

FAKE_DOCKER = r"""#!/usr/bin/env bash
st="$FAKE_DOCKER_STATE"
printf '%s\n' "$*" >> "$st/calls"
case "$1" in
  info) exit "$(cat "$st/info_rc" 2>/dev/null || echo 0)" ;;
  volume) [ -e "$st/vol_$3" ] ; exit $? ;;
  run) cat "$st/imports_count" 2>/dev/null || echo 0 ; exit 0 ;;
  ps) v="${4#volume=}"; cat "$st/ps_$v" 2>/dev/null; exit 0 ;;
  exec) cat > "$st/sql"; cat "$st/psql_out" 2>/dev/null; exit "$(cat "$st/psql_rc" 2>/dev/null || echo 0)" ;;
esac
exit 99
"""


class Env:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.secrets = tmp / "secrets"
        self.key = self.secrets / "app_master_key"
        self.env_file = tmp / ".env"
        self.state = tmp / "state"
        self.state.mkdir()
        self.docker = tmp / "docker"
        self.docker.write_text(FAKE_DOCKER, encoding="utf-8")
        self.docker.chmod(0o755)

    def set(self, name: str, value: str) -> None:
        (self.state / name).write_text(value, encoding="utf-8")

    def volume(self, name: str) -> None:
        self.set(f"vol_{PREFIX}_{name}", "")

    def calls(self) -> str:
        p = self.state / "calls"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def run(self, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k not in (VAR, "MAIRUI_LICENCE", "DEEPSEEK_API_KEY")}
        env.update(AIA_DOCKER=str(self.docker), FAKE_DOCKER_STATE=str(self.state), AIA_APP_UID=str(os.getuid()),
                   AIA_KEYCHECK_IMAGE="fake/pg:1")
        env.update(extra_env or {})
        return subprocess.run(["bash", str(ENSURE), str(self.secrets), str(self.env_file), PREFIX],
                              capture_output=True, text=True, env=env)


@pytest.fixture
def e(tmp_path: Path) -> Env:
    return Env(tmp_path)


def _key() -> str:
    return secrets.token_hex(32)


def _no_leak(r: subprocess.CompletedProcess[str], e: Env, *vals: str) -> None:
    for v in vals:
        assert v not in r.stdout and v not in r.stderr, "输出里出现了密钥值"
        assert v not in e.calls(), "docker 命令行里出现了密钥值"


def _assert_key_file(e: Env, expect: str | None = None) -> str:
    st = e.key.stat()
    assert stat.S_IMODE(st.st_mode) == 0o600
    val = e.key.read_text(encoding="utf-8")
    if expect is not None:
        assert val == expect
    else:
        assert re.fullmatch(r"[0-9a-f]{64}", val)
    assert not [p for p in e.secrets.iterdir() if p.name != "app_master_key"], "残留临时文件"
    return val


# ---- 1. 已有密钥文件：直接用 ----
def test_existing_key_used_untouched(e: Env) -> None:
    e.secrets.mkdir()
    k = _key()
    e.key.write_text(k, encoding="utf-8")
    e.env_file.write_text(f"{VAR}={_key()}\n", encoding="utf-8")   # .env 里另一把也不影响
    r = e.run()
    assert r.returncode == 0, r.stderr
    assert e.key.read_text(encoding="utf-8") == k
    assert e.calls() == ""   # 不碰 docker
    _no_leak(r, e, k)


def test_existing_empty_key_refused_not_overwritten(e: Env) -> None:
    e.secrets.mkdir()
    e.key.write_text("", encoding="utf-8")
    r = e.run()
    assert r.returncode == 3 and "为空" in r.stderr
    assert e.key.read_text(encoding="utf-8") == ""


# ---- 2. 迁移旧 .env / 环境变量 ----
@pytest.mark.parametrize("fmt", ["{v}={k}\n", "export {v}={k}\n", '{v}="{k}"\r\n', "  {v} = '{k}'  \n",
                                 "{v}=changeme\n{v}={k}\n"])
def test_migrate_from_env_file(e: Env, fmt: str) -> None:
    k = _key()
    body = "POSTGRES_DB=aia\n" + fmt.format(v=VAR, k=k) + "OTHER=1\n"
    e.env_file.write_text(body, encoding="utf-8", newline="")
    e.volume("pgdata")   # 有数据也照样迁移（迁移不需要查库）
    r = e.run()
    assert r.returncode == 0, r.stderr
    _assert_key_file(e, k)
    assert "已从" in r.stderr and "迁移" in r.stderr and "未删除" in r.stderr
    assert e.env_file.read_bytes() == body.encode("utf-8"), ".env 不应被修改"
    assert e.calls() == ""
    _no_leak(r, e, k)


def test_migrate_from_process_env(e: Env) -> None:
    k = _key()
    r = e.run({VAR: k})
    assert r.returncode == 0, r.stderr
    _assert_key_file(e, k)
    assert "环境变量" in r.stderr
    _no_leak(r, e, k)


def test_env_and_file_same_value_migrates(e: Env) -> None:
    k = _key()
    e.env_file.write_text(f"{VAR}={k}\n", encoding="utf-8")
    r = e.run({VAR: k})
    assert r.returncode == 0, r.stderr
    _assert_key_file(e, k)


def test_env_and_file_conflict_refused(e: Env) -> None:
    k1, k2 = _key(), _key()
    e.env_file.write_text(f"{VAR}={k1}\n", encoding="utf-8")
    r = e.run({VAR: k2})
    assert r.returncode == 3 and "不一致" in r.stderr
    assert not e.key.exists()
    _no_leak(r, e, k1, k2)


def test_short_legacy_key_refused(e: Env) -> None:
    short = secrets.token_hex(8)
    e.env_file.write_text(f"{VAR}={short}\n", encoding="utf-8")
    r = e.run()
    assert r.returncode == 3 and "32" in r.stderr
    assert not e.key.exists()
    _no_leak(r, e, short)


@pytest.mark.parametrize("placeholder", ["", "changeme-local-only", "<fill-me>", "example-key"])
def test_placeholder_is_not_a_key_and_existing_db_refused(e: Env, placeholder: str) -> None:
    e.env_file.write_text(f"{VAR}={placeholder}\n", encoding="utf-8")
    e.volume("pgdata")
    e.set(f"ps_{PREFIX}_pgdata", "cid123\n")
    e.set("psql_out", "27|1|3|0|0\n")
    r = e.run()
    assert r.returncode == 3 and "库已初始化" in r.stderr and "app.users=1" in r.stderr
    assert not e.key.exists() and not e.secrets.exists()


# ---- 3. 两边都没有 ----
def test_fresh_deploy_no_volumes_generates(e: Env) -> None:
    r = e.run()
    assert r.returncode == 0, r.stderr
    k = _assert_key_file(e)
    assert "全新空库" in r.stderr
    _no_leak(r, e, k)


def test_empty_db_generates(e: Env) -> None:
    e.volume("pgdata")
    e.volume("imports")
    e.set(f"ps_{PREFIX}_pgdata", "cid123\n")
    e.set("psql_out", "0|0|0|0|0\n")
    r = e.run()
    assert r.returncode == 0, r.stderr
    _assert_key_file(e)
    sql = (e.state / "sql").read_text(encoding="utf-8")
    for t in ("app.users", "app.invite_codes", "app.user_data_licences", "app.import_files", "deptype = 'e'"):
        assert t in sql
    assert "exec -i cid123" in e.calls()


@pytest.mark.parametrize("out,needle", [
    ("1|0|0|0|0", "1 张业务表"),                          # 只有 alembic_version 也算已初始化
    ("30|0|2|0|0", "app.invite_codes=2"),
    ("30|0|0|1|0", "app.user_data_licences=1"),
    ("30|0|0|0|4", "app.import_files=4"),
])
def test_initialized_db_refused(e: Env, out: str, needle: str) -> None:
    e.volume("pgdata")
    e.set(f"ps_{PREFIX}_pgdata", "cid123\n")
    e.set("psql_out", out + "\n")
    r = e.run()
    assert r.returncode == 3, r.stderr
    assert "拒绝启动" in r.stderr and needle in r.stderr and "app-master-keygen.sh" in r.stderr
    assert not e.key.exists()


def test_pgdata_without_running_db_refused(e: Env) -> None:
    e.volume("pgdata")
    r = e.run()
    assert r.returncode == 3 and "没有运行中的 postgres" in r.stderr
    assert not e.key.exists()


@pytest.mark.parametrize("rc,out", [("2", ""), ("0", "garbage\n"), ("0", "")])
def test_db_query_failure_refused(e: Env, rc: str, out: str) -> None:
    e.volume("pgdata")
    e.set(f"ps_{PREFIX}_pgdata", "cid123\n")
    e.set("psql_rc", rc)
    e.set("psql_out", out)
    r = e.run()
    assert r.returncode == 3, r.stderr
    assert not e.key.exists()


def test_imports_with_files_refused(e: Env) -> None:
    e.volume("imports")
    e.set("imports_count", "3\n")
    r = e.run()
    assert r.returncode == 3 and "导入卷" in r.stderr and "3 个文件" in r.stderr
    assert not e.key.exists()


def test_empty_imports_volume_generates(e: Env) -> None:
    e.volume("imports")
    e.set("imports_count", "0\n")
    r = e.run()
    assert r.returncode == 0, r.stderr
    _assert_key_file(e)
    assert "run --rm --network none" in e.calls() and ":ro" in e.calls()


def test_docker_unavailable_refused(e: Env) -> None:
    e.set("info_rc", "1")
    r = e.run()
    assert r.returncode == 3 and "访问不了 docker" in r.stderr
    assert not e.key.exists()


def test_usage_errors(e: Env) -> None:
    r = subprocess.run(["bash", str(ENSURE), "relative", str(e.env_file), PREFIX], capture_output=True, text=True)
    assert r.returncode == 2
    r = subprocess.run(["bash", str(ENSURE)], capture_output=True, text=True)
    assert r.returncode == 2


# ---- secret-env.sh：AIA_REQUIRE_APP_MASTER_KEY ----
def _secret_env(sd: Path, require: str | None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "AIA_SECRET_ENV_DIR": str(sd)}
    if require is not None:
        env["AIA_REQUIRE_APP_MASTER_KEY"] = require
    return subprocess.run(["sh", str(SECRET_ENV), "sh", "-c", f'[ ${{#{VAR}}} -ge 32 ] && echo has-key || echo no-key'],
                          capture_output=True, text=True, env=env)


def test_secret_env_require_flag_missing_refused(tmp_path: Path) -> None:
    r = _secret_env(tmp_path, "1")
    assert r.returncode == 2 and "拒绝启动" in r.stderr and "no-key" not in r.stdout


def test_secret_env_without_flag_unchanged(tmp_path: Path) -> None:
    r = _secret_env(tmp_path, None)
    assert r.returncode == 0 and r.stdout.strip() == "no-key"


def test_secret_env_require_flag_with_key(tmp_path: Path) -> None:
    k = _key()
    (tmp_path / "app_master_key").write_text(k, encoding="utf-8")
    r = _secret_env(tmp_path, "1")
    assert r.returncode == 0 and r.stdout.strip() == "has-key"
    assert k not in r.stdout + r.stderr


# ---- compose.sh 接线 ----
def test_compose_sh_calls_ensure_before_docker_compose() -> None:
    text = (REPO / "deploy/scripts/compose.sh").read_text(encoding="utf-8")
    code = "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())
    assert "app-master-keygen.sh" not in code
    i_ensure = code.index("app-master-key-ensure.sh")
    assert code.index("DOCKER=(") < i_ensure, "ensure 要在 docker 命令确定之后（需要查库）"
    assert re.search(r'app-master-key-ensure\.sh"[^\n]*\|\| exit \$\?', code), "ensure 失败必须中止"
