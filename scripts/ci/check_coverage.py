#!/usr/bin/env python3
"""覆盖率门槛（plan.md §8.0）：领域包 domain/ importing/ signals/ advice/ llm/ 行覆盖 ≥ 90%，整体 ≥ 80%。

输入为 `coverage json` 生成的 coverage.json（文件路径相对 src/backend，如 app/domain/x.py）。
用法：check_coverage.py coverage.json [--total 80] [--package 90]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import PurePosixPath

DOMAIN_PACKAGES = ("domain", "importing", "signals", "advice", "llm")


def pct(covered: int, total: int) -> float:
    return 100.0 if total == 0 else 100.0 * covered / total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("coverage_json")
    ap.add_argument("--total", type=float, default=80.0)
    ap.add_argument("--package", type=float, default=90.0)
    args = ap.parse_args(argv)
    data = json.load(open(args.coverage_json, encoding="utf-8"))
    files = data.get("files", {})
    agg = {p: [0, 0] for p in DOMAIN_PACKAGES}
    tot = [0, 0]
    for name, info in files.items():
        s = info["summary"]
        parts = PurePosixPath(name.replace("\\", "/")).parts
        tot[0] += s["covered_lines"]
        tot[1] += s["num_statements"]
        if "app" in parts:
            i = parts.index("app")
            if len(parts) > i + 2 and parts[i + 1] in agg:
                agg[parts[i + 1]][0] += s["covered_lines"]
                agg[parts[i + 1]][1] += s["num_statements"]
    fail = False
    t = pct(*tot)
    print(f"整体行覆盖 {t:.1f}%（{tot[0]}/{tot[1]}），门槛 {args.total:.0f}%")
    if t < args.total:
        print(f"::error title=coverage::整体行覆盖 {t:.1f}% < {args.total:.0f}%")
        fail = True
    for p, (c, n) in agg.items():
        v = pct(c, n)
        note = "（无语句）" if n == 0 else ""
        print(f"app/{p}/ 行覆盖 {v:.1f}%（{c}/{n}）{note}，门槛 {args.package:.0f}%")
        if v < args.package:
            print(f"::error title=coverage::app/{p}/ 行覆盖 {v:.1f}% < {args.package:.0f}%")
            fail = True
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
