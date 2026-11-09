"""T-R31：F23 freshness 正常样 + 3 条篡改探针（离线、虚构数据）。

T-R30 探针结论（无效，非 checker 缺口）：
1) 仅改了 3 条真值中的 1 条标题，其余 2 条未篡改故仍命中 → M/N=2/3；
2) 协议匹配顺序为 id → title_eq → prefix_unique；仅改标题而保留同号 nr 时
   id 仍命中（本夹具用无数字 URL 时才走 title）。故「只改标题」在有数字 ID
   时不能充当拒绝探针。

本文件固化有效探针：每条同时破坏 announcement_id（nr 数字）与标题，
目标行必须进入 misses；三条合计 3/3 拒绝；正常样 3/3 通过。
不升级 F23（保持 declared）。
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path


def fail(msg: object = "") -> None:
    """Explicit failure that survives python -O (unlike assert)."""
    raise AssertionError(msg)


def require(cond: object, msg: object = "") -> None:
    if not cond:
        fail(msg)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from daily_check import load_truth, load_fetch, matched, prefix_unique  # noqa: E402

FIX = HERE / "fixtures"
GT = FIX / "freshness_gt.jsonl"


def evaluate(fetch_path: Path) -> tuple[int, int, list[str]]:
    gt = load_truth(GT)
    fetch = load_fetch(fetch_path)
    hit = total = 0
    misses: list[str] = []
    codes = sorted(set(gt) | set(fetch))
    for code in codes:
        f = fetch.get(code)
        gt_rows = gt.get(code, [])
        if not gt_rows:
            continue
        if f is None or not f.get("fetch_ok"):
            total += len(gt_rows)
            misses.extend(r["announcement_id"] for r in gt_rows)
            continue
        anns = f.get("announcements", [])
        for r in gt_rows:
            total += 1
            way = None
            for a in anns:
                way = matched(a, r)
                if way:
                    break
            if not way and prefix_unique(anns, r):
                way = "prefix_unique"
            if way:
                hit += 1
            else:
                misses.append(r["announcement_id"])
    return hit, total, misses


def main() -> int:
    # 对照：仅改标题、保留同号 nr → 仍 id 命中（证明 T-R30 类探针在有 ID 时无效）
    title_only = json.loads((FIX / "freshness_fetch_ok.json").read_text())
    for it in title_only["items"]:
        for a in it["announcements"]:
            if "900001" in a["nr"]:
                a["zt"] = "被篡改但同号仍应id命中"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(title_only, fh, ensure_ascii=False)
        title_only_path = Path(fh.name)
    h, t, m = evaluate(title_only_path)
    require((h, t) == (3, 3) and m == [], (h, t, m, "title-only must still id-match"))

    h, t, m = evaluate(FIX / "freshness_fetch_ok.json")
    require((h, t) == (3, 3) and m == [], (h, t, m, "normal"))

    probes = [
        ("freshness_mut_p1.json", "900001"),
        ("freshness_mut_p2.json", "900002"),
        ("freshness_mut_p3.json", "900003"),
    ]
    rejected = 0
    for name, aid in probes:
        h, t, m = evaluate(FIX / name)
        require(t == 3, (name, t))
        require(h == 2, (name, h, "exactly one miss"))
        require(aid in m and len(m) == 1, (name, m))
        rejected += 1

    out = {
        "normal_pass": "3/3",
        "mutation_probes_rejected": f"{rejected}/3",
        "title_only_with_same_id_still_hits": "3/3",
        "probe_invalid_reason_T-R30": "only_1_of_3_titles_mutated; not_checker_gap",
        "f23_status": "declared",
    }
    print(json.dumps(out, ensure_ascii=False))
    require(rejected == 3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
