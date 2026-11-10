"""T-R60 交付自检：词表导出与 N-01 规格的一致性（确定性、离线、无网络）。

检查项（任一失败即非零退出）：
  1. 父词表与匹配器 sha256 等于冻结记录（词表未被静默改动）；
  2. `f23_lexicon_export.yaml` 与父词表逐类一致（关键词、否定词、政策规则）；
  3. 导出具备 `event_definitions` 所需六个顶层字段（key/version_no/source_rule/
     direction/severity/dedup_window），且 direction=buy、severity=veto；
  4. N-01 规格文档**不含** `strategy-card` 代码块（系统组件不得写成策略卡）；
  5. N-01 规格含关键口径串（规则式、缺失原因码、解除条件、counter 行为）；
  6. 规格验收样例 ≥6 条；抽样方案含 4 个待裁定项与漏报判定线。

只用标准库 + PyYAML。不读取任何公告样本、不访问网络、不写库。

用法：
  python docs/strategies/T-R60/check_n01_spec.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARENT = ROOT / "docs/strategies/T-R23/f23_lexicon_v2_1.yaml"
MATCHER = ROOT / "docs/strategies/T-R23/match_f23_v2_1.py"
EXPORT = HERE / "f23_lexicon_export.yaml"
SPEC = HERE / "N-01_veto_risk_announcement.md"
PLAN = HERE / "sampling_plan.md"

PARENT_SHA = "15bc3fed1327367d5813202a0cbb5d755aed0560579359cc649058f4f7693a1c"
MATCHER_SHA = "68f4a533e6418e0eda06fd8006ef04cbd212e01cadddde1c08783a0320dfcbc0"

META_FIELDS = ("key", "version_no", "source_rule", "direction", "severity", "dedup_window")

SPEC_STRINGS = (
    "f.ann_risk_count_10d > 0",          # 唯一规则
    "KEY_DATA_MISSING",                  # 缺失原因码
    "verified_live",                     # 解除条件②
    "counter",                           # 持有中行为
    "engine_policy.system_components",   # 挂载方式
    "不经导入器",                         # 非策略卡
)

PLAN_STRINGS = ("漏报", "误报", "Wilson", "Q-1", "Q-2", "Q-3", "Q-4")

errors: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    import yaml

    # 1. 冻结哈希
    check(sha(PARENT) == PARENT_SHA, "父词表 sha256 被改动")
    check(sha(MATCHER) == MATCHER_SHA, "匹配器 sha256 被改动")

    parent = yaml.safe_load(PARENT.read_text(encoding="utf-8"))
    export = yaml.safe_load(EXPORT.read_text(encoding="utf-8"))

    # 2. 导出与父词表逐类一致
    rule = export.get("source_rule", {})
    check(export.get("lexicon_version") == parent["version"], "导出词表版本不一致")
    check(export.get("parent_sha256") == PARENT_SHA, "导出未记录父哈希")
    check(export.get("matcher_sha256") == MATCHER_SHA, "导出未记录匹配器哈希")
    for name, cat in parent["categories"].items():
        got = rule.get("categories", {}).get(name)
        check(got == cat, f"类别 {name} 与父词表不一致（增删改）")
    for key in ("policy_rules", "dedup", "window", "count_rule",
                "title_excludes", "negation_resets", "clause_split"):
        check(rule.get(key) == parent[key], f"顶层键 {key} 与父词表不一致")

    # 3. event_definitions 顶层字段
    for field in META_FIELDS:
        check(field in export, f"导出缺少 event_definitions 字段 {field}")
    check(export.get("direction") == "buy", "direction 必须为 buy（N-01 只阻断买入）")
    check(export.get("severity") == "veto", "severity 必须为 veto")
    check(export.get("dedup_window") == "10trading_days", "dedup_window 不一致")

    # 4. 规格不得是策略卡
    spec = SPEC.read_text(encoding="utf-8")
    check("```yaml strategy-card" not in spec, "N-01 规格不得包含 strategy-card 块")
    check("```yaml strategy-spec" not in spec, "N-01 规格不得包含 strategy-spec 块")

    # 5. 关键口径串
    for s in SPEC_STRINGS:
        check(s in spec, f"N-01 规格缺少关键口径：{s}")

    # 6. 验收样例数量与抽样方案要素
    fixtures = [ln for ln in spec.splitlines() if ln.startswith("| N01-E")]
    check(len(fixtures) >= 6, f"验收样例不足 6 条（当前 {len(fixtures)}）")

    plan = PLAN.read_text(encoding="utf-8")
    for s in PLAN_STRINGS:
        check(s in plan, f"抽样方案缺少：{s}")
    check("0 条" in plan, "抽样方案缺少漏报判定线（0 条）")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        return 1

    print(
        "PASS：词表导出与父词表一致（%d 类 / %d 关键词），N-01 规格非策略卡，"
        "验收样例 %d 条，抽样方案要素齐备"
        % (len(rule["categories"]), export.get("keyword_total", 0), len(fixtures))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
