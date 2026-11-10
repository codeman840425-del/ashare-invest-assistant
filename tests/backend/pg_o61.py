"""o61-pg 临时库护栏：模板库名校验、建库前核端口归属（T-T62）。"""

from __future__ import annotations

import json
import os
import re
import subprocess

# 仅允许测试临时库/模板：tt 前缀（如 tt51_tpl、tt50_*）或 o61_tmp_*。
_SAFE_DB = re.compile(r"^(?:tt[a-z0-9_]+|o61_tmp_[a-z0-9_]+)$")
_O61_NAMES = frozenset({"o61-pg"})
DEFAULT_TEMPLATE_DB = "o61_tmp_0030"
TEMPLATE_ENV = "TT_O61_TEMPLATE_DB"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 55461
DEFAULT_USER = "postgres"


class PgOwnershipError(RuntimeError):
    """目标端口不属于 o61-pg，拒绝建库。"""


class InvalidTempDbName(ValueError):
    """临时库名格式不合法。"""


def validate_temp_db_name(name: str) -> str:
    raw = (name or "").strip()
    if not _SAFE_DB.fullmatch(raw) or len(raw) > 63:
        raise InvalidTempDbName(
            f"非法临时库名 {raw!r}：须匹配 tt* 或 o61_tmp_* 前缀，仅小写字母数字下划线，长度≤63"
        )
    if raw.startswith("pg_") or any(c in raw for c in '"\'\\;'):
        raise InvalidTempDbName(f"非法临时库名 {raw!r}")
    return raw


def template_db_name(environ: dict[str, str] | None = None) -> str:
    """源模板库：环境变量 TT_O61_TEMPLATE_DB，默认 o61_tmp_0030，经格式校验。"""
    merged = {**os.environ, **(environ or {})}
    return validate_temp_db_name(merged.get(TEMPLATE_ENV, DEFAULT_TEMPLATE_DB))


