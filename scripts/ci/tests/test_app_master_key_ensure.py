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


# ---- 1 / ④. 已有密钥文件 ----
@pytest.mark.parametrize("env_body", [None, "POSTGRES_DB=aia\n", f"{VAR}=changeme-local-only\n", f"{VAR}=\n"])
def test_existing_key_used_untouched(e: Env, env_body: str | None) -> None:
    e.secrets.mkdir()
    k = _key()
    e.key.write_text(k, encoding="utf-8")
    if env_body is not None:
        e.env_file.write_text(env_body, encoding="utf-8")   # 没有旧值 / 只有占位值
    r = e.run()
    assert r.returncode == 0, r.stderr
    assert e.key.read_text(encoding="utf-8") == k
    assert e.calls() == ""   # 不碰 docker
    _no_leak(r, e, k)


def test_existing_key_conflicts_with_env_file_refused(e: Env) -> None:
    # plan 升级约束④：secret 文件与旧 .env 都有且不一致 → 拒绝启动，等人工确认；两边都不改
    e.secrets.mkdir()
    k, old = _key(), _key()
    e.key.write_text(k, encoding="utf-8")
    body = f"{VAR}={old}\n"
    e.env_file.write_text(body, encoding="utf-8")
    r = e.run()
    assert r.returncode == 3 and "不一致" in r.stderr and "④" in r.stderr
    assert e.key.read_text(encoding="utf-8") == k and e.env_file.read_text(encoding="utf-8") == body
    assert e.calls() == ""
    _no_leak(r, e, k, old)


def test_existing_key_conflicts_with_process_env_refused(e: Env) -> None:
    e.secrets.mkdir()
    k, old = _key(), _key()
    e.key.write_text(k, encoding="utf-8")
    r = e.run({VAR: old})
    assert r.returncode == 3 and "不一致" in r.stderr
    assert e.key.read_text(encoding="utf-8") == k
    _no_leak(r, e, k, old)


def test_existing_key_same_as_env_file_used_and_prompts_delete(e: Env) -> None:
    e.secrets.mkdir()
    k = _key()
    e.key.write_text(k + "\n", encoding="utf-8")   # 文件末尾换行不算不一致（入口包装同样去掉）
    body = f"{VAR}={k}\n"
    e.env_file.write_text(body, encoding="utf-8")
    r = e.run()
    assert r.returncode == 0, r.stderr
    assert "一致" in r.stderr and "删除" in r.stderr
    assert e.env_file.read_text(encoding="utf-8") == body, ".env 不应被修改"
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
    assert "已从" in r.stderr and "迁移" in r.stderr and "删除 APP_MASTER_KEY 行" in r.stderr and "不自动删除" in r.stderr
    assert e.env_file.read_bytes() == body.encode("utf-8"), ".env 不应被修改"
    assert e.calls() == ""
    _no_leak(r, e, k)


# 评审 1cf643e m1 / 75c233b B1：按 docker compose 的 .env 规则解析；做不到逐字一致的写法拒绝。
ACCEPTED = [
    ("{v}={k}  # 线上主密钥\n", "{k}"),           # 空格 + # 起是注释
    ("export {v}={k} # c\r\n", "{k}"),
    ('{v}="{k}#x" # 注释\n', "{k}#x"),            # 引号里的 # 保留，引号后的注释忽略
    ("{v}='{k}#x'  # c\n", "{k}#x"),
    ('{v}="{k}"#c\n', "{k}"),                      # 引号后紧跟的注释忽略
    ("{v}={k}#x\n", "{k}#x"),                      # 未加引号、# 前没有空格：不是注释
    ("{v} = {k}\n", "{k}"),
    ("  {v}=   {k}   \n", "{k}"),
    ("{v}='{k}'\n", "{k}"),
    ("{v}=<填写>  # 占位\n{v}={k} # 后一行生效\n", "{k}"),  # 同名多行取最后一行
]
REFUSED = [
    ("{v}={k}\t#c\n", "空白"),                     # compose 把“制表符 + #c”算进值里
    ("{v}='{k} #x'\n", "空白"),
    ("{v}=   # 本应是空值\n", "空白"),                # compose 读到的是“# 本应是空值”
    ("{v}: {k}\n", "KEY: VALUE"),
    ("{v}={k}$HOME\n", "插值"),
    ('{v}="{k}${{X}}"\n', "插值"),
    ('{v}="{k}\\n"\n', "反斜杠"),
    ("{v}='{k}\\'x'\n", "反斜杠"),
    ('{v}="{k}" x\n', "非注释内容"),
    ("{v}='{k}'x\n", "非注释内容"),
    ('{v}="{k}\n', "引号不配对"),
    ("{v}='{k} # c\n", "引号不配对"),
    ('{v}="{k}\nmore"\n', "引号不配对"),          # 跨行引号
]


