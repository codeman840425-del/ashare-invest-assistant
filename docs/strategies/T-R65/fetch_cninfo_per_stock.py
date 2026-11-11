"""T-R65 ②-c：巨潮「个股公告」逐股拉取（终止上市 / 退市整理期 / 风险警示证据，带 URL）。

用途：对官方终止名单里的沪深股票，逐股取 2021-01-01 以来的公告标题、日期与 PDF 链接，
用于 ①「终止上市暨摘牌」公告 URL 证据；②「进入退市整理期」首次公告日期 → 整理期起点；
③ 与关键词检索结果交叉核对。只读公开源、单线程、固定间隔。

orgId 解析：巨潮个股查询要 (code, orgId)。深市多数是 gssz0+代码，但老股有 9900… 旧式 orgId
（如 002069=gssz 9900000781），故先取 `new/data/szse_stock.json` 的映射；仍解析不到时用
`fulltextSearch/full?searchkey=<代码>` 取记录里的 orgId。沪市默认 gssh0+代码。

用法：
  uv run --no-project python docs/strategies/T-R65/fetch_cninfo_per_stock.py \
      --codes-file F:/t-r65-data/db/termination_codes.csv --out F:/t-r65-data/cninfo_stock
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
SEARCH = "http://www.cninfo.com.cn/new/fulltextSearch/full"
SZSE_LIST = "http://www.cninfo.com.cn/new/data/szse_stock.json"
DELAY = 1.0
PAGE_SIZE = 30
MAX_PAGES = 40
CST = timezone(timedelta(hours=8))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "http://www.cninfo.com.cn/",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}


def default_org_id(exchange: str, symbol: str) -> str:
    return ("gssh0" if exchange == "SH" else "gssz0") + symbol


def load_szse_org_ids() -> tuple[dict[str, str], str]:
    req = urllib.request.Request(SZSE_LIST, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = resp.read()
    payload = json.loads(raw.decode("utf-8"))
    return {x["code"]: x["orgId"] for x in payload.get("stockList") or []}, hashlib.sha256(raw).hexdigest()


def search_org_id(symbol: str, sdate: str, edate: str) -> tuple[str | None, int]:
    query = urllib.parse.urlencode(
        {
            "searchkey": symbol,
            "sdate": sdate,
            "edate": edate,
            "isfulltext": "false",
            "sortName": "pubdate",
            "sortType": "desc",
            "pageNum": 1,
            "pageSize": PAGE_SIZE,
        }
    )
    req = urllib.request.Request(f"{SEARCH}?{query}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    for it in payload.get("announcements") or []:
        if str(it.get("secCode")) == symbol:
            return it.get("orgId"), 1
    return None, 1


def query(org: str, symbol: str, exchange: str, sdate: str, edate: str, max_pages: int = MAX_PAGES) -> tuple[list[dict], list[str], int]:
    seen: dict[str, dict] = {}
    shas: list[str] = []
    page, total = 1, 0
    while page <= max_pages:
        body = urllib.parse.urlencode(
            {
                "pageNum": page,
                "pageSize": PAGE_SIZE,
                "column": "sse" if exchange == "SH" else "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": f"{symbol},{org}",
                "searchkey": "",
                "secid": "",
                "category": "",
                "trade": "",
                "seDate": f"{sdate}~{edate}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
        ).encode()
        req = urllib.request.Request(BASE, data=body, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read()
        shas.append(hashlib.sha256(raw).hexdigest())
        payload = json.loads(raw.decode("utf-8"))
        items = payload.get("announcements") or []
        total = int(payload.get("totalAnnouncement") or total)
        for it in items:
            key = str(it.get("announcementId") or "")
            if key and key not in seen:
                seen[key] = {
                    "title": it.get("announcementTitle"),
                    "time": it.get("announcementTime"),
                    "adjunctUrl": it.get("adjunctUrl"),
                }
        if not items or page * PAGE_SIZE >= total:
            break
        page += 1
        time.sleep(DELAY)
    return list(seen.values()), shas, total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--codes-file", required=True, help="CSV: exchange,symbol（第一行表头）")
    ap.add_argument("--sdate", default="2021-01-01")
    ap.add_argument("--edate", default="2026-11-10")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with Path(args.codes_file).open(newline="", encoding="utf-8-sig") as fh:
        codes = [
            (
                r["exchange"],
                r["symbol"],
                r.get("sdate") or args.sdate,
                r.get("edate") or args.edate,
            )
            for r in csv.DictReader(fh)
        ]
    path = out / "per_stock.jsonl"
    manifest = {
        "source": "cninfo hisAnnouncement/query (per stock)",
        "sdate": args.sdate,
        "edate": args.edate,
        "stocks": len(codes),
        "requests": 0,
        "failures": 0,
        "orgid_fallbacks": [],
        "empty_after_fallback": [],
        "started_at": datetime.now(CST).isoformat(timespec="seconds"),
    }
    szse_map: dict[str, str] = {}
    org_source = {}
    if any(row[0] == "SZ" for row in codes):
        szse_map, szse_sha = load_szse_org_ids()
        manifest["requests"] += 1
        org_source["szse_stock_json_sha256"] = szse_sha
    org_cache: dict[str, str] = {}
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for exchange, symbol, sdate, edate in codes:
            org = szse_map.get(symbol) or default_org_id(exchange, symbol)
            try:
                items, shas, total = query(org, symbol, exchange, sdate, edate, args.max_pages)
                manifest["requests"] += len(shas)
                if total == 0:
                    # orgId 可能不是默认/列表里的那个：用代码检索反查一次
                    found, n = search_org_id(symbol, sdate, edate)
                    manifest["requests"] += n
                    time.sleep(DELAY)
                    if found and found != org:
                        manifest["orgid_fallbacks"].append([exchange, symbol, org, found])
                        org = found
                        items, shas, total = query(org, symbol, exchange, sdate, edate, args.max_pages)
                        manifest["requests"] += len(shas)
                if total == 0:
                    manifest["empty_after_fallback"].append([exchange, symbol])
                org_cache[f"{exchange}:{symbol}"] = org
                fh.write(
                    json.dumps(
                        {
                            "exchange": exchange,
                            "symbol": symbol,
                            "org_id": org,
                            "total": total,
                            "announcements": items,
                            "page_sha256": shas,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            except Exception as exc:  # noqa: BLE001
                manifest["failures"] += 1
                fh.write(json.dumps({"exchange": exchange, "symbol": symbol, "error": type(exc).__name__}, ensure_ascii=False) + "\n")
            if (manifest["requests"] + manifest["failures"]) % 50 == 0:
                print(json.dumps({"requests": manifest["requests"], "failures": manifest["failures"]}, ensure_ascii=False), flush=True)
            time.sleep(DELAY)
        fh.flush()
    (out / "org_ids.json").write_text(json.dumps(org_cache, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    manifest.update(
        {
            "rows": manifest["requests"] + manifest["failures"],
            "finished_at": datetime.now(CST).isoformat(timespec="seconds"),
            "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "org_ids_sha256": hashlib.sha256((out / "org_ids.json").read_bytes()).hexdigest(),
        }
    )
    (out / "fetch_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