def _docker_ps() -> list[tuple[str, str]]:
    proc = subprocess.run(
        ["docker", "ps", "--no-trunc", "--format", "{{.ID}} {{.Names}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    rows = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        cid, _, name = line.partition(" ")
        rows.append((cid, name.strip()))
    return rows


def _inspect(cid: str) -> dict:
    proc = subprocess.run(
        ["docker", "inspect", cid],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    data = json.loads(proc.stdout)
    return data[0] if data else {}


def _published_host_ports(info: dict) -> set[int]:
    found: set[int] = set()
    ports = (info.get("NetworkSettings") or {}).get("Ports") or {}
    for key, bindings in ports.items():
        if not key.endswith("/tcp") or not bindings:
            continue
        for b in bindings:
            hp = (b or {}).get("HostPort")
            if hp and str(hp).isdigit():
                found.add(int(hp))
    binds = (info.get("HostConfig") or {}).get("PortBindings") or {}
    for key, bindings in binds.items():
        if not key.endswith("/tcp") or not bindings:
            continue
        for b in bindings:
            hp = (b or {}).get("HostPort")
            if hp and str(hp).isdigit():
                found.add(int(hp))
    return found


def _host_network_listens(info: dict, port: int) -> bool:
    if (info.get("HostConfig") or {}).get("NetworkMode") != "host":
        return False
    cmd = info.get("Config", {}).get("Cmd") or []
    joined = " ".join(str(x) for x in cmd)
    # postgres -c port=55461
    return f"port={port}" in joined or f"port = {port}" in joined


def lookup_tcp_owner(host: str, port: int) -> tuple[str | None, str]:
    """查 host:port 对应的运行中容器名。不打印密钥；查不到则 (None, 原因)。"""
    del host  # 本机 docker 端口归属；127.0.0.1 与 0.0.0.0 发布均计入
    matches: list[str] = []
    reasons: list[str] = []
    for cid, name in _docker_ps():
        info = _inspect(cid)
        if not info:
            continue
        pubs = _published_host_ports(info)
        if port in pubs:
            matches.append(name)
            reasons.append(f"{name}: docker 端口映射含 {port}")
        elif _host_network_listens(info, port):
            matches.append(name)
            reasons.append(f"{name}: NetworkMode=host 且 Cmd 含 port={port}")
    if len(matches) == 1:
        return matches[0], reasons[0]
    if len(matches) > 1:
        return None, "多个容器命中同一端口：" + ",".join(matches)
    return None, f"docker 未发现发布或 host 监听 {port} 的容器"


def is_o61_container(name: str | None) -> bool:
    if not name:
        return False
    return name.lstrip("/") in _O61_NAMES


def require_o61_pg(host: str | None = None, port: str | int | None = None) -> str:
    """确认目标端口属 o61-pg，否则抛 PgOwnershipError（调用方 fail/skip）。"""
    h = host or os.environ.get("PGHOST") or DEFAULT_HOST
    p = int(port if port is not None else (os.environ.get("PGPORT") or DEFAULT_PORT))
    owner, detail = lookup_tcp_owner(h, p)
    if is_o61_container(owner):
        return owner.lstrip("/")
    shown = owner or "未知"
    raise PgOwnershipError(
        f"拒绝建库：{h}:{p} 不属于 o61-pg，归属 {shown}（{detail}）。"
        "请把 PGHOST/PGPORT 指到 o61-pg，勿写到 o55/o53/o57/o60。"
    )


# ---------------------------------------------------------------------------
# T-T68：连接参数读 libpq 环境变量；本机缺省核 o61；CI 端口不误拦；禁连 o53/o55/o57/o60
# ---------------------------------------------------------------------------
# 规则：
# 1. 参数来自 PGHOST/PGPORT/PGUSER/PGPASSWORD（与 T-O67 / test_ta95 一致），
#    缺省回落 127.0.0.1:55461、用户 postgres、无密码。不把口令写进源码、不打印 DSN。
# 2. 解析结果等于本机缺省（loopback + 55461）时，必须 require_o61_pg，归属不是 o61-pg 则拒绝。
# 3. 非缺省目标（例如 CI 的 127.0.0.1:5432 或主机名 db:5432）不做 o61 归属校验，以免误拦。
# 4. 无论是否缺省，主机名或 docker 归属一旦命中 o53/o55/o57/o60，一律拒绝，且不发起连接。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_FORBIDDEN_MARK = re.compile(r"(?:^|[^a-z0-9])(o53|o55|o57|o60)(?:[^a-z0-9]|$)")


def resolve_libpq_params(
    environ: dict[str, str] | None = None,
) -> tuple[str, int, str, str | None]:
    """读取 libpq 环境变量；返回 (host, port, user, password)。password 可能为 None。"""
    env = environ if environ is not None else os.environ
    host = env.get("PGHOST") or DEFAULT_HOST
    port = int(env.get("PGPORT") or DEFAULT_PORT)
    user = env.get("PGUSER") or DEFAULT_USER
    raw_pw = env.get("PGPASSWORD")
    password = raw_pw if raw_pw else None
    return host, port, user, password


def is_local_o61_default(host: str, port: str | int) -> bool:
    return host in _LOOPBACK_HOSTS and int(port) == DEFAULT_PORT


def forbidden_pg_marker(name: str | None) -> str | None:
    if not name:
        return None
    matched = _FORBIDDEN_MARK.search(name.lower().lstrip("/"))
    return matched.group(1) if matched else None


def libpq_sqlalchemy_url(database: str, *, environ: dict[str, str] | None = None):
    """构造 SQLAlchemy URL；调用方不得打印返回值（可能含口令）。"""
    from sqlalchemy.engine import URL

    host, port, user, password = resolve_libpq_params(environ)
    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
    )


def guard_temp_pg(host: str | None = None, port: str | int | None = None) -> str | None:
    """按 T-T68 规则决定是否允许在该目标上建临时库。不建立连接。"""
    resolved_host, resolved_port, _user, _password = resolve_libpq_params()
    h = host if host is not None else resolved_host
    p = int(port if port is not None else resolved_port)
    marker = forbidden_pg_marker(h)
    if marker:
        raise PgOwnershipError(
            f"拒绝建库：目标主机命中禁连实例 {marker}（{h}:{p}）。"
            "绝不能连到 o53/o55/o57/o60。"
        )
    if is_local_o61_default(h, p):
        return require_o61_pg(h, p)
    owner, detail = lookup_tcp_owner(h, p)
    marker = forbidden_pg_marker(owner)
    if marker:
        shown = owner or "未知"
        raise PgOwnershipError(
            f"拒绝建库：{h}:{p} 归属 {shown}（{detail}），命中禁连实例 {marker}。"
            "绝不能连到 o53/o55/o57/o60。"
        )
    return owner.lstrip("/") if owner else None
