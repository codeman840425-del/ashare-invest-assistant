"""T-R62：v2.1 vs v3 在 B 轮归档样本上的对照（离线、确定性、不联网）。

用途：证明 T-A152 两处修复**只**去掉 B 轮实测的两个误报，且不误伤任何原有真命中。
输入：B 轮归档样本 `T-R61/sample_titles.jsonl`（1,490 条；在 ds/T-R61 分支）。
输出：差异清单 + 计数（stdout JSON）。

用法：
  uv run --no-project --with pyyaml==6.0.3 python docs/strategies/T-R62/compare_v21_v3.py \
      --sample ../ds-T-R61/docs/strategies/T-R61/sample_titles.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V3 = HERE / "match_f23_v3.py"
V3_SHA = "d49ccb2fdb629a75d3b470e7844a99ea658c31e2c55e340dcf88c95b21940ce4"
V21 = ROOT / "docs/strategies/T-R23/match_f23_v2_1.py"
V21_SHA = "68f4a533e6418e0eda06fd8006ef04cbd212e01cadddde1c08783a0320dfcbc0"


def load(path: Path, want: str, name: str):
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if got != want:
        raise SystemExit(f"{name} sha256 不一致：{got}")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", required=True)
    args = ap.parse_args()

    m3 = load(V3, V3_SHA, "f23v3")
    m21 = load(V21, V21_SHA, "f23v21")
    rows = [json.loads(line) for line in open(args.sample, encoding="utf-8")]

    h3 = h21 = 0
    removed, added = [], []
    for r in rows:
        a, _, _ = m21.match_detail(r["title"])
        b, _, _ = m3.match_detail(r["title"])
        h21 += int(bool(a))
        h3 += int(bool(b))
        if a and not b:
            removed.append({"code": r["code"], "title": r["title"]})
        if b and not a:
            added.append({"code": r["code"], "title": r["title"]})
    print(json.dumps({"rows": len(rows), "hits_v21": h21, "hits_v3": h3,
                      "removed": removed, "added": added}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
