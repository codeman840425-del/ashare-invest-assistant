"""T-R62：生成 F23 词表 v3（由 v2.1 定向修订，只改 T-A152 裁定的两处）。

原则：**只做两处定向修订，其余逐字不动**，并用脚本比对证明「除这两处外与 v2.1 完全相同」。
不手写整份 YAML，避免抄写漂移。

修订（依据 T-A152 / T-R61 B 轮实测）：
  1. FP-2（controller 否定短语 + direction）：
     在 `controller_selldown` 与 `controller_equity` 的 `negations_before` 增加
     「不通过 / 不会通过 / 不主动 / 承诺不 / 自愿不」——覆盖「承诺未来六个月**不通过**二级市场主动减持」类
     承诺公告；命中被否定后 `_controller_equity` 不再产出 `direction_down`。
  2. FP-1（insolvency 他方重整主体限定）：
     在 `insolvency` 增加 `exclude_all_of`（每组内所有词都出现才排除本条类别）：
       - [参与, 破产重整]：参与他方破产重整（投资/作为投资人）
       - [参与, 重整投资]
       - [认购, 重整投资]
     自身重整（「签署《重整投资协议》暨预重整进展」「被债权人申请重整」等）不含上述组合，保持命中。

用法：
  python docs/strategies/T-R62/make_lexicon_v3.py            # 校验并打印差异
  python docs/strategies/T-R62/make_lexicon_v3.py --write    # 写 f23_lexicon_v3.yaml
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = ROOT / "docs/strategies/T-R23/f23_lexicon_v2_1.yaml"
OUT = HERE / "f23_lexicon_v3.yaml"

CONTROLLER_NEG_ADD = ["不通过", "不会通过", "不主动", "承诺不", "自愿不"]
INSOLVENCY_EXCLUDE = [["参与", "破产重整"], ["参与", "重整投资"], ["认购", "重整投资"]]


def build(parent: dict) -> dict:
    lex = copy.deepcopy(parent)
    lex["version"] = "f23_lexicon_v3"
    lex["base_version"] = "f23_lexicon_v2_1"
    lex["revision_basis"] = "T-A152（T-R61 B 轮实测 FP-1/FP-2 定向修复；其余逐字继承 v2.1）"

    for cat in ("controller_selldown", "controller_equity"):
        negs = lex["categories"][cat].setdefault("negations_before", [])
        for token in CONTROLLER_NEG_ADD:
            if token not in negs:
                negs.append(token)

    lex["categories"]["insolvency"]["exclude_all_of"] = INSOLVENCY_EXCLUDE
    return lex


def diff_summary(parent: dict, child: dict) -> dict:
    """列出与 v2.1 的全部差异（只允许预期的三处）。"""
    changes = []
    p_cats, c_cats = parent["categories"], child["categories"]
    if set(p_cats) != set(c_cats):
        raise SystemExit(f"类别集合被改动：{set(p_cats) ^ set(c_cats)}")
    for name in p_cats:
        for key in sorted(set(p_cats[name]) | set(c_cats[name])):
            if p_cats[name].get(key) != c_cats[name].get(key):
                changes.append({"category": name, "field": key,
                                "from": p_cats[name].get(key),
                                "to": c_cats[name].get(key)})
    for key in sorted(set(parent) | set(child)):
        if key in {"categories"}:
            continue
        if parent.get(key) != child.get(key):
            changes.append({"top": key, "from": parent.get(key), "to": child.get(key)})
    return {"changes": changes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    parent = yaml.safe_load(PARENT.read_text(encoding="utf-8"))
    child = build(parent)
    summary = diff_summary(parent, child)

    expected = {
        ("controller_selldown", "negations_before"),
        ("controller_equity", "negations_before"),
        ("insolvency", "exclude_all_of"),
        ("top", "version"),
        ("top", "base_version"),
        ("top", "revision_basis"),
    }
    got = {(c.get("category") or "top", c.get("field") or c.get("top")) for c in summary["changes"]}
    if not got <= expected:
        raise SystemExit(f"出现未预期的改动：{got - expected}")

    if args.write:
        header = (
            "# F23 f.ann_risk_count_10d 风险公告标题词表 v3（T-R62；T-A152 定向修订）\n"
            "# 由 make_lexicon_v3.py 从 v2.1（docs/strategies/T-R23/f23_lexicon_v2_1.yaml）定向生成；\n"
            "# 除 controller 否定短语与 insolvency 他方重整排除外，逐字继承 v2.1。\n"
        )
        OUT.write_text(header + yaml.safe_dump(child, allow_unicode=True, sort_keys=False),
                       encoding="utf-8", newline="\n")
        print(json.dumps({"written": str(OUT), "changes": summary["changes"]},
                         ensure_ascii=False))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
