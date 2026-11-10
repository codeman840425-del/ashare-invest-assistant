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
