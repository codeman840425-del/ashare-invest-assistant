#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""网关请求体上限与应用上限的一致性（T-O03；契约 v0.2.3 #22、§4 413，plan 6.1 config/imports.yaml）。

规则（以 plan 6.1 / 契约为准，7c62f59 架构师定夺）：
  1. config/imports.yaml 必须存在且是 YAML 映射；max_file_bytes、max_files_per_upload、max_request_bytes 为正整数。
     文件不存在 → 明确报错（不静默跳过）。键在顶层（plan 6.1 原样）；也接受包在 ``imports:`` 下。
  2. nginx 每一处 client_max_body_size（换算成字节）== imports.max_request_bytes（plan：“= nginx client_max_body_size 26m”，
     “max_request_bytes 须与 nginx client_max_body_size 同步修改”）。
  3. 网关上限略大于应用上限：client_max_body_size > max_file_bytes × max_files_per_upload（plan：“必须 >”，否则 api 启动失败）；
     余量 = 二者之差，按 plan 当前取值为 1 MiB（容纳 multipart 开销），评审未另定余量，因此由规则 2 的等式锁定。
  4. nginx 413 JSON 信封（@payload_too_large）里的 max_bytes == client_max_body_size 字节数（契约 §4：{max_bytes} = max_request_bytes）。
限流（T-O10，契约 §1.3/§2 429 RATE_LIMITED + Retry-After；plan“全局 Nginx limit_req + 应用层”）：
  5. deploy/nginx/limits.conf（生产）与 limits.dev.conf（dev）都定义 zone aia_api / aia_auth / aia_import，
     键为 $binary_remote_addr（aia_import 用 $aia_import_key，nginx.conf 的 map 中 default 必须是 $binary_remote_addr、GET/HEAD 为空）；
     dev 速率不低于生产；$aia_retry_after_s 各分支 = ceil(1/速率) 秒；dev 必须 limit_req_dry_run on（只记日志），生产不得 dry run。
  6. nginx.conf：include /etc/nginx/aia-limits.conf、limit_req_status 429；location /api/ 有 aia_api；登录/注册 location 有 aia_auth；
     = /api/v1/imports 有 aia_import；error_page 429 @rate_limited，信封含 RATE_LIMITED、details.retry_after_s、Retry-After、X-Request-Id。
  7. compose：基础文件把 limits.conf 挂到 /etc/nginx/aia-limits.conf，dev 叠加文件改挂 limits.dev.conf。
上游动态解析（T-O13；api 容器重建换 IP 后静态 upstream 一直连旧地址 → 502）：
  8. nginx.conf：resolver 127.0.0.11（Docker DNS），valid ≤ 30s；不得再有 upstream 块；
     map $host $aia_api_upstream 的 default 为 "api:8000"；每一处 proxy_pass 都是 http://$aia_api_upstream，
     不带 URI（原样转发）或带 URI 时以 $is_args$args 结尾（变量形式不会自动追加参数）。
  9. compose：基础文件 nginx 健康检查经 nginx 探上游 /health/live（不是自答的 /healthz）；dev 叠加文件不得覆盖 healthcheck。
     基础文件 nginx 的 dns 必须且只能是 127.0.0.1（断开外部 DNS：上游停机时未知名字不会被宿主 DNS 解析到外部地址）；
     dev 叠加文件不得覆盖 dns。
     （评审 d1a148f）resolver 只能写 127.0.0.11 一个地址（多个地址 nginx 会轮询，直接查外部 DNS，绕过 dns:）；
     map $host $aia_api_upstream 每个分支都必须是内部短名 name:port（不带点、不是 IP）；
     任何 compose 文件都不得给 nginx 设 network_mode（host 网络不经内嵌 DNS，改用宿主解析）或 extends；
     !reset / !override 写法明确报错（会绕过这里的合并检查）；
     deploy/compose 下除基础与 dev 外的 compose 文件（如 docker compose 会自动加载的 docker-compose.override.yml）
     一律报错，同时按叠加文件规则检查。
