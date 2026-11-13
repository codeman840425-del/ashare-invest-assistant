"""T-R66b：12 只「无整理期标题证据」退市股的公告正文交叉核（带 URL）。

对 T-R65 产物 `termination_list.csv` 中 `no_period_evidence=no_title_evidence` 的股票，
逐股取「终止上市暨摘牌」公告 PDF，抽正文核对是否明示「不进入退市整理期」/交易类强制退市等，
给出裁决并保留公告 URL、PDF sha256 与命中片段。只读公开源、单线程 1.0s 间隔。

用法：
  uv run --no-project --with pypdf python docs/strategies/T-R66b/crosscheck_evidence_only.py \
      --termination data/retest-inputs/termination_list.csv \
      --per-stock-jsonl F:/t-r65-data/cninfo_stock/per_stock.jsonl \
      --out F:/t-r66b-data \
      --manifest docs/strategies/T-R66b/manifests/evidence_only_crosscheck.json
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pypdf

CST = timezone(timedelta(hours=8))
PDF_BASE = "http://static.cninfo.com.cn/"
DELAY = 1.0
WINDOW_START, WINDOW_END = "2022-01-04", "2026-08-06"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "http://www.cninfo.com.cn/"}
PATTERNS = [
    ("no_delisting_period", ("不进入退市整理期", "不进行退市整理期", "不设退市整理期", "不进入退市整理")),
    ("trade_type", ("交易类强制退市",)),
    ("market_cap_or_face", ("面值", "市值", "收盘价", "1元", "一元")),
    ("volume_or_holders", ("成交量", "股东人数")),
    ("merger_or_voluntary", ("主动终止上市", "吸收合并", "要约收购")),
    ("delisting_period_mentioned", ("进入退市整理期",)),
    ("termination", ("终止上市",)),
]


def read_csv(path: Path) -> list[dict]:
    import csv

    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def pick_announcement(announcements: list[dict]) -> dict | None:
    candidates = [a for a in announcements if "终止上市" in (a.get("title") or "")]
    if not candidates:
        return None
    return sorted(candidates, key=lambda a: a.get("time") or 0)[-1]


def extract(url: str, out_dir: Path) -> tuple[str, str, int]:
    name = url.rsplit("/", 1)[-1]
    target = out_dir / name
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as resp:
        raw = resp.read()
    target.write_bytes(raw)
    reader = pypdf.PdfReader(io.BytesIO(raw))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text, hashlib.sha256(raw).hexdigest(), len(reader.pages)


def snippets(text: str, keywords: tuple[str, ...], limit: int = 2) -> list[dict]:
    found = []
    compact = re.sub(r"\s+", "", text)
    for keyword in keywords:
        for match in re.finditer(re.escape(keyword), compact):
            start = max(0, match.start() - 45)
            found.append({"keyword": keyword, "context": compact[start : match.end() + 60]})
            if len(found) >= limit:
                return found
    return found


def verdict(matches: dict[str, list[dict]]) -> str:
    if matches["no_delisting_period"]:
        return "no_delisting_period_confirmed"
    if matches["delisting_period_mentioned"]:
        return "contradiction_delisting_period_mentioned"
    if matches["trade_type"]:
        return "trade_type_confirmed"
    if matches["merger_or_voluntary"]:
        return "merger_or_voluntary_confirmed"
    if matches["market_cap_or_face"] or matches["volume_or_holders"]:
        return "trade_type_indicator_confirmed"
    return "no_explicit_text"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--termination", required=True)
    ap.add_argument("--per-stock-jsonl", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pdf_dir = out / "pdfs"
    pdf_dir.mkdir(exist_ok=True)

    per_stock = {}
    for line in Path(args.per_stock_jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "error" in row:
            continue
        per_stock[(row["exchange"], row["symbol"])] = row.get("announcements") or []

    targets = [
        r
        for r in read_csv(Path(args.termination))
        if WINDOW_START <= r["delisting_date"] <= WINDOW_END
        and r.get("no_period_evidence") == "no_title_evidence"
    ]
    results = []
    for row in targets:
        key = (row["exchange"], row["symbol"])
        ann = pick_announcement(per_stock.get(key, []))
        record = {
            "exchange": key[0],
            "symbol": key[1],
            "name": row["name"],
            "delisting_date": row["delisting_date"],
            "title_evidence": row.get("no_period_evidence"),
            "announcement_url": PDF_BASE + ann["adjunctUrl"] if ann and ann.get("adjunctUrl") else None,
            "announcement_title": ann.get("title") if ann else None,
        }
        if not record["announcement_url"]:
            record["verdict"] = "no_termination_announcement"
            results.append(record)
            continue
        try:
            text, pdf_sha, pages = extract(record["announcement_url"], pdf_dir)
            matches = {name: snippets(text, keys) for name, keys in PATTERNS}
            record.update(
                {
                    "pdf_sha256": pdf_sha,
                    "pdf_pages": pages,
                    "text_chars": len(text),
                    "verdict": verdict(matches),
                    "matches": {name: value for name, value in matches.items() if value},
                }
            )
            if len(text.strip()) < 50:
                record["verdict"] = "text_unavailable"
        except Exception as exc:  # noqa: BLE001
            record["verdict"] = "fetch_error"
            record["error"] = type(exc).__name__
        results.append(record)
        time.sleep(DELAY)

    counts: dict[str, int] = {}
    for item in results:
        counts[item["verdict"]] = counts.get(item["verdict"], 0) + 1
    payload = {
        "task": "T-R66b",
        "source": "cninfo 终止上市暨摘牌公告 PDF 正文",
        "window": {"start": WINDOW_START, "end": WINDOW_END},
        "targets": len(targets),
        "verdict_counts": counts,
        "stocks": results,
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
    }
    manifest = Path(args.manifest)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({"targets": len(targets), "verdict_counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
