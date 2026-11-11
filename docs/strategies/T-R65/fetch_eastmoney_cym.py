"""T-R65 ②-b：东财 F10 公司概况（曾用名链）逐股礼貌拉取——沪市 ST 交叉核对用。

用途：对沪市股票池逐股取 `jbzl.cym`（曾用名链）、当前简称、上市日期、证券类别，作为
「沪市 ST 状态变更事件」的完整性旁证（链里出现几次 ST/*ST 段，就应能找到对应数量的带日期事件）。
不是历史行情、不含账户/持仓信息；单线程、固定间隔、只读公开页。
输出（仓库外）：<out>/sh_cym.jsonl + <out>/fetch_manifest.json。

两种模式：
  全池：--hf-manifest + --vipdoc-dir（沪市 A 股全池；退市/无数据代码会触发服务端慢响应，注意耗时）
  子集：--codes-file（每行一个 6 位代码，来自巨潮 ST 事件命中的沪市股票；配合 --append 续抓）

用法：
  uv run --no-project python docs/strategies/T-R65/fetch_eastmoney_cym.py \
      --hf-manifest F:/ashare-invest-assistant/data/hf-1min/2022plus/manifest_files.csv \
      --vipdoc-dir "D:/西部证券/vipdoc/sh/minline" \
      --out F:/t-r65-data/em_cym
  uv run --no-project python docs/strategies/T-R65/fetch_eastmoney_cym.py \
      --codes-file F:/t-r65-data/cninfo/sh_codes.txt --append --out F:/t-r65-data/em_cym
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

URL = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code=SH{code}"
SH_A_PREFIX = ("600", "601", "603", "605", "688", "689")
DELAY = 1.0
CST = timezone(timedelta(hours=8))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://emweb.securities.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}


def pool(hf_manifest: Path, vipdoc_dir: Path | None) -> list[str]:
    codes: set[str] = set()
    with hf_manifest.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("is_bj") == "True" or row.get("exchange") != "SH":
                continue
            sym = row["symbol"].strip()
            if sym[:3] in SH_A_PREFIX:
                codes.add(sym)
    if vipdoc_dir is not None and vipdoc_dir.exists():
        for p in vipdoc_dir.glob("sh*.lc1"):
            sym = p.stem[2:]
            if len(sym) == 6 and sym[:3] in SH_A_PREFIX:
                codes.add(sym)
    return sorted(codes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hf-manifest", default=None)
    ap.add_argument("--vipdoc-dir", default=None)
    ap.add_argument("--codes-file", default=None, help="每行一个 6 位沪市代码；给出时忽略 --hf-manifest")
    ap.add_argument("--append", action="store_true", help="追加到已有 jsonl，并跳过已成功的代码")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.codes_file:
        codes = sorted(
            {
                line.strip().lstrip("SH").lstrip("sh")
                for line in Path(args.codes_file).read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            }
        )
    else:
        if not args.hf_manifest:
            ap.error("需要 --hf-manifest 或 --codes-file")
        codes = pool(Path(args.hf_manifest), Path(args.vipdoc_dir) if args.vipdoc_dir else None)
    path = out / "sh_cym.jsonl"
    previous: dict[str, dict] = {}
    if args.append and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            previous[row["code"]] = row
        codes = [code for code in codes if "cym" not in previous.get(code, {})]
    manifest = {
        "source": "eastmoney F10 CompanySurveyAjax (cym chain; no dates)",
        "codes_expected": len(codes) + (len(previous) if args.append else 0),
        "codes_this_run": len(codes),
        "requests": 0,
        "failures": 0,
        "started_at": datetime.now(CST).isoformat(timespec="seconds"),
        "delay_seconds": DELAY,
    }
    mode = "a" if args.append else "w"
    with path.open(mode, encoding="utf-8", newline="\n") as fh:
        for code in codes:
            try:
                req = urllib.request.Request(URL.format(code=code), headers=HEADERS)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    raw = resp.read()
                payload = json.loads(raw.decode("utf-8"))
                jb = payload.get("jbzl") or {}
                fx = payload.get("fxxg") or {}
                fh.write(
                    json.dumps(
                        {
                            "code": code,
                            "cym": jb.get("cym"),
                            "current_name": jb.get("agjc"),
                            "category": jb.get("zqlb"),
                            "listing_date": fx.get("ssrq"),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                manifest["requests"] += 1
            except Exception as exc:  # noqa: BLE001
                manifest["failures"] += 1
                fh.write(json.dumps({"code": code, "error": type(exc).__name__}, ensure_ascii=False) + "\n")
            if manifest["requests"] % 100 == 0:
                print(json.dumps({"done": manifest["requests"], "failures": manifest["failures"]}, ensure_ascii=False), flush=True)
            time.sleep(DELAY)
        fh.flush()
    manifest.update(
        {
            "rows": manifest["requests"] + manifest["failures"],
            "finished_at": datetime.now(CST).isoformat(timespec="seconds"),
            "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )
    (out / "fetch_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
