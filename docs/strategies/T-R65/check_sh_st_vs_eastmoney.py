"""T-R65 ②-e：沪市 ST 历史的东财 F10「曾用名链」交叉核对（旁证，不生成结论）。

东财链无日期，只做三项一致性检查：
1. 当前状态：链末段是否为 ST/*ST ↔ 产物在 2026-11-06 的 is_st；
2. 段数上限：产物在窗口内的 ST 段数不应多于链里历史上的 ST 段数（多于=凭空造出事件）；
3. 缺失提示：链里有 ST 段而产物完全无 ST（可能漏；也可能该段在 2022 年之前，按链长披露）。

用法：
  python docs/strategies/T-R65/check_sh_st_vs_eastmoney.py \
      --em F:/t-r65-data/em_cym/sh_cym.jsonl \
      --st F:/ashare-invest-assistant/data/retest-inputs/st_history_sh.csv \
      --asof 2026-11-06 --out F:/t-r65-data/em_check.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "backend"))
from retest.t_r58 import data  # noqa: E402

WINDOW_START = date(2022, 1, 1)


def is_st_name(name: str) -> bool:
    n = unicodedata.normalize("NFKC", name or "").replace(" ", "")
    while n[:1] in ("G", "S") and n[:2] not in ("ST",):
        n = n[1:]
    return n.startswith("ST") or n.startswith("*ST")


def chain_episodes(chain: str, current_name: str | None = None) -> list[str]:
    names = [x.strip() for x in (chain or "").split("->") if x.strip()]
    if current_name and current_name.strip() and current_name.strip() != "--":
        names.append(current_name.strip())
    episodes, current = [], []
    for name in names:
        if is_st_name(name):
            current.append(name)
        elif current:
            episodes.append(current[0])
            current = []
    if current:
        episodes.append(current[0])
    return episodes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--em", required=True)
    ap.add_argument("--st", required=True)
    ap.add_argument("--asof", default="2026-11-06")
    ap.add_argument("--delisting", default=None, help="终止名单 CSV（跳过退市股，链对退市股不可靠）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    asof = date.fromisoformat(args.asof)
    delisted = set()
    if args.delisting:
        delisted = {(r["exchange"], r["symbol"]) for r in csv.DictReader(Path(args.delisting).open(encoding="utf-8-sig"))}
    em = {}
    for line in Path(args.em).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "cym" in row:
            em[row["code"]] = row
    history, summary = data.load_status_history(Path(args.st), "st")

    def state_at(code: str, day: date) -> bool:
        for start, end, value in history.get(("SH", code), []):
            if start <= day and (end is None or day < end):
                return value
        return False

    current_mismatch = []
    too_many = []
    chain_has_but_built_none = []
    built_episodes_total = 0
    chain_episodes_total = 0
    per_stock = []
    for code, row in sorted(em.items()):
        if not code.startswith(("600", "601", "603", "605", "688", "689")):
            continue
        if ("SH", code) in delisted:
            continue
        chain = chain_episodes(row.get("cym") or "", row.get("current_name"))
        segs = history.get(("SH", code), [])
        built_eps = [s for s in segs if s[2] and (s[1] is None or s[1] > WINDOW_START)]
        built_now = state_at(code, asof)
        chain_now = is_st_name((row.get("current_name") or "").strip())
        built_episodes_total += len(built_eps)
        chain_episodes_total += len(chain)
        if built_now != chain_now:
            current_mismatch.append([code, row.get("current_name"), built_now, chain_now])
        if len(built_eps) > len(chain):
            too_many.append([code, len(built_eps), len(chain), chain])
        if chain and not built_eps:
            chain_has_but_built_none.append([code, len(chain), row.get("current_name")])
        per_stock.append([code, len(built_eps), len(chain)])
    report = {
        "source": "eastmoney F10 CompanySurveyAjax cym chain (no dates)",
        "stocks_checked": len(per_stock),
        "current_state_mismatch": {"count": len(current_mismatch), "sample": current_mismatch[:20]},
        "episodes_impossible": {"count": len(too_many), "sample": too_many[:20]},
        "chain_has_st_but_built_none": {
            "count": len(chain_has_but_built_none),
            "sample": chain_has_but_built_none[:20],
        },
        "totals": {"built_window_episodes": built_episodes_total, "chain_episodes_all_history": chain_episodes_total},
        "em_stocks": len(em),
        "st_summary": {k: summary.get(k) for k in ("rows", "stocks", "open_ended")} if summary else None,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({k: report[k] for k in ("stocks_checked", "totals")}, ensure_ascii=False))
    print(json.dumps({k: report[k]["count"] for k in ("current_state_mismatch", "episodes_impossible", "chain_has_st_but_built_none")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
