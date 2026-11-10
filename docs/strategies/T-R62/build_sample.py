"""T-R61：由巨潮原始页构建样本并跑冻结匹配器（研究侧，确定性、零麦蕊）。

输入：`fetch_titles.py` 产出的 `raw/<date>/page_*.json`
输出（out 目录，不入库）：
  sample.jsonl        去重、过滤后的全量样本（含 policy_hit/categories/flags）
  nonhit_sample.jsonl 未命中里按固定种子抽的 100 条（供盲评）
  sample_stats.json   各步计数（可审计）

过滤口径（与 F23 的适用域一致，逐项计数，可审计）：
  - 只保留沪深 A 股个股：SH 600/601/603/605/688/689；SZ 000/001/002/003/300/301；
  - 剔除北交所（920/43/83/87 开头）、B 股（200/201/900）、基金/债券/权证（其他前缀）；
  - 按 announcementId 去重（同一公告多次出现只算 1 条）。

匹配器：**逐字节使用** `docs/strategies/T-R23/match_f23_v2_1.py`（sha256 断言），不复制、不改词。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MATCHER = ROOT / "docs/strategies/T-R23/match_f23_v2_1.py"
MATCHER_SHA = "68f4a533e6418e0eda06fd8006ef04cbd212e01cadddde1c08783a0320dfcbc0"

A_SHARE_PREFIX = {
    "600", "601", "603", "605", "688", "689",          # 沪
    "000", "001", "002", "003", "300", "301",          # 深
}
SEED = 20261110


def load_matcher():
    data = MATCHER.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != MATCHER_SHA:
        raise SystemExit(f"匹配器 sha256 不一致：{got}")
    spec = importlib.util.spec_from_file_location("f23_matcher", MATCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def code_of(item: dict) -> str:
    return str(item.get("secCode") or "").strip()


def keep_code(code: str) -> bool:
    return len(code) == 6 and code[:3] in A_SHARE_PREFIX


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    raw = Path(args.raw)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    matcher = load_matcher()

    stats = {"files": 0, "rows_raw": 0, "dup_ids": 0, "rows_dedup": 0,
             "non_a_share": 0, "rows_kept": 0, "per_date": {}}
    seen: dict[str, dict] = {}
    for date_dir in sorted((raw / "raw").iterdir()):
        date = date_dir.name
        day_rows = 0
        for page in sorted(date_dir.glob("page_*.json")):
            stats["files"] += 1
            payload = json.loads(page.read_text(encoding="utf-8"))
            for item in payload.get("announcements") or []:
                stats["rows_raw"] += 1
                day_rows += 1
                ann_id = str(item.get("announcementId") or "").strip()
                if not ann_id:
                    continue
                if ann_id in seen:
                    stats["dup_ids"] += 1
                    continue
                seen[ann_id] = {"date": date, "item": item}
        stats["per_date"][date] = {"rows": day_rows}
    stats["rows_dedup"] = len(seen)

    sample = []
    for ann_id, rec in seen.items():
        code = code_of(rec["item"])
        if not keep_code(code):
            stats["non_a_share"] += 1
            continue
        title = str(rec["item"].get("announcementTitle") or "")
        hit, cats, flags = matcher.match_detail(title)
        sample.append({
            "ann_id": ann_id, "code": code, "date": rec["date"],
            "title": title, "policy_hit": bool(hit),
            "categories": cats, "flags": flags,
        })
    stats["rows_kept"] = len(sample)
    stats["hits"] = sum(1 for r in sample if r["policy_hit"])
    stats["seed"] = SEED

    (out / "sample.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in sample) + "\n",
        encoding="utf-8", newline="\n")

    # 未命中里固定种子抽 100 条（盲评用；先不带命中标签输出）
    nonhit = [r for r in sample if not r["policy_hit"]]
    rng = random.Random(SEED)
    drawn = rng.sample(nonhit, min(100, len(nonhit)))
    (out / "nonhit_sample.jsonl").write_text(
        "\n".join(json.dumps({"ann_id": r["ann_id"], "code": r["code"],
                              "date": r["date"], "title": r["title"]},
                             ensure_ascii=False) for r in drawn) + "\n",
        encoding="utf-8", newline="\n")

    (out / "sample_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
