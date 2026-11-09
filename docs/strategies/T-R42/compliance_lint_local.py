"""T-R42：H-01/S-01 合规禁用词本地自查（不替代服务端 compliance_lint）。

禁用词表照录出处（不自创）：
- plan.md:3362 —「禁用"保证、必涨、稳赚、牛股、金股、目标价"等词」
- plan.md:162 —「禁用词（"保证/必涨/稳赚"等）」
- src/backend/app/strategy/reviews.py:317 — COMPLIANCE_TERMS = ("保证", "必涨", "稳赚", "牛股", "金股", "目标价")
  （实现镜像；api-contract.md:953 只写「G7 文案需通过禁用词校验」未列词表，故词表以 plan/reviews 为准）

本脚本只扫 docs/strategies 内两张卡正文+YAML；--mutate 植入禁用词后须 exit≠0。
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

# 照录 reviews.py:317 / plan.md:3362；顺序与实现一致
COMPLIANCE_TERMS = ("保证", "必涨", "稳赚", "牛股", "金股", "目标价")
SOURCES = {
    "plan.md:3362": '禁用"保证、必涨、稳赚、牛股、金股、目标价"',
    "plan.md:162": '禁用词（"保证/必涨/稳赚"等）',
    "reviews.py:317": 'COMPLIANCE_TERMS = ("保证", "必涨", "稳赚", "牛股", "金股", "目标价")',
    "api-contract.md:953": "G7 文案需通过禁用词校验（未列词表；本自查用 plan/reviews 词表）",
}

CARDS = [
    ROOT / "docs/strategies/cards/hold_risk_monitor.md",
    ROOT / "docs/strategies/cards/st_pullback_ma.md",
]


def fail(msg: object = "") -> None:
    raise AssertionError(msg)


def require(cond: object, msg: object = "") -> None:
    if not cond:
        fail(msg)


def find_terms(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text)
    return [t for t in COMPLIANCE_TERMS if t in normalized]


def scan_card(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    hits = find_terms(text)
    return {"path": str(path.relative_to(ROOT)), "hits": hits, "ok": len(hits) == 0}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mutate = "--mutate" in argv
    results = []
    for p in CARDS:
        require(p.is_file(), p)
        r = scan_card(p)
        if mutate:
            # 植入禁用词「稳赚」到扫描文本
            planted = p.read_text(encoding="utf-8") + "\n【篡改】稳赚\n"
            hits = find_terms(planted)
            require("稳赚" in hits, "planted term missing")
            fail(f"COMPLIANCE_LINT_FAILED:{hits}")
        require(r["ok"], f'COMPLIANCE_LINT_FAILED {r["path"]}:{r["hits"]}')
        results.append(r)
    out = {
        "result": "PASS",
        "scope": "local_docs_strategies_only",
        "disclaimer": "本地自查，不替代服务端 compliance_lint（api-contract.md:953）",
        "terms": list(COMPLIANCE_TERMS),
        "sources": SOURCES,
        "cards": results,
        "note": "run with --mutate to force exit≠0 under normal/-O",
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
