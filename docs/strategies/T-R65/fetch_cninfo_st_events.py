"""T-R65 ②-a：巨潮公告关键词检索 → ST/*ST 状态变更事件（公开源、限流、只读）。

用途：沪市（以及交叉核对深市）2022-01-01 至 2026-11-10 的 ST 状态变更**日期**证据。
关键词取自交易所风险警示公告的标题惯用表述；每条结果保留 secCode/secName/title/announcementTime/announcementId。
输出（仓库外）：<out>/events.jsonl + <out>/fetch_manifest.json（含每页 sha256、请求数、失败数）。

用法：
  uv run --no-project python docs/strategies/T-R65/fetch_cninfo_st_events.py --out F:/t-r65-data/cninfo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = "http://www.cninfo.com.cn/new/fulltextSearch/full"
KEYWORDS = [
    "撤销退市风险警示",
    "撤销其他风险警示",
    "实施退市风险警示",
    "实施其他风险警示",
    # 深市模板惯用「实行」，2022-05 起实测多例（如 002069、000038）标题只含「实行」
    "实行退市风险警示",
    "实行其他风险警示",
    "被实施退市风险警示",
    "被实施其他风险警示",
    "进入退市整理期",
]
SDATE, EDATE = "2022-01-01", "2026-11-10"
PAGE_SIZE = 30
DELAY = 1.2
CST = timezone(timedelta(hours=8))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "http://www.cninfo.com.cn/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def get(url: str) -> tuple[bytes, dict]:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read(), dict(resp.headers)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sdate", default=SDATE)
    ap.add_argument("--edate", default=EDATE)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    events_path = out / "events.jsonl"
    manifest: dict = {
        "source": "cninfo fulltextSearch/full",
        "keywords": KEYWORDS,
        "sdate": args.sdate,
        "edate": args.edate,
        "requests": 0,
        "failures": 0,
        "pages": [],
        "started_at": datetime.now(CST).isoformat(timespec="seconds"),
    }
    seen: set[str] = set()
    rows = 0
    with events_path.open("w", encoding="utf-8", newline="\n") as fh:
        for kw in KEYWORDS:
            page = 1
            total = None
            while True:
                q = urllib.parse.urlencode(
                    {
                        "searchkey": kw,
                        "sdate": args.sdate,
                        "edate": args.edate,
                        "isfulltext": "false",
                        "sortName": "pubdate",
                        "sortType": "desc",
                        "pageNum": page,
                        "pageSize": PAGE_SIZE,
                    }
                )
                url = f"{BASE}?{q}"
                try:
                    raw, _ = get(url)
                except Exception as exc:  # noqa: BLE001
                    manifest["failures"] += 1
                    manifest["pages"].append({"keyword": kw, "page": page, "error": type(exc).__name__})
                    break
                manifest["requests"] += 1
                payload = json.loads(raw.decode("utf-8"))
                items = payload.get("announcements") or []
                total = payload.get("totalRecordNum") or total
                manifest["pages"].append(
                    {"keyword": kw, "page": page, "items": len(items), "total": total,
                     "sha256": hashlib.sha256(raw).hexdigest()}
                )
                if not items:
                    break
                for it in items:
                    aid = str(it.get("announcementId") or "")
                    key = aid or f"{it.get('secCode')}|{it.get('announcementTime')}|{it.get('shortTitle')}"
                    if key in seen:
                        continue
                    seen.add(key)
                    fh.write(
                        json.dumps(
                            {
                                "keyword": kw,
                                "secCode": it.get("secCode"),
                                "secName": it.get("secName"),
                                "title": it.get("shortTitle") or it.get("announcementTitle"),
                                "announcementTime": it.get("announcementTime"),
                                "announcementId": aid,
                                "adjunctUrl": it.get("adjunctUrl"),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    rows += 1
                page += 1
                pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else page
                if page > pages:
                    break
                time.sleep(DELAY)
            time.sleep(DELAY)
    manifest.update(
        {
            "rows": rows,
            "finished_at": datetime.now(CST).isoformat(timespec="seconds"),
            "events_sha256": hashlib.sha256(events_path.read_bytes()).hexdigest(),
        }
    )
    (out / "fetch_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({"rows": rows, "requests": manifest["requests"], "failures": manifest["failures"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
