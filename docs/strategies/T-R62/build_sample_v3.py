"""T-R62：v3 重跑样本构建（同口径、新交易日；对同一批标题同时跑 v2.1 与 v3）。

输入：fetch_titles.py 产物（raw/<date>/page_*.json）
输出：
  sample_v3.jsonl        全量样本（含 policy_hit_v3 / v21 双结果，用于对照）
  nonhit_v3_sample.jsonl v3 未命中中固定种子抽 100 条（盲评）
  sample_v3_stats.json   各步计数

口径与 T-R60 sampling_plan 一致；种子改为 20261111（与 B 轮 20261110 区分，可复现）。
两个匹配器均**按 sha256 断言**后逐字节使用，不改词、不改代码。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V3_MATCHER = HERE / "match_f23_v3.py"
V3_SHA = "67b0717ba579e3ce89fba4a3024353bf68d4e9380302531c30efd063abbd6704"
V21_MATCHER = ROOT / "docs/strategies/T-R23/match_f23_v2_1.py"
V21_SHA = "68f4a533e6418e0eda06fd8006ef04cbd212e01cadddde1c08783a0320dfcbc0"

A_SHARE_PREFIX = {"600", "601", "603", "605", "688", "689",
                  "000", "001", "002", "003", "300", "301"}
SEED = 20261111


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
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    raw, out = Path(args.raw), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    m3 = load(V3_MATCHER, V3_SHA, "f23v3")
    m21 = load(V21_MATCHER, V21_SHA, "f23v21")

    stats = {"files": 0, "rows_raw": 0, "dup_ids": 0, "non_a_share": 0,
             "rows_kept": 0, "hits_v3": 0, "hits_v21": 0,
             "v21_hit_but_v3_not": 0, "v3_hit_but_v21_not": 0,
             "per_date": {}, "seed": SEED}
    seen: dict[str, dict] = {}
    for date_dir in sorted((raw / "raw").iterdir()):
        rows = 0
        for page in sorted(date_dir.glob("page_*.json")):
            stats["files"] += 1
            payload = json.loads(page.read_text(encoding="utf-8"))
            for item in payload.get("announcements") or []:
                stats["rows_raw"] += 1
                rows += 1
                ann_id = str(item.get("announcementId") or "").strip()
                if not ann_id:
                    continue
                if ann_id in seen:
                    stats["dup_ids"] += 1
                    continue
                seen[ann_id] = {"date": date_dir.name, "item": item}
        stats["per_date"][date_dir.name] = {"rows": rows}

    sample = []
    for ann_id, rec in seen.items():
        code = str(rec["item"].get("secCode") or "").strip()
        if len(code) != 6 or code[:3] not in A_SHARE_PREFIX:
            stats["non_a_share"] += 1
            continue
        title = str(rec["item"].get("announcementTitle") or "")
        h3, c3, f3 = m3.match_detail(title)
        h21, c21, f21 = m21.match_detail(title)
        stats["hits_v3"] += int(bool(h3))
        stats["hits_v21"] += int(bool(h21))
        if h21 and not h3:
            stats["v21_hit_but_v3_not"] += 1
        if h3 and not h21:
            stats["v3_hit_but_v21_not"] += 1
        sample.append({"ann_id": ann_id, "code": code, "date": rec["date"], "title": title,
                       "policy_hit": bool(h3), "categories": c3, "flags": f3,
                       "v21_hit": bool(h21), "v21_categories": c21, "v21_flags": f21})
    stats["rows_kept"] = len(sample)

    (out / "sample_v3.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in sample) + "\n",
        encoding="utf-8", newline="\n")

    nonhit = [r for r in sample if not r["policy_hit"]]
    drawn = random.Random(SEED).sample(nonhit, min(100, len(nonhit)))
    (out / "nonhit_v3_sample.jsonl").write_text(
        "\n".join(json.dumps({"ann_id": r["ann_id"], "code": r["code"],
                              "date": r["date"], "title": r["title"]},
                             ensure_ascii=False) for r in drawn) + "\n",
        encoding="utf-8", newline="\n")
    (out / "sample_v3_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