请求行 / 请求头过长（T-D，T-live-0f8129b F-1；与 413 同一信封）：
  10. nginx.conf：server 级显式写且只写一条 large_client_header_buffers N SIZE；
      error_page 414 指向内部 URI location（不能是命名 location：读请求行阶段 URI 尚未解析，跳命名 location 会变 500），
      该 location 为 internal、return 414、信封含 URI_TOO_LONG、details.max_bytes == SIZE 字节、request_id、X-Request-Id 头；
      error_page 494 =400 指向的 location return 400、信封含 REQUEST_HEADER_TOO_LARGE、max_bytes == SIZE、X-Request-Id 头。
      limits*.conf 不得再写 large_client_header_buffers（prod / dev 共用 nginx.conf 的值，信封里的 max_bytes 才一致）。
用法：check_gateway_limits.py [--repo DIR]   不一致或缺文件时退出码 1，输出 ::error。
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import yaml

NGINX_CONF = "deploy/nginx/nginx.conf"
IMPORTS_YAML = "config/imports.yaml"
UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
SIZE_RE = re.compile(r"^\s*client_max_body_size\s+(\d+)([kKmMgG]?)\s*;", re.M)
ENVELOPE_RE = re.compile(r'"max_bytes"\s*:\s*(\d+)')
KEYS = ("max_file_bytes", "max_files_per_upload", "max_request_bytes")


def strip_comments(text: str) -> str:
    """去掉整行注释（nginx 的 # 注释）；指令行不带行尾注释（本仓库约定）。"""
    return re.sub(r"(?m)^\s*#.*$", "", text)


def check(repo: Path) -> list[str]:
    errors: list[str] = []
    conf_path, cfg_path = repo / NGINX_CONF, repo / IMPORTS_YAML
    if not conf_path.is_file():
        return [f"{NGINX_CONF} 不存在"]
    conf = strip_comments(conf_path.read_text(encoding="utf-8"))
    sizes = [int(n) * UNITS[u.lower()] for n, u in SIZE_RE.findall(conf)]
    if not sizes:
        errors.append(f"{NGINX_CONF}: 没有 client_max_body_size（默认 1m，不满足导入上限）")
    elif len(set(sizes)) > 1:
        errors.append(f"{NGINX_CONF}: client_max_body_size 有多个不同取值 {sorted(set(sizes))}")
    gateway = sizes[0] if sizes else None

    m = re.search(r"location\s+@payload_too_large\s*\{(.*?)\n\s*\}", conf, re.S)
    env_vals = [int(v) for v in ENVELOPE_RE.findall(m.group(1))] if m else []
    if not m:
        errors.append(f"{NGINX_CONF}: 没有 location @payload_too_large（413 JSON 信封）")
    elif not env_vals:
        errors.append(f"{NGINX_CONF}: @payload_too_large 信封里没有 max_bytes")
    elif gateway is not None and any(v != gateway for v in env_vals):
        errors.append(f"{NGINX_CONF}: 413 信封 max_bytes={env_vals} 与 client_max_body_size={gateway} 字节不一致")

    if not cfg_path.is_file():
        errors.append(f"{IMPORTS_YAML} 不存在：无法校验网关上限（plan 6.1 要求该文件；后端提交 config/imports.yaml 后本项才能通过）")
        return errors
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return errors + [f"{IMPORTS_YAML}: YAML 解析失败：{e}"]
    if isinstance(cfg, dict) and isinstance(cfg.get("imports"), dict):
        cfg = cfg["imports"]
    if not isinstance(cfg, dict):
        return errors + [f"{IMPORTS_YAML}: 顶层不是映射"]
    vals: dict[str, int] = {}
    for k in KEYS:
        v = cfg.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            errors.append(f"{IMPORTS_YAML}: imports.{k} 缺失或不是正整数（{v!r}）")
        else:
            vals[k] = v
    if len(vals) < len(KEYS) or gateway is None:
        return errors
    app_total = vals["max_file_bytes"] * vals["max_files_per_upload"]
    if gateway != vals["max_request_bytes"]:
        errors.append(f"nginx client_max_body_size={gateway} 字节 ≠ imports.max_request_bytes={vals['max_request_bytes']}"
                      f"（plan 6.1：二者同步修改）")
    if gateway <= app_total:
        errors.append(f"nginx client_max_body_size={gateway} 字节 不大于 应用上限 max_file_bytes×max_files_per_upload={app_total}"
                      f"（网关必须略大于应用上限，否则合法上传在网关就 413）")
    if vals["max_request_bytes"] <= app_total:
        errors.append(f"imports.max_request_bytes={vals['max_request_bytes']} 不大于 {app_total}（plan 6.1：否则 api 启动失败）")
    if not errors:
        print(f"OK   client_max_body_size={gateway} = imports.max_request_bytes = 413 max_bytes；"
              f"应用上限 {vals['max_file_bytes']}×{vals['max_files_per_upload']}={app_total}，余量 {gateway - app_total} 字节")
    return errors