@pytest.mark.parametrize("line,expect", ACCEPTED)
def test_migrate_env_file_inline_comment(e: Env, line: str, expect: str) -> None:
    k = _key()
    e.env_file.write_text(line.format(v=VAR, k=k), encoding="utf-8", newline="")
    r = e.run()
    assert r.returncode == 0, r.stderr
    _assert_key_file(e, expect.format(k=k))
    _no_leak(r, e, k)


@pytest.mark.parametrize("line,why", REFUSED)
def test_ambiguous_env_line_refused(e: Env, line: str, why: str) -> None:
    k = _key()
    e.env_file.write_text(line.format(v=VAR, k=k), encoding="utf-8", newline="")
    r = e.run()
    assert r.returncode == 3 and why in r.stderr and "无法保证与 docker compose" in r.stderr, r.stderr
    assert not e.key.exists()
    _no_leak(r, e, k)


def test_ambiguous_env_line_refused_even_with_key_file(e: Env) -> None:
    # 文件已存在时（④）同样拒绝：解析不确定就不能判断“一致”
    e.secrets.mkdir()
    k = _key()
    e.key.write_text(k, encoding="utf-8")
    e.env_file.write_text(f"{VAR}={k}\t# c\n", encoding="utf-8")
    r = e.run()
    assert r.returncode == 3 and "空白" in r.stderr
    assert e.key.read_text(encoding="utf-8") == k
    _no_leak(r, e, k)


@pytest.mark.parametrize("line", ['{v}="<请填写 主密钥>"  # 占位\n', "{v}=changeme now\n"])
def test_placeholder_not_parsed_strictly(e: Env, line: str) -> None:
    e.secrets.mkdir()
    k = _key()
    e.key.write_text(k, encoding="utf-8")
    e.env_file.write_text(line.format(v=VAR), encoding="utf-8")
    r = e.run()
    assert r.returncode == 0, r.stderr
    assert e.key.read_text(encoding="utf-8") == k


def _compose_value(tmp: Path, env_text: str) -> str | None:
    """用真 docker compose 解析 .env，返回插值后的 APP_MASTER_KEY（假值，只在内存里比较）。"""
    import json
    (tmp / "c.yml").write_text("services:\n  s:\n    image: busybox\n    environment:\n      V: ${" + VAR + "-UNSET}\n", encoding="utf-8")
    (tmp / "o.env").write_text(env_text, encoding="utf-8", newline="")
    r = subprocess.run(["docker", "compose", "-p", "t-envparse", "--env-file", str(tmp / "o.env"), "-f", str(tmp / "c.yml"),
                        "config", "--format", "json"], capture_output=True, text=True,
                       env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp")})
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)["services"]["s"]["environment"]["V"]


def _have_compose() -> bool:
    try:
        return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0
    except OSError:
        return False


@pytest.mark.skipif(not _have_compose(), reason="没有 docker compose，跳过与 compose 的逐字对照")
@pytest.mark.parametrize("line,expect", ACCEPTED)
def test_env_parse_matches_compose(tmp_path: Path, line: str, expect: str) -> None:
    """对照组：脚本接受的每种写法，docker compose 读到的值必须与脚本迁移进文件的值逐字相同。"""
    k = _key()
    assert _compose_value(tmp_path, line.format(v=VAR, k=k)) == expect.format(k=k)


def test_existing_key_equals_env_value_with_comment(e: Env) -> None:
    # ④：.env 行尾注释不得被当成值的一部分而误判“不一致”
    e.secrets.mkdir()
    k = _key()
    e.key.write_text(k, encoding="utf-8")
    e.env_file.write_text(f"{VAR}={k}   # 旧值，待删除\n", encoding="utf-8")
    r = e.run()
    assert r.returncode == 0, r.stderr
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
    e.set("psql_out", "0|1|3|0|0|0\n")
    r = e.run()
    assert r.returncode == 3 and "库里已有数据" in r.stderr and "app.users=1" in r.stderr
    assert not e.key.exists() and not e.secrets.exists()


