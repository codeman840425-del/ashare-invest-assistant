#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""compose 日志轮转检查（T-A04 ③）。

deploy/compose/ 下每个 compose 文件（基础 + dev 覆盖）：
  1. 顶层有 x-logging（YAML 锚点 &default-logging）：driver json-file，options.max-size 在 1m–100m，
     options.max-file 是 2–20 的整数（字符串形式，docker 要求）；
  2. 每个服务都写了 logging，且与本文件的 x-logging 完全一致（统一用锚点，不允许单个服务另写一套或省略）；
  3. 各文件的 x-logging 彼此一致（dev 覆盖不能改掉轮转参数）。
没有轮转的 json-file 日志会无限增长占满磁盘；local / journald 等其他驱动不在本仓库的运维约定内，一律拒绝。
compose 合并标签（!reset / !override）或 YAML 无法解析 → 明确报错（复用 check_secret_boundary 的解析器）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_secret_boundary as ccs  # noqa: E402

COMPOSE_DIR = "deploy/compose"
ANCHOR_KEY = "x-logging"
DRIVER = "json-file"
SIZE_RE = re.compile(r"^(\d+)([km])$")
MAX_SIZE_BYTES = 100 * 1024 * 1024
MIN_SIZE_BYTES = 1024 * 1024
MAX_FILE_RANGE = (2, 20)


def _size_bytes(v: str) -> int | None:
    m = SIZE_RE.match(v)
    if not m:
        return None
    return int(m.group(1)) * (1024 if m.group(2) == "k" else 1024 * 1024)


def _check_policy(where: str, lg, errs: list[str]) -> None:
    if not isinstance(lg, dict):
        errs.append(f"{where}: logging 必须是映射（driver: {DRIVER} + options）")
        return
    if lg.get("driver") != DRIVER:
        errs.append(f"{where}: logging.driver 必须是 {DRIVER}（发现 {lg.get('driver')!r}）")
    opts = lg.get("options")
    if not isinstance(opts, dict):
        errs.append(f"{where}: logging 缺少 options（max-size / max-file）")
        return
    ms = opts.get("max-size")
    b = _size_bytes(str(ms)) if isinstance(ms, str) else None
    if b is None or not (MIN_SIZE_BYTES <= b <= MAX_SIZE_BYTES):
        errs.append(f"{where}: logging.options.max-size 必须是 1m–100m 的字符串（发现 {ms!r}）")
    mf = opts.get("max-file")
    ok = isinstance(mf, str) and mf.isdigit() and MAX_FILE_RANGE[0] <= int(mf) <= MAX_FILE_RANGE[1]
    if not ok:
        errs.append(f"{where}: logging.options.max-file 必须是 {MAX_FILE_RANGE[0]}–{MAX_FILE_RANGE[1]} 的整数字符串（发现 {mf!r}）")


def check(repo: Path) -> list[str]:
    errs: list[str] = []
    files = sorted((repo / COMPOSE_DIR).glob("*.y*ml"))
    if not files:
        errs.append(f"{COMPOSE_DIR} 下没有 compose 文件")
    anchors: dict[str, object] = {}
    for f in files:
        rel = f.relative_to(repo).as_posix()
        doc = ccs._load(f, rel, errs)
        if doc is None:
            continue
        anchor = doc.get(ANCHOR_KEY)
        if anchor is None:
            errs.append(f"{rel}: 缺少顶层 {ANCHOR_KEY}（&default-logging 锚点）")
        else:
            _check_policy(f"{rel}: {ANCHOR_KEY}", anchor, errs)
            anchors[rel] = anchor
            if not re.search(r"^x-logging:\s*&default-logging\s*$", f.read_text(encoding="utf-8"), re.M):
                errs.append(f"{rel}: {ANCHOR_KEY} 必须定义为锚点 &default-logging")
        for name, svc in (doc.get("services") or {}).items():
            where = f"{rel}: 服务 {name}"
            lg = (svc or {}).get("logging")
            if lg is None:
                errs.append(f"{where} 没有配置 logging（须 logging: *default-logging）")
                continue
            if anchor is not None and lg != anchor:
                errs.append(f"{where} 的 logging 与 {ANCHOR_KEY} 不一致（须 logging: *default-logging）")
            _check_policy(where, lg, errs)
    vals = list(anchors.values())
    if any(v != vals[0] for v in vals[1:]):
        errs.append(f"{COMPOSE_DIR}: 各 compose 文件的 {ANCHOR_KEY} 不一致（覆盖文件不得改轮转参数）")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    errs = check(Path(ap.parse_args().repo))
    for e in errs:
        print(f"::error title=compose-logging::{e}")
    print("compose-logging: OK" if not errs else f"compose-logging: {len(errs)} 处问题")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