LIMITS_PROD = "deploy/nginx/limits.conf"
LIMITS_DEV = "deploy/nginx/limits.dev.conf"
COMPOSE_BASE = "deploy/compose/docker-compose.yml"
COMPOSE_DEV = "deploy/compose/docker-compose.dev.yml"
LIMITS_TARGET = "/etc/nginx/aia-limits.conf"
ZONES = ("aia_api", "aia_auth", "aia_import")
ZONE_KEY = {"aia_api": "$binary_remote_addr", "aia_auth": "$binary_remote_addr", "aia_import": "$aia_import_key"}
ZONE_RE = re.compile(r"^\s*limit_req_zone\s+(\S+)\s+zone=(\w+):\S+\s+rate=(\d+)r/([sm])\s*;", re.M)
# $aia_retry_after_s 的 map 分支 → 对应 zone
RETRY_BRANCH = {"default": "aia_api", "~^/api/v1/auth/(login|register)$": "aia_auth", "~^/api/v1/imports$": "aia_import"}
LOCATIONS = {  # location 头 → 必须出现的 limit_req zone
    "location /api/ {": ("aia_api",),
    "location ~ ^/api/v1/auth/(login|register)$ {": ("aia_api", "aia_auth"),
    "location = /api/v1/imports {": ("aia_api", "aia_import"),
}


def _block(conf: str, head: str) -> str | None:
    i = conf.find(head)
    if i < 0:
        return None
    j = conf.find("\n    }", i)
    return conf[i:j if j > 0 else len(conf)]


def _parse_limits(text: str) -> tuple[dict[str, tuple[str, float]], dict[str, int]]:
    zones = {z: (k, int(n) / (60.0 if u == "m" else 1.0)) for k, z, n, u in ZONE_RE.findall(text)}
    m = re.search(r"map\s+\$uri\s+\$aia_retry_after_s\s*\{(.*?)\}", text, re.S)
    retry: dict[str, int] = {}
    for line in (m.group(1).splitlines() if m else []):
        mm = re.match(r'\s*"?([^"\s]+)"?\s+(\d+)\s*;', line)
        if mm:
            retry[mm.group(1)] = int(mm.group(2))
    return zones, retry


