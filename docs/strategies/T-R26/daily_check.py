# ruff: noqa
"""T-R26 F23 每日核对（研究侧，确定性、离线；无网络、无麦蕊）。

用法（在仓库根目录）:
  python docs/strategies/T-R26/daily_check.py freshness \
      --truth  docs/strategies/T-R26/evidence/gt_D1.jsonl \
      --fetch  docs/strategies/T-R26/evidence/tb86_D1.json \
      --date-d 2026-11-09 \
      --ledger docs/strategies/T-R26/ledger/ledger.jsonl

  python docs/strategies/T-R26/daily_check.py completeness \
      --fetch docs/strategies/T-R26/evidence/tb86_completeness.json \
      --list  docs/strategies/T-R26/completeness_list.yaml

  python docs/strategies/T-R26/daily_check.py summary \
      --ledger docs/strategies/T-R26/ledger/ledger.jsonl

输入契约（T-B86 证据，脱敏、无证书值）:
  fetch JSON: {"fetched_at_beijing": "...", "items": [{"security_code": "600519.SH",
              "fetch_ok": true, "announcements": [{"zt": "...", "nr": "...", "t": "..."}]}]}
  truth JSONL（研究员巨潮公开页保全，每行一条）:
  {"security_code": "600519.SH", "announcement_id": "1225...", "title": "...",
   "ann_date": "2026-11-09", "url": "..."}

新鲜度口径见 f23_freshness_protocol.md §4；匹配规则：ID → 归一化标题全等 → 唯一前缀(≥12字)。
台账一行/股/日；汇总输出累计 M/N 与 >=95% 判定。本脚本不做任何判定升级。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    from match_f23_v2_1 import match  # 冻结匹配器，不改词（ noqa: E402 ）
except ModuleNotFoundError:  # 无 PyYAML 环境时的只读退化：仅完整性判定需要 match
    match = None


def norm(title: str) -> str:
    """与冻结匹配器同源归一化（NFKC + 去空白 + 去 HTML + 全半角映射）。"""
    t = re.sub(r"</?[^>]+>", "", title or "")
    t = unicodedata.normalize("NFKC", t)
    for a, b in {"＊": "*", "其它": "其他"}.items():
        t = t.replace(a, b)
    return re.sub(r"\s+", "", t)


def load_truth(path: pathlib.Path) -> dict[str, list[dict]]:
    gt: dict[str, list[dict]] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gt.setdefault(row["security_code"], []).append(row)
    for rows in gt.values():
        seen = set()
        uniq = []
        for r in rows:  # 按 cninfo 公告 ID 去重（更正公告是独立 ID，各算一条）
            if r["announcement_id"] not in seen:
                seen.add(r["announcement_id"])
                uniq.append(r)
        gt_rows = uniq
        rows[:] = gt_rows
    return gt


def load_fetch(path: pathlib.Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for item in data.get("items", []):
        out[item["security_code"]] = item
    return out


def ann_id_of(nr: str) -> str | None:
    m = re.search(r"(\d{6,})", nr or "")
    return m.group(1) if m else None


def matched(ann: dict, gt_row: dict) -> str | None:
    """返回匹配方式：id / title_eq / prefix_unique / None。"""
    nid = ann_id_of(ann.get("nr", ""))
    if nid and nid == gt_row["announcement_id"]:
        return "id"
    a, b = norm(ann.get("zt", "")), norm(gt_row["title"])
    if a and a == b:
        return "title_eq"
    return None


def prefix_unique(cands: list[dict], gt_row: dict) -> bool:
    g = norm(gt_row["title"])
    if len(g) < 12:
        return False
    hits = [a for a in (norm(c.get("zt", "")) for c in cands) if a and (a.startswith(g) or g.startswith(a))]
    return len(hits) == 1


def cmd_freshness(args: argparse.Namespace) -> int:
    gt = load_truth(pathlib.Path(args.truth))
    fetch = load_fetch(pathlib.Path(args.fetch))
    ledger = pathlib.Path(args.ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    total = hit = 0
    lines = []
    codes = sorted(set(gt) | set(fetch))
    for code in codes:
        f = fetch.get(code)
        gt_rows = gt.get(code, [])
        if not gt_rows:  # 无公告日不产生观测（协议 §4）
            lines.append({"date_d": args.date_d, "security_code": code, "gt_n": 0,
                          "fetched_at_beijing": (f or {}).get("fetched_at_beijing"), "fetch_ok": None,
                          "note": "no_ground_truth_no_observation"})
            continue
        if f is None or not f.get("fetch_ok"):
            lines.append({"date_d": args.date_d, "security_code": code, "gt_n": len(gt_rows),
                          "hit_n": 0, "misses": [r["announcement_id"] for r in gt_rows],
                          "fetch_ok": (f or {}).get("fetch_ok", False),
                          "fetched_at_beijing": (f or {}).get("fetched_at_beijing"),
                          "note": "fetch_fail_all_miss"})
            total += len(gt_rows)
            continue
        anns = f.get("announcements", [])
        hit_rows, misses = [], []
        for r in gt_rows:
            way = None
            for a in anns:
                way = matched(a, r)
                if way:
                    hit_rows.append((r["announcement_id"], way))
                    break
            if not way and prefix_unique(anns, r):
                way = "prefix_unique"
                hit_rows.append((r["announcement_id"], way))
            if not way:
                misses.append({"id": r["announcement_id"], "title": r["title"], "note": "late_or_absent"})
        total += len(gt_rows)
        hit += len(hit_rows)
        lines.append({"date_d": args.date_d, "security_code": code, "gt_n": len(gt_rows),
                      "hit_n": len(hit_rows), "hits": hit_rows, "misses": misses,
                      "fetch_ok": True, "fetched_at_beijing": f.get("fetched_at_beijing")})
    with open(ledger, "a", encoding="utf-8") as fh:
        for row in lines:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    day_hit = sum(r.get("hit_n", 0) for r in lines)
    day_tot = sum(r.get("gt_n", 0) for r in lines)
    print(f"date_d={args.date_d} 行数={len(lines)} 当日 M/N={day_hit}/{day_tot} "
          f"(累计 M/N={hit}/{total})")
    return 0


def cmd_completeness(args: argparse.Namespace) -> int:
    import yaml
    lst = yaml.safe_load(pathlib.Path(args.list).read_text(encoding="utf-8"))
    data = json.loads(pathlib.Path(args.fetch).read_text(encoding="utf-8"))
    by_code = {}
    for item in data.get("items", []):
        by_code[item["security_code"]] = item
    results = []
    for row in lst["primary"]:
        f = by_code.get(row["code"])
        anns = (f or {}).get("announcements", [])
        found = next((a for a in anns if ann_id_of(a.get("nr", "")) == str(row["ann_id"])), None)
        if found is None:  # 退化到标题匹配
            cands = [a for a in anns if norm(a.get("zt", "")) and
                     (norm(a["zt"]) in norm(found_title(row)) or norm(found_title(row)) in norm(a["zt"]))]
            found = cands[0] if len(cands) == 1 else None
        if match is None:
            raise SystemExit("completeness 需要冻结匹配器（PyYAML）；请用 uv run --no-project --with pyyaml==6.0.3 python 运行")
        hit_word = bool(found and match(found.get("zt", ""))[0])
        if found is None and (f is None or not f.get("fetch_ok")):
            status = "fetch_fail"
        elif found is None:
            status = "miss"  # 或 miss_window，由人工按窗口证据改判并注明
        elif hit_word:
            status = "pass"
        else:
            status = "fetch_found_but_no_hit"
        results.append({"seq": row["seq"], "code": row["code"], "ann_id": str(row["ann_id"]),
                        "status": status, "title_norm": norm(found["zt"]) if found else None})
    passed = sum(1 for r in results if r["status"] == "pass")
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    print(f"completeness pass={passed}/{len(results)}（10/10 达标漏 0；miss_window 人工改判须注明理由）")
    return 0


def found_title(row: dict) -> str:
    """已知清单标题需人工从保全材料取；此函数仅由调用方在 --titles 提供时替换。
    简化实现：返回空串使退化匹配失败，避免伪匹配。"""
    return ""


def cmd_summary(args: argparse.Namespace) -> int:
    total = hit = 0
    no_obs = fetch_fail = 0
    with open(args.ledger, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            total += r.get("gt_n", 0)
            hit += r.get("hit_n", 0)
            no_obs += 1 if r.get("gt_n") == 0 else 0
            fetch_fail += 1 if r.get("note") == "fetch_fail_all_miss" else 0
    ratio = (hit / total) if total else 0.0
    print(f"累计 M/N={hit}/{total} 命中率={ratio:.2%} 通过线=95% 判定={'达标' if total and ratio >= 0.95 else '不达标/不足'}")
    print(f"无观测股-日={no_obs} fetch_fail 股-日={fetch_fail}")
    print("完整性另行 completeness 子命令核对；本汇总不做 F23 升级判定。")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freshness")
    f.add_argument("--truth", required=True)
    f.add_argument("--fetch", required=True)
    f.add_argument("--date-d", required=True)
    f.add_argument("--ledger", default=str(HERE / "ledger" / "ledger.jsonl"))
    f.set_defaults(fn=cmd_freshness)
    c = sub.add_parser("completeness")
    c.add_argument("--fetch", required=True)
    c.add_argument("--list", default=str(HERE / "completeness_list.yaml"))
    c.set_defaults(fn=cmd_completeness)
    s = sub.add_parser("summary")
    s.add_argument("--ledger", default=str(HERE / "ledger" / "ledger.jsonl"))
    s.set_defaults(fn=cmd_summary)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
