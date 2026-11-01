#!/usr/bin/env python3
"""网关请求体上限与应用上限的一致性（T-O03；契约 v0.2.3 #22、§4 413，plan 6.1 config/imports.yaml）。

规则（以 plan 6.1 / 契约为准，7c62f59 架构师定夺）：
  1. config/imports.yaml 必须存在且是 YAML 映射；max_file_bytes、max_files_per_upload、max_request_bytes 为正整数。
     文件不存在 → 明确报错（不静默跳过）。键在顶层（plan 6.1 原样）；也接受包在 ``imports:`` 下。
  2. nginx 每一处 client_max_body_size（换算成字节）== imports.max_request_bytes（plan：“= nginx client_max_body_size 26m”，
     “max_request_bytes 须与 nginx client_max_body_size 同步修改”）。
  3. 网关上限略大于应用上限：client_max_body_size > max_file_bytes × max_files_per_upload（plan：“必须 >”，否则 api 启动失败）；
     余量 = 二者之差，按 plan 当前取值为 1 MiB（容纳 multipart 开销），评审未另定余量，因此由规则 2 的等式锁定。
  4. nginx 413 JSON 信封（@payload_too_large）里的 max_bytes == client_max_body_size 字节数（契约 §4：{max_bytes} = max_request_bytes）。
用法：check_gateway_limits.py [--repo DIR]   不一致或缺文件时退出码 1，输出 ::error。
"""

from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    args = ap.parse_args(argv)
    errors = check(args.repo.resolve())
    for e in errors:
        print(f"::error title=gateway-limits::{e}")
    print(f"check_gateway_limits: {len(errors)} 个问题")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
