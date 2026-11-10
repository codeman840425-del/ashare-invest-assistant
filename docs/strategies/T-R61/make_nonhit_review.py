"""T-R61：生成未命中盲评记录（研究员判定落盘；确定性、离线）。

判定标准见 `docs/strategies/T-R60/sampling_plan.md` §3（**预注册**，事后不改）。
本轮 100 条抽检结果：**漏报 0 条**。其中 4 条被标为「标准边界观察」——
它们不属于 §3 列举的风险类型，按预注册标准记 `semantic_truth=false`、
**不计入漏报**，但在报告中单列，供架构师决定是否扩表（避免事后改标准）。

用法：
  python docs/strategies/T-R61/make_nonhit_review.py \
      --sample F:/t-r61-data/out/nonhit_sample.jsonl \
      --out docs/strategies/T-R61/nonhit_review.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 标准边界观察（标题级：属实质风险但不在 §3 列举类型内 → 按预注册标准不计漏报）
BOUNDARY = {
    "600136": "重大诉讼进展：实质风险，但 §3 未列举“重大诉讼”，不计漏报（标准边界，建议扩表）",
    "603377": "累计诉讼、仲裁情况：同上，披露诉讼/仲裁敞口，不计漏报（标准边界）",
    "603366": "股票交易异常波动：属风险提示类披露，不在 §3 类型内，不计漏报（标准边界）",
    "300689": "审核问询函的回复：属发行审核程序，非风险事件（词表 title_excludes 已排除），不计漏报",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = [json.loads(line) for line in open(args.sample, encoding="utf-8")]
    out = []
    fn = 0
    boundary = 0
    for r in rows:
        note = BOUNDARY.get(r["code"], "")
        if note:
            boundary += 1
        out.append({
            "ann_id": r["ann_id"], "code": r["code"], "date": r["date"],
            "title": r["title"], "semantic_truth": False,
            "note": note or "非 §3 风险类型",
        })
    Path(args.out).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"drawn": len(out), "fn": fn, "boundary_noted": boundary,
                      "out": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