def check_rate_limits(repo: Path) -> list[str]:
    errors: list[str] = []
    parsed: dict[str, dict[str, tuple[str, float]]] = {}
    for rel in (LIMITS_PROD, LIMITS_DEV):
        f = repo / rel
        if not f.is_file():
            errors.append(f"{rel} 不存在（limit_req 参数）")
            continue
        zones, retry = _parse_limits(strip_comments(f.read_text(encoding="utf-8")))
        parsed[rel] = zones
        dry = bool(re.search(r"^\s*limit_req_dry_run\s+on\s*;", strip_comments(f.read_text(encoding="utf-8")), re.M))
        if rel == LIMITS_DEV and not dry:
            errors.append(f"{rel}: 缺少 limit_req_dry_run on;（burst 在 location 里写死，只放宽速率挡不住本机连发，dev 会误伤契约套件）")
        if rel == LIMITS_PROD and dry:
            errors.append(f"{rel}: 生产限流不得 limit_req_dry_run on（等于没有限流）")
        for z in ZONES:
            if z not in zones:
                errors.append(f"{rel}: 缺少 limit_req_zone {z}")
            elif zones[z][0] != ZONE_KEY[z]:
                errors.append(f"{rel}: zone {z} 的键是 {zones[z][0]}，应为 {ZONE_KEY[z]}（按来源地址）")
        for branch, z in RETRY_BRANCH.items():
            if z not in zones:
                continue
            want = math.ceil(1 / zones[z][1])
            if retry.get(branch) != want:
                errors.append(f"{rel}: $aia_retry_after_s 分支 {branch} = {retry.get(branch)}，应为 ceil(1/速率) = {want}（zone {z}）")
    if len(parsed) == 2:
        for z in ZONES:
            p, d = parsed[LIMITS_PROD].get(z), parsed[LIMITS_DEV].get(z)
            if p and d and d[1] < p[1]:
                errors.append(f"{LIMITS_DEV}: zone {z} 速率低于生产（dev 只能放宽）")

    conf_path = repo / NGINX_CONF
    if not conf_path.is_file():
        return errors + [f"{NGINX_CONF} 不存在"]
    conf = strip_comments(conf_path.read_text(encoding="utf-8"))
    if not re.search(r"^\s*include\s+" + re.escape(LIMITS_TARGET) + r"\s*;", conf, re.M):
        errors.append(f"{NGINX_CONF}: 没有 include {LIMITS_TARGET}")
    if not re.search(r"^\s*limit_req_status\s+429\s*;", conf, re.M):
        errors.append(f"{NGINX_CONF}: 没有 limit_req_status 429（默认 503，不符合契约 429 RATE_LIMITED）")
    m = re.search(r"map\s+\$request_method\s+\$aia_import_key\s*\{(.*?)\}", conf, re.S)
    body = m.group(1) if m else ""
    if not (re.search(r"^\s*default\s+\$binary_remote_addr\s*;", body, re.M)
            and re.search(r'^\s*GET\s+""\s*;', body, re.M) and re.search(r'^\s*HEAD\s+""\s*;', body, re.M)):
        errors.append(f"{NGINX_CONF}: map $request_method $aia_import_key 应为 GET/HEAD → \"\"、default → $binary_remote_addr")
    for head, zones in LOCATIONS.items():
        blk = _block(conf, head)
        if blk is None:
            errors.append(f"{NGINX_CONF}: 缺少 {head.rstrip(' {')}")
            continue
        for z in zones:
            if not re.search(r"^\s*limit_req\s+zone=" + z + r"\b", blk, re.M):
                errors.append(f"{NGINX_CONF}: {head.rstrip(' {')} 没有 limit_req zone={z}")
    if not re.search(r"^\s*error_page\s+429\s+@rate_limited\s*;", conf, re.M):
        errors.append(f"{NGINX_CONF}: 没有 error_page 429 @rate_limited")
    rl = _block(conf, "location @rate_limited {")
    if rl is None:
        errors.append(f"{NGINX_CONF}: 没有 location @rate_limited（429 JSON 信封）")
    else:
        for needle, why in (('"code":"RATE_LIMITED"', "错误码 RATE_LIMITED"),
                            ('"retry_after_s":$aia_retry_after_s', "details.retry_after_s"),
                            ('"request_id":"$aia_request_id"', "request_id"),
                            ("add_header Retry-After $aia_retry_after_s always;", "Retry-After 头"),
                            ("add_header X-Request-Id $aia_request_id always;", "X-Request-Id 头"),
                            ("return 429 ", "状态 429")):
            if needle not in rl:
                errors.append(f"{NGINX_CONF}: @rate_limited 缺少{why}（{needle}）")

    for rel, src in ((COMPOSE_BASE, "../nginx/limits.conf"), (COMPOSE_DEV, "../nginx/limits.dev.conf")):
        f = repo / rel
        if not f.is_file():
            errors.append(f"{rel} 不存在")
            continue
        doc, err = load_compose(repo, rel)
        if err:
            errors.append(err)
            continue
        vols = (((doc.get("services") or {}).get("nginx") or {}).get("volumes")) or []
        if f"{src}:{LIMITS_TARGET}:ro" not in vols:
            errors.append(f"{rel}: nginx 没有挂载 {src}:{LIMITS_TARGET}:ro")
    if not errors:
        p = parsed.get(LIMITS_PROD, {})
        print("OK   limit_req：" + "，".join(f"{z}={p[z][1]:g}r/s" for z in ZONES if z in p) + "；429 RATE_LIMITED 信封 + Retry-After")
    return errors


RESOLVER_RE = re.compile(r"^\s*resolver\s+([^;]*);", re.M)
PROXY_PASS_RE = re.compile(r"^\s*proxy_pass\s+(\S+)\s*;", re.M)
UPSTREAM_VAR = "$aia_api_upstream"
UPSTREAM_HOST = "api:8000"
NGINX_DNS = "127.0.0.1"


