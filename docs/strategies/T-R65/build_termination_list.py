"""T-R65 ②-d：沪深终止名单 + 退市整理期起点（runner 输入）。

输入：
  --szse-xlsx        深交所「终止上市公司」导出（证券代码/证券简称/上市日期/终止上市日期）
  --securities-csv   库内 market.securities 的只读导出（code,name,exchange,...,list_date,delist_date,listing_status,...）
  --per-stock-jsonl  可选：巨潮逐股公告（fetch_cninfo_per_stock.py 输出），用于补「终止上市公告 URL」和整理期起点

输出（--out-dir）：
  termination_list.csv        exchange,symbol,delisting_date,name,source,source_url
  delisting_period.csv        exchange,symbol,start_date,source,source_url
  termination_manifest.json

口径：终止名单只认交易所（深交所导出 / 库内 exchange_delist_list 来源）；B 股（200/900 前缀）不入 runner 名单但计数披露；
      runner 侧按 exchange+symbol 精确匹配，故 symbol 用 6 位纯代码。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
A_PREFIXES = ("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689")
SZ_A_PREFIXES = ("000", "001", "002", "003", "300", "301")
SH_A_PREFIXES = ("600", "601", "603", "605", "688", "689")
CNINFO_PDF = "http://static.cninfo.com.cn/"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def read_szse_xlsx(path: Path) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=False, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(x).strip() if x is not None else "" for x in rows[0]]
    need = {"证券代码", "证券简称", "终止上市日期"}
    if not need <= set(header):
        raise SystemExit(f"unexpected szse columns: {header}")
    idx = {name: header.index(name) for name in need | {"上市日期"}}
    result = []
    for row in rows[1:]:
        if row[idx["证券代码"]] is None:
            continue
        result.append(
            {
                "symbol": str(row[idx["证券代码"]]).strip().zfill(6),
                "name": str(row[idx["证券简称"]] or "").strip(),
                "list_date": str(row[idx["上市日期"]] or "")[:10] if row[idx["上市日期"]] else "",
                "delisting_date": str(row[idx["终止上市日期"]] or "")[:10]
                if row[idx["终止上市日期"]]
                else "",
            }
        )
    return result


def announcement_time_ms_to_date(ms: int | None) -> date | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=CST).date()


def pick(announcements: list[dict], needle: str) -> list[dict]:
    return [a for a in announcements if needle in (a.get("title") or "")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--szse-xlsx", required=True)
    ap.add_argument("--securities-csv", required=True)
    ap.add_argument("--per-stock-jsonl", default=None)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    xlsx = Path(args.szse_xlsx)
    securities_csv = Path(args.securities_csv)

    sz_rows = read_szse_xlsx(xlsx)
    securities = read_csv(securities_csv)
    db = {}
    for r in securities:
        sym, exch = r["code"].split(".")
        db[(exch, sym)] = r

    per_stock = {}
    if args.per_stock_jsonl:
        for line in Path(args.per_stock_jsonl).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if "error" in row:
                continue
            per_stock[(row["exchange"], row["symbol"])] = row.get("announcements") or []

    termination: list[dict] = []
    period: list[dict] = []
    notes = {"szse_rows": len(sz_rows), "szse_b_share_rows": 0, "szse_a_rows": 0,
             "db_sh_delisted": 0, "date_diffs": [], "missing_url": [], "period_missing": [],
             "period_span_days": []}

    for r in sz_rows:
        if r["symbol"].startswith(("200", "201")):
            notes["szse_b_share_rows"] += 1
            continue
        if not r["symbol"].startswith(SZ_A_PREFIXES) or not r["delisting_date"]:
            continue
        notes["szse_a_rows"] += 1
        key = ("SZ", r["symbol"])
        url = ""
        anns = per_stock.get(key, [])
        terminal = pick(anns, "终止上市")
        if terminal:
            first = sorted(terminal, key=lambda a: a["time"] or 0)[-1]
            url = CNINFO_PDF + (first.get("adjunctUrl") or "") if first.get("adjunctUrl") else ""
        termination.append(
            {
                "exchange": "SZ",
                "symbol": r["symbol"],
                "delisting_date": r["delisting_date"],
                "name": r["name"],
                "source": "szse_delist_xlsx",
                "source_url": url,
            }
        )
        starts = pick(anns, "进入退市整理期")
        if starts:
            first = sorted(starts, key=lambda a: a["time"] or 0)[0]
            day = announcement_time_ms_to_date(first.get("time"))
            if day:
                period.append(
                    {
                        "exchange": "SZ",
                        "symbol": r["symbol"],
                        "start_date": day.isoformat(),
                        "source": "cninfo_first_delisting_period_announcement",
                        "source_url": CNINFO_PDF + (first.get("adjunctUrl") or ""),
                    }
                )
        else:
            notes["period_missing"].append(("SZ", r["symbol"]))

    for key, r in sorted(db.items()):
        exch, sym = key
        if exch != "SH" or r["listing_status"] != "delisted" or not r["delist_date"]:
            continue
        if not sym.startswith(SH_A_PREFIXES):
            continue
        notes["db_sh_delisted"] += 1
        anns = per_stock.get(key, [])
        terminal = pick(anns, "终止上市")
        url = ""
        if terminal:
            first = sorted(terminal, key=lambda a: a["time"] or 0)[-1]
            if first.get("adjunctUrl"):
                url = CNINFO_PDF + first["adjunctUrl"]
        termination.append(
            {
                "exchange": "SH",
                "symbol": sym,
                "delisting_date": r["delist_date"],
                "name": r["name"],
                "source": "db_securities_exchange_delist_list",
                "source_url": url,
            }
        )
        starts = pick(anns, "进入退市整理期")
        if starts:
            first = sorted(starts, key=lambda a: a["time"] or 0)[0]
            day = announcement_time_ms_to_date(first.get("time"))
            if day:
                period.append(
                    {
                        "exchange": "SH",
                        "symbol": sym,
                        "start_date": day.isoformat(),
                        "source": "cninfo_first_delisting_period_announcement",
                        "source_url": CNINFO_PDF + (first.get("adjunctUrl") or ""),
                    }
                )
        else:
            notes["period_missing"].append(("SH", sym))

    # 交叉核对：深市 xlsx A 股 vs 库内 delisted
    xlsx_dates = {("SZ", r["symbol"]): r["delisting_date"] for r in sz_rows if r["symbol"].startswith(SZ_A_PREFIXES)}
    db_sz = {k: v["delist_date"] for k, v in db.items() if k[0] == "SZ" and v["listing_status"] == "delisted" and v["delist_date"]}
    for key, day in sorted(db_sz.items()):
        if key in xlsx_dates and xlsx_dates[key] != day:
            notes["date_diffs"].append([key[0], key[1], xlsx_dates[key], day])
    notes["db_sz_not_in_xlsx"] = sorted(f"{e}:{s}" for e, s in set(db_sz) - set(xlsx_dates))
    notes["xlsx_not_in_db"] = sorted(f"{e}:{s}" for e, s in set(xlsx_dates) - set(db_sz))
    notes["missing_url"] = [[e, s] for e, s, _ in [(x["exchange"], x["symbol"], x["source_url"]) for x in termination] if not _]

    # 整理期公告日与终止日跨度（只做诊断，日历日）
    for row in period:
        term = next(
            (x["delisting_date"] for x in termination
             if x["exchange"] == row["exchange"] and x["symbol"] == row["symbol"]),
            None,
        )
        if term:
            notes["period_span_days"].append((date.fromisoformat(term) - date.fromisoformat(row["start_date"])).days)

    termination.sort(key=lambda x: (x["exchange"], x["symbol"]))
    period.sort(key=lambda x: (x["exchange"], x["symbol"]))
    term_path = out / "termination_list.csv"
    with term_path.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=["exchange", "symbol", "delisting_date", "name", "source", "source_url"])
        w.writeheader()
        w.writerows(termination)
    period_path = out / "delisting_period.csv"
    with period_path.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=["exchange", "symbol", "start_date", "source", "source_url"])
        w.writeheader()
        w.writerows(period)

    manifest = {
        "product": "termination_list_and_delisting_period",
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "inputs": {
            "szse_xlsx": {"path_name": xlsx.name, "sha256": sha256(xlsx)},
            "securities_csv": {"path_name": securities_csv.name, "sha256": sha256(securities_csv)},
        },
        "outputs": {
            "termination_list": {"rows": len(termination), "sha256": sha256(term_path)},
            "delisting_period": {"rows": len(period), "sha256": sha256(period_path)},
        },
        "counts": {
            "termination_by_exchange": {
                e: sum(1 for x in termination if x["exchange"] == e) for e in ("SH", "SZ")
            },
            "period_by_exchange": {e: sum(1 for x in period if x["exchange"] == e) for e in ("SH", "SZ")},
        },
        "checks": notes,
        "rule": {
            "termination_source": "只认交易所：深交所终止上市导出；沪市取库内 exchange_delist_list 来源的 delisted+delist_date",
            "b_shares": "200/201 前缀不计入 runner 名单，仅计数披露",
            "delisting_period_start": "巨潮个股公告中最早一条「进入退市整理期」公告日期（未按交易日校正，见 README 口径）",
        },
    }
    (out / "termination_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({"termination": len(termination), "period": len(period), "missing_url": len(notes["missing_url"]), "period_missing": len(notes["period_missing"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
