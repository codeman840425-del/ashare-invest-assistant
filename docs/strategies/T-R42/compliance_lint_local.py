"""T-R42：H-01/S-01 合规禁用词本地自查（不替代服务端 compliance_lint）。

禁用词表照录出处（不自创）：
- plan.md:3362 —「禁用"保证、必涨、稳赚、牛股、金股、目标价"等词」
- plan.md:162 —「禁用词（"保证/必涨/稳赚"等）」
- src/backend/app/strategy/reviews.py:317-324 — COMPLIANCE_TERMS 与 lint()（NFKC 归一后子串匹配，
  命中抛 COMPLIANCE_LINT_FAILED，:326）；decide() 在 :351 lint(comment)、:353 approved 时 lint(card_version.fields)
  （实现镜像；api-contract.md:953 只写「G7 文案需通过禁用词校验」未列词表，故词表以 plan/reviews 为准）

本脚本只扫 docs/strategies 内两张卡全文（正文+YAML）。
`--mutate <name>`：对卡文本做真实篡改（植入禁用词/全角变体）后走同一 scan，须 exit 1 且原因含该卡与命中词。
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
    "reviews.py:317-324": 'COMPLIANCE_TERMS = (...) + def lint(text): NFKC 后子串匹配 → COMPLIANCE_LINT_FAILED',
    "reviews.py:351-353": "decide(): lint(comment)；approved 时 lint(json.dumps(card_version.fields))",
    "test_tb83b_reauth.py:246": "comment='保证' → 422 COMPLIANCE_LINT_FAILED（服务端自检用例，仅覆盖 comment 路径）",
    "api-contract.md:953": "G7 文案需通过禁用词校验（未列词表；本自查用 plan/reviews 词表）",
}

CARDS = [
    ROOT / "docs/strategies/cards/hold_risk_monitor.md",
    ROOT / "docs/strategies/cards/st_pullback_ma.md",
]


class CheckFail(Exception):
    pass


def require(cond: object, msg: str) -> None:
    if not cond:
        raise CheckFail(msg)


def find_terms(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text)
    return [t for t in COMPLIANCE_TERMS if t in normalized]


def scan_text(label: str, text: str) -> dict:
    hits = find_terms(text)
    return {"path": label, "hits": hits, "ok": len(hits) == 0}


# name -> (card index, text transform, expected failure)
MUTATIONS = {
    "h01_plant_wenzhuan": (0, lambda s: s + "\n【篡改】稳赚\n", "COMPLIANCE_LINT_FAILED docs/strategies/cards/hold_risk_monitor.md:['稳赚']"),
    "s01_plant_baozheng": (1, lambda s: s + "\n【篡改】保证\n", "COMPLIANCE_LINT_FAILED docs/strategies/cards/st_pullback_ma.md:['保证']"),
    # 康熙部首「⽬」(U+2F6C) 经 NFKC 归一为「目」→ 命中「目标价」，验证与 reviews.py:323 同样先 NFKC
    "s01_nfkc_mubiaojia": (1, lambda s: s + "\n【篡改】\u2f6c标价\n", "COMPLIANCE_LINT_FAILED docs/strategies/cards/st_pullback_ma.md:['目标价']"),
}


def run(texts: list[tuple[str, str]]) -> list[dict]:
    results = []
    for label, text in texts:
        r = scan_text(label, text)
        require(r["ok"], f'COMPLIANCE_LINT_FAILED {r["path"]}:{r["hits"]}')
        results.append(r)
    return results


def mutated(texts: list[tuple[str, str]], name: str) -> list[tuple[str, str]]:
    idx, fn, _ = MUTATIONS[name]
    out = list(texts)
    out[idx] = (out[idx][0], fn(out[idx][1]))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    texts = []
    for p in CARDS:
        if not p.is_file():
            print(json.dumps({"result": "FAIL", "reason": f"missing {p.name}"}, ensure_ascii=False))
            return 1
        texts.append((str(p.relative_to(ROOT)), p.read_text(encoding="utf-8")))
    if argv[:1] == ["--mutate"]:
        name = argv[1] if len(argv) > 1 else ""
        if name not in MUTATIONS:
            print(json.dumps({"error": "unknown mutation", "choices": sorted(MUTATIONS)}, ensure_ascii=False))
            return 2
        try:
            run(mutated(texts, name))
        except CheckFail as e:
            print(json.dumps({"result": "FAIL", "mutation": name, "reason": str(e)}, ensure_ascii=False))
            return 1
        print(json.dumps({"result": "MUTATION_NOT_DETECTED", "mutation": name}, ensure_ascii=False))
        return 0
    try:
        results = run(texts)
        for name, (_, _, tag) in MUTATIONS.items():
            try:
                run(mutated(texts, name))
                reason = None
            except CheckFail as e:
                reason = str(e)
            require(reason == tag, f"mutation_not_rejected:{name}:{reason}")
    except CheckFail as e:
        print(json.dumps({"result": "FAIL", "reason": str(e)}, ensure_ascii=False))
        return 1
    out = {
        "result": "PASS",
        "scope": "local_docs_strategies_only",
        "disclaimer": "本地自查，不替代服务端 compliance_lint（reviews.py:317-324，decide :351-353）",
        "terms": list(COMPLIANCE_TERMS),
        "sources": SOURCES,
        "cards": results,
        "mutations_rejected": sorted(MUTATIONS),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