COMPOSE_DIR = "deploy/compose"
SHORT_UPSTREAM_RE = re.compile(r"^[a-z][a-z0-9_-]*:\d+$")


class _ComposeLoader(yaml.SafeLoader):
    """safe_load + 把 compose 的 !reset / !override 标签变成明确的报错（而不是 ConstructorError 崩溃）。"""


def _tag_refused(loader: yaml.SafeLoader, suffix: str, node: yaml.Node):  # noqa: ARG001
    raise _TagRefused(f"!{suffix}", node.start_mark.line + 1)


class _TagRefused(Exception):
    def __init__(self, tag: str, line: int) -> None:
        super().__init__(tag, line)
        self.tag, self.line = tag, line


_ComposeLoader.add_multi_constructor("!", _tag_refused)


def load_compose(repo: Path, rel: str) -> tuple[dict | None, str | None]:
    """读 compose 文件：返回 (文档, None) 或 (None, 明确的错误)。"""
    try:
        doc = yaml.load((repo / rel).read_text(encoding="utf-8"), Loader=_ComposeLoader)  # noqa: S506（SafeLoader 子类）
    except _TagRefused as e:
        return None, (f"{rel}: 第 {e.line} 行用了 {e.tag}——compose 的 !reset/!override 会整体替换合并结果、"
                      f"绕过本检查（如清空 nginx 的 dns），不允许；请直接改基础文件")
    except yaml.YAMLError as e:
        return None, f"{rel}: YAML 解析失败：{e}"
    if doc is None:
        doc = {}
    if not isinstance(doc, dict):
        return None, f"{rel}: 顶层不是映射"
    return doc, None


def extra_compose_files(repo: Path) -> list[str]:
    d = repo / COMPOSE_DIR
    if not d.is_dir():
        return []
    known = {Path(COMPOSE_BASE).name, Path(COMPOSE_DEV).name}
    return sorted(f"{COMPOSE_DIR}/{f.name}" for f in d.iterdir()
                  if f.is_file() and f.suffix in (".yml", ".yaml") and f.name not in known)


