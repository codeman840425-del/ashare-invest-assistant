#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""部署配置的密钥边界检查（T-A07 §5、plan §2.1B，T-O09）。

  1. deploy/compose/、deploy/env/.env.example、deploy/scripts/、.github/ 下的文本里不出现全站麦蕊证书变量名
     （证书改为用户录入、HPKE 加密存库；部署配置不再传它）；
  2. 任何 compose 服务都不使用 env_file（避免 .env 整体注入）；
  3. 证书封装私钥只给 ingest：secret data_licence_seal_private_keys、名字以 _PRIVATE_KEY / _PRIVATE_KEYS
     结尾的环境变量、挂载源含 private_keys 的卷，都只允许出现在 ingest 服务；
  4. 基础 compose 的顶层 secrets 用 file: 定义两把封装密钥，ingest 拿到私钥+公钥，api 拿到公钥；
  5. .env.example 里没有私钥变量（私钥只走 secret 文件）。

失败退出码 1，依赖缺失退出码 2。用法：check_secret_boundary.py [--repo DIR]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("缺少 pyyaml：uv run --no-project --with pyyaml==6.0.3 python scripts/ci/check_secret_boundary.py", file=sys.stderr)
    sys.exit(2)

COMPOSE_DIR = "deploy/compose"
BASE_COMPOSE = "deploy/compose/docker-compose.yml"
ENV_EXAMPLE = "deploy/env/.env.example"
TEXT_ROOTS = ["deploy/compose", "deploy/env/.env.example", "deploy/scripts", ".github"]
# 拼接避免本文件成为 rg 命中以外的“配置引用”；扫描脚本里保留该名字是为了做比对
FORBIDDEN_NAME = "MAIRUI_" + "LICENCE"
PRIVATE_SECRET = "data_licence_seal_private_keys"
PUBLIC_SECRET = "data_licence_seal_public_keys"
PRIVATE_ENV_RE = re.compile(r"_PRIVATE_KEYS?$")
PRIVATE_OWNER = "ingest"


def _texts(repo: Path):
    for root in TEXT_ROOTS:
        p = repo / root
        files = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else []
        for f in files:
            try:
                yield f.relative_to(repo).as_posix(), f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue


def _env_keys(env) -> list[str]:
    if isinstance(env, dict):
        return [str(k) for k in env]
    if isinstance(env, list):
        return [str(x).split("=", 1)[0] for x in env]
    return []


def _secret_names(secrets) -> list[str]:
    out = []
    for s in secrets or []:
        out.append(str(s.get("source")) if isinstance(s, dict) else str(s))
    return out


def _volume_sources(vols) -> list[str]:
    out = []
    for v in vols or []:
        out.append(str(v.get("source", "")) if isinstance(v, dict) else str(v).split(":", 1)[0])
    return out


def check(repo: Path) -> list[str]:
    errs: list[str] = []
    for rel, text in _texts(repo):
        for i, line in enumerate(text.splitlines(), 1):
            if FORBIDDEN_NAME in line:
                errs.append(f"{rel}:{i}: 部署配置不得再引用全站麦蕊证书变量（T-O09）")

    compose_files = sorted((repo / COMPOSE_DIR).glob("*.y*ml"))
    if not (repo / BASE_COMPOSE).is_file():
        errs.append(f"{BASE_COMPOSE} 不存在")
    for f in compose_files:
        rel = f.relative_to(repo).as_posix()
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for name, svc in (doc.get("services") or {}).items():
            svc = svc or {}
            where = f"{rel}: 服务 {name}"
            if "env_file" in svc:
                errs.append(f"{where} 使用了 env_file（禁止整体注入 .env）")
            if name == PRIVATE_OWNER:
                continue
            for k in _env_keys(svc.get("environment")):
                if PRIVATE_ENV_RE.search(k):
                    errs.append(f"{where} 的环境变量 {k} 是私钥，只允许 {PRIVATE_OWNER}")
            if PRIVATE_SECRET in _secret_names(svc.get("secrets")):
                errs.append(f"{where} 挂了 {PRIVATE_SECRET}，只允许 {PRIVATE_OWNER}")
            for src in _volume_sources(svc.get("volumes")):
                if "private_keys" in src:
                    errs.append(f"{where} 挂载了私钥路径，只允许 {PRIVATE_OWNER}")
        for sname, sdef in (doc.get("secrets") or {}).items():
            if isinstance(sdef, dict) and "environment" in sdef:
                errs.append(f"{rel}: secret {sname} 用 environment: 定义（必须用 file:，不经环境变量）")

    base = repo / BASE_COMPOSE
    if base.is_file():
        doc = yaml.safe_load(base.read_text(encoding="utf-8")) or {}
        top = doc.get("secrets") or {}
        for s in (PRIVATE_SECRET, PUBLIC_SECRET):
            if not (isinstance(top.get(s), dict) and "file" in top[s]):
                errs.append(f"{BASE_COMPOSE}: 顶层 secrets 缺少 {s}（file:）")
        svcs = doc.get("services") or {}
        need = {PRIVATE_OWNER: {PRIVATE_SECRET, PUBLIC_SECRET}, "api": {PUBLIC_SECRET}}
        for svc, want in need.items():
            have = set(_secret_names((svcs.get(svc) or {}).get("secrets")))
            if not want <= have:
                errs.append(f"{BASE_COMPOSE}: 服务 {svc} 缺少 secrets {sorted(want - have)}")

    ex = repo / ENV_EXAMPLE
    if ex.is_file():
        for i, line in enumerate(ex.read_text(encoding="utf-8").splitlines(), 1):
            key = line.split("=", 1)[0].strip()
            if "=" in line and not line.lstrip().startswith("#") and PRIVATE_ENV_RE.search(key):
                errs.append(f"{ENV_EXAMPLE}:{i}: 私钥不得出现在 .env（只走 secret 文件）")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    errs = check(Path(ap.parse_args().repo))
    for e in errs:
        print(f"::error title=secret-boundary::{e}")
    print("secret-boundary: OK" if not errs else f"secret-boundary: {len(errs)} 处问题")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
