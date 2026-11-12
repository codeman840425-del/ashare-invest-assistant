"""T-R61：巨潮公开公告标题取样（研究侧；单线程、限流、异常即停、零麦蕊）。

抽样框（与 `docs/strategies/T-R60/sampling_plan.md` §2 一致）：
  巨潮资讯网公开公告查询的**连续交易日全量标题**，**不按关键词筛选**。
  本脚本按 `seDate` 取指定交易日的全部公告（不传 searchkey/category/stock），
  逐页顺序抓取，页间固定间隔 `--delay` 秒（默认 1.5s），单线程，不并发。

合规与红线：
  - 只访问巨潮公开查询页（`www.cninfo.com.cn/new/hisAnnouncement/query`）；
  - 不调麦蕊（0 次）、不带任何凭据、不读私有样本；
  - 任何非 200 / 解析失败 → 立即停止并保留已取页（不重试轰炸）；
  - 原始页只落本地研究目录（默认仓库外），不入库；入库的只有派生样本与统计。

用法：
  python docs/strategies/T-R61/fetch_titles.py --dates 2026-11-09 2026-11-10 \
      --out F:/t-r61-data --delay 1.5

产出（out 目录）：
  raw/<date>/page_<n>.json   原始响应（逐页）
  fetch_manifest.json        日期/页数/条数/每页 sha256/抓取时刻（UTC+8）
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
UA = "Mozilla/5.0 (research; sequential polite fetch; project owner authorized)"
MAX_PAGES = 80  # 单日保护上限（防参数异常导致无限翻页）


def query(date: str, page: int, size: int = 30) -> dict:
    body = urllib.parse.urlencode(
        {
            "pageNum": str(page),
            "pageSize": str(size),
            "column": "szse",
            "tabName": "fulltext",
            "plate": "",
            "stock": "",
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"{date}~{date}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
    ).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        if resp.status != 200:
            raise RuntimeError(f"http_{resp.status}")
        raw = resp.read()
    return {"raw": raw, "json": json.loads(raw.decode("utf-8"))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dates", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()

    out = Path(args.out)
    manifest = {"source": URL, "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
                "delay_seconds": args.delay, "dates": {}}
    total_rows = 0

    for date in args.dates:
        day_dir = out / "raw" / date
        day_dir.mkdir(parents=True, exist_ok=True)
        first = query(date, 1)
        pages = int(first["json"].get("totalpages") or 0)
        total = int(first["json"].get("totalAnnouncement") or 0)
        if pages < 1:
            print(f"[{date}] 0 pages, skip", file=sys.stderr)
            continue
        if pages > MAX_PAGES:
            raise SystemExit(f"[{date}] totalpages={pages} 超保护上限，停止")
        rows = 0
        meta_pages = []
        payloads = [(1, first)]
        for page in range(2, pages + 1):
            time.sleep(args.delay)
            payloads.append((page, query(date, page)))
        for page, item in payloads:
            raw = item["raw"]
            (day_dir / f"page_{page}.json").write_bytes(raw)
            items = item["json"].get("announcements") or []
            rows += len(items)
            meta_pages.append({"page": page, "rows": len(items),
                               "sha256": hashlib.sha256(raw).hexdigest()})
        manifest["dates"][date] = {"pages": pages, "totalAnnouncement": total,
                                   "rows_fetched": rows, "page_meta": meta_pages}
        total_rows += rows
        print(f"[{date}] pages={pages} totalAnnouncement={total} rows_fetched={rows}")

    manifest["total_rows"] = total_rows
    (out / "fetch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"dates": list(manifest["dates"]), "total_rows": total_rows},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