def check_dynamic_upstream(repo: Path) -> list[str]:
    errors: list[str] = []
    f = repo / NGINX_CONF
    if not f.is_file():
        return [f"{NGINX_CONF} 不存在"]
    conf = strip_comments(f.read_text(encoding="utf-8"))
    rs = RESOLVER_RE.findall(conf)
    if len(rs) != 1:
        errors.append(f"{NGINX_CONF}: 需要且只能有一条 resolver（Docker DNS 127.0.0.11），实际 {len(rs)} 条")
    else:
        parts = rs[0].split()
        addrs = [p for p in parts if "=" not in p]
        if addrs != ["127.0.0.11"]:
            errors.append(f"{NGINX_CONF}: resolver 只能写 Docker DNS 127.0.0.11 一个地址（多个地址 nginx 会轮询，"
                          f"直接查外部 DNS、绕过 dns:；实际：{rs[0].strip()}）")
        valid = [p for p in parts if p.startswith("valid=")]
        m = re.fullmatch(r"valid=(\d+)(s?)", valid[0]) if valid else None
        if not m or int(m.group(1)) > 30:
            errors.append(f"{NGINX_CONF}: resolver 需要 valid=≤30s 的短缓存（实际：{rs[0].strip()}）")
    if re.search(r"^\s*upstream\s+\S+\s*\{", conf, re.M):
        errors.append(f"{NGINX_CONF}: 不得再用静态 upstream 块（只在启动时解析一次，api 换 IP 后 502）")
    m = re.search(r"map\s+\$host\s+" + re.escape(UPSTREAM_VAR) + r"\s*\{(.*?)\}", conf, re.S)
    if not m or not re.search(r'^\s*default\s+"?' + re.escape(UPSTREAM_HOST) + r'"?\s*;', m.group(1), re.M):
        errors.append(f'{NGINX_CONF}: 缺少 map $host {UPSTREAM_VAR} {{ default "{UPSTREAM_HOST}"; }}（不能用 set：@nginx_405 里会是空值）')
    for line in (m.group(1).splitlines() if m else []):
        mm = re.match(r'\s*("[^"]*"|\S+)\s+("[^"]*"|\S+?)\s*;\s*$', line)
        if not line.strip():
            continue
        val = mm.group(2).strip('"') if mm else None
        if val is None or not SHORT_UPSTREAM_RE.match(val):
            errors.append(f"{NGINX_CONF}: map {UPSTREAM_VAR} 的分支只能指向内部短名 name:port（不带点、不是 IP；"
                          f"否则会经外部 DNS 解析或直连外部；实际：{line.strip()}）")
    targets = PROXY_PASS_RE.findall(conf)
    if not targets:
        errors.append(f"{NGINX_CONF}: 没有 proxy_pass")
    prefix = "http://" + UPSTREAM_VAR
    for t in targets:
        if not t.startswith(prefix):
            errors.append(f"{NGINX_CONF}: proxy_pass {t} 不是 {prefix}（静态主机名不会重新解析）")
        elif t != prefix and not t.endswith("$is_args$args"):
            errors.append(f"{NGINX_CONF}: proxy_pass {t} 带 URI 但没有 $is_args$args（变量形式不会自动追加查询参数）")

    extras = extra_compose_files(repo)
    for rel in extras:
        errors.append(f"{rel}: {COMPOSE_DIR} 下只允许 {Path(COMPOSE_BASE).name} 和 {Path(COMPOSE_DEV).name}"
                      f"（在该目录直接跑 docker compose 会自动加载 docker-compose.override.yml 等文件，绕过 compose.sh）")
    for rel in (COMPOSE_BASE, COMPOSE_DEV, *extras):
        cf = repo / rel
        if not cf.is_file():
            errors.append(f"{rel} 不存在")
            continue
        doc, err = load_compose(repo, rel)
        if err:
            errors.append(err)
            continue
        nginx = (doc.get("services") or {}).get("nginx") or {}
        if not isinstance(nginx, dict):
            nginx = {}
        hc = nginx.get("healthcheck")
        dns = nginx.get("dns")
        if "network_mode" in nginx:
            errors.append(f"{rel}: nginx 不得设 network_mode（实际：{nginx['network_mode']!r}；host 等模式不经 Docker 内嵌 DNS，"
                          f"改用宿主解析，dns: 断开外部 DNS 失效）")
        if "extends" in nginx:
            errors.append(f"{rel}: nginx 不得用 extends（继承来的 dns/network_mode/healthcheck 绕过本检查）")
        if rel != COMPOSE_BASE:
            what = "dev 叠加文件" if rel == COMPOSE_DEV else "叠加文件"
            if hc is not None:
                errors.append(f"{rel}: {what}不得覆盖 nginx healthcheck（应与基础文件一致探上游 /health/live）")
            if dns is not None:
                errors.append(f"{rel}: {what}不得覆盖 nginx dns（基础文件断开外部 DNS）")
            continue
        dns_list = [dns] if isinstance(dns, str) else dns
        if dns_list != [NGINX_DNS]:
            errors.append(f"{rel}: nginx 必须设 dns: [{NGINX_DNS}]（断开外部 DNS；否则上游停机时未知名字会被宿主 DNS 解析到外部地址，"
                          f"请求带着 Cookie 出本机）（实际：{dns!r}）")
        test = " ".join(hc.get("test") or []) if isinstance(hc, dict) and isinstance(hc.get("test"), list) else str((hc or {}).get("test", ""))
        if "http://127.0.0.1/health/live" not in test:
            errors.append(f"{rel}: nginx healthcheck 必须经 nginx 探上游 http://127.0.0.1/health/live（实际：{test or '无'}）")
    if not errors:
        print(f"OK   上游动态解析：resolver 127.0.0.11，{len(targets)} 处 proxy_pass 全部经 {UPSTREAM_VAR}；nginx 健康检查探上游 /health/live；外部 DNS 已断开")
    return errors


LCHB_RE = re.compile(r"^\s*large_client_header_buffers\s+(\d+)\s+(\d+)([kKmM]?)\s*;", re.M)
LCHB_ANY_RE = re.compile(r"^\s*large_client_header_buffers\b", re.M)


def _location_body(conf: str, name: str) -> str | None:
    """`location = /x {` 或 `location @x {` 的内容：到第一个只含 `}` 的行（信封 JSON 里有 `}`；这些 location 没有嵌套块）。"""
    head = f"location = {name} {{" if name.startswith("/") else f"location {name} {{"
    i = conf.find(head)
    if i < 0:
        return None
    m = re.compile(r"^\s*}\s*$", re.M).search(conf, i + len(head))
    return conf[i + len(head):m.start() if m else len(conf)]


