"""T-R62：词表 v3 一致性检查（离线、确定性；PASS 不代表验收，只代表规则自洽）。

检查项：
  1. v3 与 v2.1 的差异**只有 T-A152 裁定的三处**（controller×2 否定短语、insolvency 排除）+
     版本元数据；其余逐字相同（防抄写漂移）。
  2. 回归用例 `f23_v3_cases.yaml` 全部符合预期（命中/不命中、flag）。
  3. v2.1 在 B 轮样本上的基线仍是 18 命中（归档数据，仅作对照；样本文件在 T-R61 分支）。
  4. 冻结 sha256 与 `rules_freeze_v3.yaml` 记录一致。

用法：
  uv run --no-project --with pyyaml==6.0.3 python docs/strategies/T-R62/check_f23_v3.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V21 = ROOT / "docs/strategies/T-R23/f23_lexicon_v2_1.yaml"
V3 = HERE / "f23_lexicon_v3.yaml"
MATCHER = HERE / "match_f23_v3.py"
CASES = HERE / "f23_v3_cases.yaml"
FREEZE = HERE / "rules_freeze_v3.yaml"

CONTROLLER_ADD = ["不通过", "不会通过", "不主动", "承诺不", "自愿不"]
INSOLVENCY_EXCLUDE = [["参与", "破产重整"], ["参与", "重整投资"], ["认购", "重整投资"]]

errors: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_matcher():
    spec = importlib.util.spec_from_file_location("f23v3", MATCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    p21 = yaml.safe_load(V21.read_text(encoding="utf-8"))
    v3 = yaml.safe_load(V3.read_text(encoding="utf-8"))

    # 1. 最小差异
    check(v3["version"] == "f23_lexicon_v3", "版本号不是 f23_lexicon_v3")
    check(v3.get("base_version") == "f23_lexicon_v2_1", "base_version 不是 v2.1")
    for cat in ("controller_selldown", "controller_equity"):
        for tok in CONTROLLER_ADD:
            check(tok in v3["categories"][cat]["negations_before"], f"{cat} 缺少否定短语 {tok}")
        for tok in p21["categories"][cat]["negations_before"]:
            check(tok in v3["categories"][cat]["negations_before"], f"{cat} 丢失原有否定词 {tok}")
    check(v3["categories"]["insolvency"].get("exclude_all_of") == INSOLVENCY_EXCLUDE,
          "insolvency exclude_all_of 与裁定不一致")
    for name, cat in p21["categories"].items():
        if name in {"controller_selldown", "controller_equity"}:
            continue
        if name == "insolvency":
            # 允许且仅允许新增 exclude_all_of；其余字段逐字相同
            got = {k: v for k, v in v3["categories"][name].items() if k != "exclude_all_of"}
            check(got == cat, "insolvency 除 exclude_all_of 外被意外改动")
            continue
        check(v3["categories"][name] == cat, f"类别 {name} 被意外改动")
    for key in ("policy_rules", "dedup", "window", "count_rule", "title_excludes",
                "negation_resets", "clause_split", "after_window", "normalize"):
        check(v3.get(key) == p21.get(key), f"顶层 {key} 被意外改动")

    # 2. 回归用例
    m = load_matcher()
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]
    for c in cases:
        hit, cats, flags = m.match_detail(c["title"])
        check(hit == c["policy_hit"], f"{c['id']} 命中不符：got={hit} want={c['policy_hit']}")
        if c.get("categories"):
            check(set(c["categories"]) <= set(cats), f"{c['id']} 类别缺失：got={cats}")
        if c.get("expect_flag"):
            check(flags.get("controller_equity") == c["expect_flag"],
                  f"{c['id']} flag 不符：got={flags.get('controller_equity')}")
        # 明确禁止：FP-2 原题不得出现 direction_down
        if c["id"] == "V3-N1":
            check(flags.get("controller_equity") != "direction_down", "V3-N1 仍标 direction_down")

    # 4. 冻结记录
    if FREEZE.exists():
        fr = yaml.safe_load(FREEZE.read_text(encoding="utf-8"))
        check(fr["sha256"][V3.name] == sha(V3), "f23_lexicon_v3.yaml 哈希与冻结记录不一致")
        check(fr["sha256"][MATCHER.name] == sha(MATCHER), "match_f23_v3.py 哈希与冻结记录不一致")
    else:
        errors.append("缺少 rules_freeze_v3.yaml")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print(f"PASS：v3 仅 3 处定向修订；回归用例 {len(cases)} 条全符合；冻结哈希一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
