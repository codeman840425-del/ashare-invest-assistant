#!/usr/bin/env python3
"""T-O70：deploy/ 里官方 alpine:3.x 引用必须带多架构 index digest（tag@sha256:64hex）。

只认词边界上的 `alpine:3.`（例如 alpine:3.21），不把 redis:*alpine3.21 或
nginx:*alpine3.23 这类派生镜像算进去。不连网、不读密钥。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 未钉死的 alpine:3.x，或 digest 不是 64 位小写十六进制
ALPINE_TAG = re.compile(r"(?<![A-Za-z0-9._-])alpine:3\.\d+")
ALPINE_PINNED = re.compile(r"(?<![A-Za-z0-9._-])alpine:3\.\d+@sha256:[0-9a-f]{64}")
SKIP_PARTS = {".git", "node_modules", "__pycache__"}


def iter_deploy_files(repo: Path) -> list[Path]:
    root = repo / "deploy"
    out: list[Path] = []
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_PARTS for part in p.parts):
            continue
        out.append(p)
    return out


def check(repo: Path) -> list[str]:
    errs: list[str] = []
    deploy = repo / "deploy"
    if not deploy.is_dir():
        return [f"缺少 {deploy.relative_to(repo) if deploy.is_relative_to(repo) else deploy}"]
    for p in iter_deploy_files(repo):
        rel = p.relative_to(repo).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in ALPINE_TAG.finditer(line):
                frag = line[m.start() :]
                if not ALPINE_PINNED.match(line[m.start() :]):
                    token = re.match(r"alpine:3\.\d+(@sha256:[^\s\\]+)?", frag)
                    shown = token.group(0) if token else m.group(0)
                    errs.append(f"{rel}:{i}: 未钉死的 alpine 引用：{shown}")
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="检查 deploy/ 中 alpine:3.x 是否带 digest")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = ap.parse_args(argv)
    errs = check(args.repo.resolve())
    if errs:
        print("check_alpine_pin: " + "；".join(errs), file=sys.stderr)
        return 1
    print("check_alpine_pin: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
