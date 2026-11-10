"""T-R60：F23 词表 → `app.event_definitions` 载荷导出（研究侧，确定性、离线）。

单一真源原则：词表本体只有一份 —— `docs/strategies/T-R23/f23_lexicon_v2_1.yaml`
（旧轮冻结版，plan「T-R22 裁定」派生，sha256 由 rules_freeze_v2_1.yaml 记录）。
本脚本**只做派生导出**，不新增第二份可编辑词表：把该 YAML 转成
`event_definitions` 的 `source_rule` JSONB 形状 + 顶层 key/version_no/direction/
severity/dedup_window，供后端按 §2.5.11A ② 版本化写入。

硬约束（脚本内断言，失败即退出，不写输出）：
  1. 父文件 sha256 必须等于冻结记录中的值（防止词表被静默改动）；
  2. 导出中每个类别的 keywords 与父文件逐条相等、顺序一致、数量一致；
  3. 否定词、排除词、policy_rules、dedup、window 全部原样搬运，不增不减；
  4. 不读取任何公告样本、不联网、不写库。

用法（仓库根目录）：
  python docs/strategies/T-R60/export_lexicon.py            # 只校验并打印摘要
  python docs/strategies/T-R60/export_lexicon.py --write    # 校验并写 f23_lexicon_export.yaml
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]                      # 仓库根
PARENT = ROOT / "docs/strategies/T-R23/f23_lexicon_v2_1.yaml"
MATCHER = ROOT / "docs/strategies/T-R23/match_f23_v2_1.py"
OUT = HERE / "f23_lexicon_export.yaml"

# 冻结记录（docs/strategies/T-R23/rules_freeze_v2_1.yaml）
PARENT_SHA = "15bc3fed1327367d5813202a0cbb5d755aed0560579359cc649058f4f7693a1c"
MATCHER_SHA = "68f4a533e6418e0eda06fd8006ef04cbd212e01cadddde1c08783a0320dfcbc0"

# event_definitions 顶层字段（src/backend/app/db/tables/strategy.py:544）
EXPORT_META = {
    "key": "f23_risk_announcement",
    "version_no": 1,
    "direction": "buy",          # N-01 只阻断买入方向；持有中仅作 counter
    "severity": "veto",
    "dedup_window": "10trading_days",
}

# 原样搬运的顶层键（父文件里的机器可读配置）
PASSTHROUGH = (
    "normalize",
    "clause_split",
    "after_window",
    "negation_resets",
    "title_exclude_prefix_regex",
    "title_excludes",
    "categories",
    "policy_rules",
    "dedup",
    "window",
    "count_rule",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_yaml(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def keyword_stats(lex: dict) -> dict[str, int]:
    """每个类别的关键词数；用于导出前后逐类比对。"""
    stats = {}
    for name, cat in lex["categories"].items():
        if "keywords" in cat:
            stats[name] = len(cat["keywords"])
    return stats


def build(lex: dict) -> dict:
    stats = keyword_stats(lex)
    export = {
        "generated_by": "docs/strategies/T-R60/export_lexicon.py",
        "not_a_source": "本文件是派生导出，不是词表真源；改词表须改父文件并出新版本",
        "lexicon_version": lex["version"],
        "parent_file": "docs/strategies/T-R23/f23_lexicon_v2_1.yaml",
        "parent_sha256": PARENT_SHA,
        "matcher_file": "docs/strategies/T-R23/match_f23_v2_1.py",
        "matcher_sha256": MATCHER_SHA,
        "keyword_counts": stats,
        "keyword_total": sum(stats.values()),
        **EXPORT_META,
        "source_rule": {k: lex[k] for k in PASSTHROUGH},
    }
    return export


def validate(lex: dict, export: dict) -> None:
    """导出必须与父文件逐项一致；任何减少/改写都是错误。"""
    if sha256(PARENT) != PARENT_SHA:
        raise SystemExit("父词表 sha256 与冻结记录不一致，停止导出")
    if sha256(MATCHER) != MATCHER_SHA:
        raise SystemExit("匹配器 sha256 与冻结记录不一致，停止导出")

    stats = keyword_stats(lex)
    for name, count in stats.items():
        got = export["source_rule"]["categories"][name]["keywords"]
        want = lex["categories"][name]["keywords"]
        if got != want:
            raise SystemExit(f"类别 {name} 关键词与父文件不一致")
        if len(got) != count:
            raise SystemExit(f"类别 {name} 关键词数量不一致")
    if export["keyword_total"] != sum(stats.values()):
        raise SystemExit("关键词总数不一致")

    for key in PASSTHROUGH:
        if key not in export["source_rule"]:
            raise SystemExit(f"缺少顶层键 {key}")
    if set(export["source_rule"]) != set(PASSTHROUGH):
        raise SystemExit("顶层键集合与预期不一致")

    # categories 里每类除 keywords 外的规则字段必须原样保留
    for name, cat in lex["categories"].items():
        if export["source_rule"]["categories"][name] != cat:
            raise SystemExit(f"类别 {name} 的规则字段被改写")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="写出 f23_lexicon_export.yaml")
    args = ap.parse_args()

    lex = load_yaml(PARENT)
    export = build(lex)
    validate(lex, export)

    if args.write:
        import yaml

        header = (
            "# 由 docs/strategies/T-R60/export_lexicon.py 生成；勿手改。\n"
            "# 词表真源：docs/strategies/T-R23/f23_lexicon_v2_1.yaml（冻结 sha256 见 parent_sha256）\n"
            "# 用途：backend 写入 app.event_definitions 的 source_rule 载荷（plan 2.5.11A N-01 ②）\n"
        )
        OUT.write_text(
            header + yaml.safe_dump(export, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )
        print(json.dumps({"written": str(OUT), "sha256": sha256(OUT)}, ensure_ascii=False))
    else:
        print(
            json.dumps(
                {
                    "ok": True,
                    "lexicon_version": export["lexicon_version"],
                    "categories": len(export["source_rule"]["categories"]),
                    "policy_rules": len(export["source_rule"]["policy_rules"]),
                    "keyword_total": export["keyword_total"],
                    "keyword_counts": export["keyword_counts"],
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
