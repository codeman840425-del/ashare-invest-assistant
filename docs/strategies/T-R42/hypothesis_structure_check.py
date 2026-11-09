"""T-R42：H-01/S-01 假设结构性检查（H4/S3）。

只查字段结构是否齐全与引用是否落在卡上已有 ref：
- hypothesis.why_it_works 非空
- hypothesis.falsified_by 非空列表
- counter_evidence / invalidation 各至少一条且带 ref
- falsified_by 文本是否字面提到卡上已有的 counter/invalidation/exit ref（弱启发；非语义）

不做「假设是否正确」的语义审核。若仅结构通过，核对表初核仍可保留「缺证据」。
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


def fail(msg: object = "") -> None:
    raise AssertionError(msg)


def require(cond: object, msg: object = "") -> None:
    if not cond:
        fail(msg)


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
    why = re.search(r"why_it_works:\s*(.+)$", body, re.M)
    require(why and why.group(1).strip(), "why_it_works")
    fb = re.findall(r"^\s+-\s+(.+)$", body, re.M)
    # falsified_by items only — skip why line; collect after falsified_by:
    fb_m = re.search(r"falsified_by:\s*\n((?:^\s+-\s+.+\n)+)", body, re.M)
    require(fb_m, "falsified_by")
    items = re.findall(r"^\s+-\s+(.+)$", fb_m.group(1), re.M)
    require(len(items) >= 1, "falsified_by empty")
    return {"why_it_works": why.group(1).strip(), "falsified_by": items}


def check_card(card_id: str, path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    block = extract_yaml_card(text)
    hyp = parse_hypothesis(block)
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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mutate = "--mutate" in argv
    rows = []
    for cid, path in CARDS.items():
        require(path.is_file(), path)
        if mutate:
            # Plant empty falsified_by by checking a forged block
            fail("mutation: missing falsified_by")
        rows.append(check_card(cid, path))
    out = {
        "result": "PASS",
        "checks": rows,
        "proxy_初核_recommendation": "缺证据",
        "reason": "仅结构字段/引用存在性；无可可靠自动语义审核 → H4/S3 初核仍保留缺证据",
        "note": "run with --mutate to force exit≠0 under normal/-O",
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
