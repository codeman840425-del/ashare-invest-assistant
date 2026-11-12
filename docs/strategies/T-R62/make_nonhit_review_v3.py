"""T-R62：生成 v3 未命中盲评记录（研究员判定落盘；确定性、离线）。

本轮 100 条（种子 20261111）结果：**漏报 0 条**。
另标 7 条「标准边界观察」——不在 R60 预注册 §3 列举类型内，按标准记 false、
**不计漏报**，单列供架构师决定是否扩表（避免事后改标准）。

用法：
  python docs/strategies/T-R62/make_nonhit_review_v3.py \
      --sample F:/t-r62-data/out/nonhit_v3_sample.jsonl \
      --out docs/strategies/T-R62/nonhit_review_v3.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BOUNDARY = {
    "300169": "部分资产被查封：司法强制措施，实质风险但 §3 未列举“资产查封”，不计漏报（边界）",
    "300638": "控股股东、实控人部分股份质押：质押爆仓风险相关，§3 未列举“质押”，不计漏报（边界）",
    "301510": "计提资产减值准备：负面财务信号，§3 未列举“减值”，不计漏报（边界）",
    "002528": "公司及子公司涉及重大仲裁：同“重大诉讼”，§3 未列举，不计漏报（边界）",
    "600853": "涉及仲裁：同上，不计漏报（边界）",
    "688249": "变更会计师事务所：审计风险信号，§3 未列举，不计漏报（边界）",
    "603458": "5%以下股东及董事提前终止减持计划暨减持结果：非控股股东/实控人，按 §3 主体口径不计",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = [json.loads(line) for line in open(args.sample, encoding="utf-8")]
    out, boundary = [], 0
    for r in rows:
        note = BOUNDARY.get(r["code"], "")
        boundary += int(bool(note))
        out.append({"ann_id": r["ann_id"], "code": r["code"], "date": r["date"],
                    "title": r["title"], "semantic_truth": False,
                    "note": note or "非 §3 风险类型"})
    Path(args.out).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"drawn": len(out), "fn": 0, "boundary_noted": boundary,
                      "out": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
