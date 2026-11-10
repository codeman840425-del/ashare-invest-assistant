"""T-R42：H-01/S-01 假设结构性检查（H4/S3）。

只查字段结构是否齐全与引用是否落在卡上已有 ref：
- hypothesis.why_it_works 非空
- hypothesis.falsified_by 非空列表
- counter_evidence / invalidation 各至少一条且带 ref
- falsified_by 文本是否字面提到卡上已有的 counter/invalidation/exit ref（弱启发；非语义）

不做「假设是否正确」的语义审核。若仅结构通过，核对表初核仍可保留「缺证据」。
`--mutate <name>`（T-R43）：对卡文本做真实篡改（删 falsified_by / 删 counter_evidence 引用 /
清空 why_it_works）后走同一检查，须 exit 1 且原因指向该卡与被删字段。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CARDS = {
    "H-01": ROOT / "docs/strategies/cards/hold_risk_monitor.md",
    "S-01": ROOT / "docs/strategies/cards/st_pullback_ma.md",
}


class CheckFail(Exception):
    pass


def require(cond: object, msg: str) -> None:
    if not cond:
        raise CheckFail(msg)


def extract_yaml_card(text: str) -> str:
    m = re.search(r"^```yaml strategy-card\s*\n(.*?)^```", text, re.M | re.S)
    require(m, "strategy-card fence")
    return m.group(1)


def refs_in(block: str, section: str) -> list[str]:
    # section like counter_evidence: / invalidation: / exit: / entry:
    m = re.search(rf"^{section}:\s*\n((?:^[ \t]+.+\n)+)", block, re.M)
    if not m:
        return []
    return re.findall(r"ref:\s*([A-Za-z0-9_]+)", m.group(1))


def parse_hypothesis(block: str) -> dict:
    m = re.search(r"^hypothesis:\s*\n((?:^[ \t]+.+\n)+)", block, re.M)
    require(m, "hypothesis block")
    body = m.group(1)
    why = re.search(r"why_it_works:[ \t]*(.*)$", body, re.M)  # T-R43: \s* 曾跨行吞下一行，空值漏检
    require(why and why.group(1).strip(), "why_it_works empty")
    fb = re.findall(r"^\s+-\s+(.+)$", body, re.M)
    # falsified_by items only — skip why line; collect after falsified_by:
    fb_m = re.search(r"falsified_by:\s*\n((?:^\s+-\s+.+\n)+)", body, re.M)
    require(fb_m, "falsified_by missing")
    items = re.findall(r"^\s+-\s+(.+)$", fb_m.group(1), re.M)
    require(len(items) >= 1, "falsified_by empty")
    return {"why_it_works": why.group(1).strip(), "falsified_by": items}


def check_card(card_id: str, path: Path, text: str) -> dict:
    block = extract_yaml_card(text)
    try:
        hyp = parse_hypothesis(block)
    except CheckFail as e:
        raise CheckFail(f"{card_id} {e}") from None
    counter = refs_in(block, "counter_evidence")
    inval = refs_in(block, "invalidation")
    exit_refs = refs_in(block, "exit")
    entry_refs = refs_in(block, "entry")
    require(len(counter) >= 1, f"{card_id} counter_evidence")
    require(len(inval) >= 1, f"{card_id} invalidation")
    known = set(counter + inval + exit_refs + entry_refs)
    # weak structural: each falsified_by item is non-empty string (testable prose present)
    for i, item in enumerate(hyp["falsified_by"]):
        require(len(item.strip()) >= 8, f"{card_id} falsified_by[{i}] too short")
    return {
        "card_id": card_id,
        "path": str(path.relative_to(ROOT)),
        "why_len": len(hyp["why_it_works"]),
        "falsified_by_n": len(hyp["falsified_by"]),
        "counter_refs": counter,
        "invalidation_refs": inval,
        "exit_refs": exit_refs,
        "entry_refs": entry_refs,
        "known_refs": sorted(known),
        "structural_ok": True,
        "semantic_audited": False,
        "limit": "structural/deterministic field presence only; no judgement that hypothesis is correct",
    }


def _drop_falsified(s: str) -> str:
    return re.sub(r"(  falsified_by:\n)((?:    - .+\n)+)", "", s, count=1)


def _drop_counter_refs(s: str) -> str:
    return re.sub(r"(counter_evidence:\n)((?:  - .+\n)+)", r"counter_evidence:\n  []\n", s, count=1)


def _empty_why(s: str) -> str:
    return re.sub(r"(why_it_works:)[^\n]*", r"\1 ", s, count=1)


# name -> (card id, transform, expected failure)
MUTATIONS = {
    "h01_drop_falsified_by": ("H-01", _drop_falsified, "H-01 falsified_by missing"),
    "s01_drop_counter_refs": ("S-01", _drop_counter_refs, "S-01 counter_evidence"),
    "s01_empty_why": ("S-01", _empty_why, "S-01 why_it_works empty"),
}


def run(texts: dict) -> list[dict]:
    return [check_card(cid, CARDS[cid], texts[cid]) for cid in CARDS]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    texts = {}
    for cid, path in CARDS.items():
        if not path.is_file():
            print(json.dumps({"result": "FAIL", "reason": f"missing {path.name}"}, ensure_ascii=False))
            return 1
        texts[cid] = path.read_text(encoding="utf-8")

    def mutated(name: str) -> dict:
        cid, fn, _ = MUTATIONS[name]
        m = dict(texts)
        m[cid] = fn(m[cid])
        require(m[cid] != texts[cid], f"mutation_noop:{name}")
        return m

    if argv[:1] == ["--mutate"]:
        name = argv[1] if len(argv) > 1 else ""
        if name not in MUTATIONS:
            print(json.dumps({"error": "unknown mutation", "choices": sorted(MUTATIONS)}, ensure_ascii=False))
            return 2
        try:
            run(mutated(name))
        except CheckFail as e:
            print(json.dumps({"result": "FAIL", "mutation": name, "reason": str(e)}, ensure_ascii=False))
            return 1
        print(json.dumps({"result": "MUTATION_NOT_DETECTED", "mutation": name}, ensure_ascii=False))
        return 0
    try:
        rows = run(texts)
        for name, (_, _, tag) in MUTATIONS.items():
            m = mutated(name)
            try:
                run(m)
                reason = None
            except CheckFail as e:
                reason = str(e)
            require(reason == tag, f"mutation_not_rejected:{name}:{reason}")
    except CheckFail as e:
        print(json.dumps({"result": "FAIL", "reason": str(e)}, ensure_ascii=False))
        return 1
    out = {
        "result": "PASS",
        "checks": rows,
        "proxy_初核_recommendation": "缺证据",
        "reason": "仅结构字段/引用存在性；无可靠自动语义审核 → H4/S3 初核仍保留缺证据",
        "mutations_rejected": sorted(MUTATIONS),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