# ---- 3. 两边都没有 ----
def test_fresh_deploy_no_volumes_generates(e: Env) -> None:
    r = e.run()
    assert r.returncode == 0, r.stderr
    k = _assert_key_file(e)
    assert "全新部署" in r.stderr
    _no_leak(r, e, k)


def test_empty_db_generates(e: Env) -> None:
    e.volume("pgdata")
    e.volume("imports")
    e.set(f"ps_{PREFIX}_pgdata", "cid123\n")
    e.set("psql_out", "0|0|0|0|0|0\n")
    r = e.run()
    assert r.returncode == 0, r.stderr
    _assert_key_file(e)
    sql = (e.state / "sql").read_text(encoding="utf-8")
    for t in ("app.users", "app.invite_codes", "app.user_data_licences", "app.import_files", "app.llm_providers"):
        assert t in sql
    assert "api_key_ciphertext IS NOT NULL" in sql
    # 评审 n2：会话强制只读（两道）
    assert sql.startswith("BEGIN READ ONLY;") and sql.rstrip().endswith("COMMIT;")
    assert "-e PGOPTIONS=-c default_transaction_read_only=on cid123" in e.calls()


def test_migrated_but_empty_db_generates(e: Env) -> None:
    # plan 升级约束①/③：“数据库为空”= app.users / invite_codes / user_data_licences 都为空（已迁移、无数据也算）
    e.volume("pgdata")
    e.set(f"ps_{PREFIX}_pgdata", "cid123\n")
    e.set("psql_out", "0|0|0|0|0|0\n")
    r = e.run()
    assert r.returncode == 0, r.stderr
    _assert_key_file(e)


@pytest.mark.parametrize("out,needle", [
    ("0|1|0|0|0|0", "app.users=1"),
    ("0|0|2|0|0|0", "app.invite_codes=2"),
    ("0|0|0|1|0|0", "app.user_data_licences=1"),
    ("0|0|0|0|4|0", "app.import_files=4"),                  # 保守项（plan 未列）
    ("0|0|0|0|0|1", "app.llm_providers 密文=1"),            # 评审 75c233b n1：系统级密文，users 为空也可能有
])
def test_db_with_data_refused(e: Env, out: str, needle: str) -> None:
    e.volume("pgdata")
    e.set(f"ps_{PREFIX}_pgdata", "cid123\n")
    e.set("psql_out", out + "\n")
    r = e.run()
    assert r.returncode == 3, r.stderr
    assert "拒绝启动" in r.stderr and needle in r.stderr and "从备份恢复" in r.stderr and "app-master-keygen.sh" in r.stderr
    assert not e.key.exists()


def test_pgdata_without_running_db_refused(e: Env) -> None:
    e.volume("pgdata")
    r = e.run()
    assert r.returncode == 3 and "没有运行中的 postgres" in r.stderr
    assert not e.key.exists()


@pytest.mark.parametrize("rc,out", [("2", ""), ("0", "garbage\n"), ("0", ""), ("0", "0|x|0|0|0|0\n"), ("0", "0|0|0|0|0\n")])
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


# ---- secret-env.sh：AIA_FORBID_APP_MASTER_KEY（ingest，plan e56462c）----
def _forbid(sd: Path, extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "AIA_SECRET_ENV_DIR": str(sd), "AIA_FORBID_APP_MASTER_KEY": "1", **(extra or {})}
    return subprocess.run(["sh", str(SECRET_ENV), "sh", "-c", "echo started"], capture_output=True, text=True, env=env)


def test_forbid_flag_clean_starts(tmp_path: Path) -> None:
    r = _forbid(tmp_path)
    assert r.returncode == 0 and r.stdout.strip() == "started"


def test_forbid_flag_secret_file_refused(tmp_path: Path) -> None:
    k = _key()
    (tmp_path / "app_master_key").write_text(k, encoding="utf-8")
    r = _forbid(tmp_path)
    assert r.returncode == 2 and "started" not in r.stdout and "拒绝启动" in r.stderr
    assert k not in r.stdout + r.stderr