def _check_envelope(body: str, what: str, status: int, code: str, size: int) -> list[str]:
    errs = []
    for needle, why in ((f"return {status} ", f"状态 {status}"), (f'"code":"{code}"', f"code {code}"),
                        ('"request_id":"$aia_request_id"', "request_id"), ("add_header X-Request-Id $aia_request_id always", "X-Request-Id 头"),
                        ("application/json", "JSON Content-Type")):
        if needle not in body:
            errs.append(f"{NGINX_CONF}: {what} 缺少{why}（{needle}）")
    vals = {int(v) for v in ENVELOPE_RE.findall(body)}
    if vals != {size}:
        errs.append(f"{NGINX_CONF}: {what} 信封 max_bytes={sorted(vals) or '无'} 与 large_client_header_buffers 单个缓冲 {size} 字节不一致")
    return errs


def check_header_limits(repo: Path) -> list[str]:
    errors: list[str] = []
    nc = repo / NGINX_CONF
    if not nc.is_file():
        return [f"{NGINX_CONF} 不存在"]
    conf = strip_comments(nc.read_text(encoding="utf-8"))
    found = LCHB_RE.findall(conf)
    if len(found) != 1 or len(LCHB_ANY_RE.findall(conf)) != 1:
        errors.append(f"{NGINX_CONF}: 需要且只能有一条 large_client_header_buffers N SIZE;（实际 {len(LCHB_ANY_RE.findall(conf))} 条）")
        size = None
    else:
        size = int(found[0][1]) * UNITS[found[0][2].lower()]
    for rel in (LIMITS_PROD, LIMITS_DEV):
        lf = repo / rel
        if lf.is_file() and LCHB_ANY_RE.search(strip_comments(lf.read_text(encoding="utf-8"))):
            errors.append(f"{rel}: 不得设置 large_client_header_buffers（prod/dev 共用 nginx.conf 的值）")

    m414 = re.findall(r"^\s*error_page\s+414\s+(\S+)\s*;", conf, re.M)
    if len(m414) != 1:
        errors.append(f"{NGINX_CONF}: 需要且只能有一条 error_page 414 <内部 URI>（实际 {len(m414)} 条）")
    elif m414[0].startswith("@"):
        errors.append(f"{NGINX_CONF}: error_page 414 不能指向命名 location {m414[0]}（URI 尚未解析，nginx 报 empty URI 并返回 500）；改用 internal 的 URI location")
    elif not m414[0].startswith("/"):
        errors.append(f"{NGINX_CONF}: error_page 414 目标 {m414[0]} 不是本机内部 URI")
    else:
        body = _location_body(conf, m414[0])
        if body is None:
            errors.append(f"{NGINX_CONF}: 没有 location = {m414[0]}（414 JSON 信封）")
        else:
            if not re.search(r"^\s*internal\s*;", body, re.M):
                errors.append(f"{NGINX_CONF}: location = {m414[0]} 必须 internal（外部不可直接访问）")
            if size is not None:
                errors += _check_envelope(body, f"414 location {m414[0]}", 414, "URI_TOO_LONG", size)

    m494 = re.findall(r"^\s*error_page\s+494\s+=400\s+(\S+)\s*;", conf, re.M)
    if len(m494) != 1:
        errors.append(f"{NGINX_CONF}: 需要且只能有一条 error_page 494 =400 <location>（请求头过大对外 400 + JSON 信封）")
    else:
        body = _location_body(conf, m494[0])
        if body is None:
            errors.append(f"{NGINX_CONF}: 没有 location {m494[0]}（494→400 JSON 信封）")
        elif size is not None:
            errors += _check_envelope(body, f"494 location {m494[0]}", 400, "REQUEST_HEADER_TOO_LARGE", size)
    if not errors:
        print(f"OK   请求行/请求头上限 large_client_header_buffers 单个 {size} 字节 = 414/400 信封 max_bytes；414 走 internal URI location")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    errors = check(repo) + check_rate_limits(repo) + check_dynamic_upstream(repo) + check_header_limits(repo)
    for e in errors:
        print(f"::error title=gateway-limits::{e}")
    print(f"check_gateway_limits: {len(errors)} 个问题")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