@pytest.mark.parametrize("val", ["x" * 64, ""])
def test_forbid_flag_env_refused(tmp_path: Path, val: str) -> None:
    r = _forbid(tmp_path, {VAR: val})
    assert r.returncode == 2 and "started" not in r.stdout
    assert (val or "\0") not in r.stdout + r.stderr


# ---- compose.sh 接线 ----
COMPOSE_SH = REPO / "deploy/scripts/compose.sh"


def test_compose_sh_calls_ensure_before_docker_compose() -> None:
    text = COMPOSE_SH.read_text(encoding="utf-8")
    code = "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())
    assert "app-master-keygen.sh" not in code
    i_ensure = code.index("app-master-key-ensure.sh")
    assert code.index("DOCKER=(") < i_ensure, "ensure 要在 docker 命令确定之后（需要查库）"
    assert i_ensure < code.index("FILES=(-f"), "ensure 要在调用 docker compose 之前"
    # 强制分支：失败即中止；告警分支：检查模式
    assert re.search(r'^\s*AIA_DOCKER=[^\n]*app-master-key-ensure\.sh"[^\n]*\|\| exit \$\? ;;', code, re.M), \
        "强制子命令上 ensure 失败必须中止"
    assert re.search(r'AIA_KEYCHECK_ONLY=1 [^\n]*app-master-key-ensure\.sh"[^\n]*\|\| rc=\$\?', code)
    # M2：文件已存在时也要做④的比对，所以不得包在“文件不存在”判断里
    assert not re.search(r'if \[ ! -e "\$secrets_dir/app_master_key" \]', code)
    strict = re.search(r"^\s*([a-z|']+)\)\s*$", code[code.index('case "$sub" in'):], re.M).group(1).split("|")
    assert set(strict) >= {"up", "run", "create", "start", "restart", "''"}


def _subcmd(args: list[str]) -> str:
    text = COMPOSE_SH.read_text(encoding="utf-8")
    start = text.index("compose_subcmd() {")
    fn = text[start:text.index("\n}\n", start) + 3]
    return subprocess.run(["bash", "-c", fn + '\ncompose_subcmd "$@"', "x", *args],
                          capture_output=True, text=True).stdout


@pytest.mark.parametrize("args,want", [
    (["up", "-d", "--wait"], "up"),
    (["--profile", "maint", "run", "--rm", "maint-cli"], "run"),
    (["-p", "x", "--env-file", "/e", "-f", "a.yml", "down"], "down"),
    (["--ansi=never", "--dry-run", "ps"], "ps"),
    (["--progress", "plain", "logs", "api"], "logs"),
    ([], ""),
])
def test_compose_subcmd_parsing(args: list[str], want: str) -> None:
    assert _subcmd(args) == want


def test_keycheck_only_mode_does_not_migrate_or_generate(e: Env) -> None:
    # 评审 m2：down/ps/logs 走检查模式——不迁移、不生成、不起容器查库
    k = _key()
    e.env_file.write_text(f"{VAR}={k}\n", encoding="utf-8")
    r = e.run({"AIA_KEYCHECK_ONLY": "1"})
    assert r.returncode == 0 and "检查模式" in r.stderr
    assert not e.key.exists() and e.calls() == ""
    _no_leak(r, e, k)
    e.env_file.write_text("", encoding="utf-8")
    e.volume("pgdata")
    r = e.run({"AIA_KEYCHECK_ONLY": "1"})
    assert r.returncode == 0 and not e.key.exists()
    assert "exec" not in e.calls() and " run " not in e.calls()


def test_keycheck_only_mode_still_reports_mismatch(e: Env) -> None:
    e.secrets.mkdir()
    k, other = _key(), _key()
    e.key.write_text(k, encoding="utf-8")
    e.env_file.write_text(f"{VAR}={other}\n", encoding="utf-8")
    r = e.run({"AIA_KEYCHECK_ONLY": "1"})
    assert r.returncode == 3 and "不一致" in r.stderr     # compose.sh 把它降为告警
    assert e.key.read_text(encoding="utf-8") == k
    _no_leak(r, e, k)
    _no_leak(r, e, other)
