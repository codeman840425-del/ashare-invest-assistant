"""第 13 项：T-R12 / T-R12a 财务时点自算实测（T-B05 窗口跑；plan 2.12.1，docs 6efedef + de86b99；V5j 见 review-af589c0 M1）。

只在显式点名时运行（`run_all.py p13`）：不在缺省全量 ORDER 里，缺省全量运行的调用次数不变。
固定 28 次调用（mock 下确定；真实运行时 ⑤ 的 gg 节点按 /hszg/list 实际返回动态选，找不到节点则少 1–2 次）：
  ① cashflow 全历史 ×6：600519 贵州茅台、000001 平安银行(银行)、600000 浦发银行(银行)、601318 中国平安(保险)、
     300750 宁德时代、600525 长园集团(差错更正样例)
  ② balance  全历史 ×5：同上去掉 600000（银行资产负债由 000001 覆盖；腾出 1 次给 V5j，review-af589c0 M1）
  ③ income   全历史 ×1：600525（与 ①② 的 600525 合起来看三张表的多版本）
  ④⑥⑦ capital 全历史 ×5：600519（2011-07-01 送股）、000001、601318（A+H）、000550（A+B）、689009（CDR，V5j）
  ⑤ /hszg/list ×1、/hszg/zg ×2（000001、601318）、/hszg/gg ×2（银行一级节点、保险二级节点）
  ⑥ 日线不复权 /d/n st=20260901 et=20261031 ×3：600519、000001、601318
  ⑧ /hscp/jnfh ×2：600519、000001（送转事件 vs capital 行可见时间，V5d）
  ⑨ balance 全历史 ×1：689009 九号公司（CDR，开曼红筹）
  合计 6+5+1+5+5+3+2+1 = 28。

输出（当次运行目录 results/run-<ts>/p13_fin_pit/，独占创建、不覆盖）：
  raw_<key>.json   完整原始响应文本（已脱敏；写盘前断言不含证书）——多版本行全部字段原样保存
  manifest.json    每次调用：key、条目号、URL(脱敏)、HTTP 状态、行数、字段、sha256、文件名、fetched_at(UTC)
  plan_meta.json   公司类别、更正公司/公告日/受影响期、核对值（供离线分析）
  然后在同一进程里跑一次 p13_analyze（纯离线），写 results/run-<ts>/p13_analysis.json。
结构化摘要写入 results/run-<ts>/p13_fin_pit.json。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import common as c
import p13_analyze as an

SUBDIR = an.SUBDIR
# 可由 run_all 开关覆盖
RESTATED = {"code": "600525.SH", "announce": "2025-04-29",
            "periods": ["2023-09-30", "2023-12-31", "2024-03-31", "2024-06-30", "2024-09-30"],
            "source": "长园集团 2025-030 号公告（证券日报 2025-04-29 D904 版）"}
CASHFLOW_CODES = ["600519.SH", "000001.SZ", "600000.SH", "601318.SH", "300750.SZ"]
KINDS = {"600519": "general", "000001": "bank", "600000": "bank", "601318": "insurer", "300750": "general",
         "600525": "general(restated)", "000550": "A+B", "689009": "CDR"}
CAPITAL_CODES = ["600519.SH", "000001.SZ", "601318.SH", "000550.SZ", "689009.SH"]
BALANCE_SKIP = {"600000.SH"}   # review-af589c0 M1：总次数保持 28
PB_CODES = ["600519.SH", "000001.SZ", "601318.SH"]
JNFH_CODES = ["600519", "000001"]
ZG_CODES = ["000001", "601318"]
CDR_CODE = "689009.SH"
DAILY_RANGE = ("20260901", "20261031")
VERIFY_PENDING = {"000001": ["bank_balance"], "601318": ["insurance_balance", "non_a_share_capital"]}


def c6(code: str) -> str:
    return code.split(".")[0]


def call_plan(restated: str | None = None) -> list:
    """不含 ⑤ gg（依赖 list 结果，运行时追加）。每项 (key, 条目, 名称, 路径模板, 参数)。"""
    rs = restated or RESTATED["code"]
    codes = [*CASHFLOW_CODES, rs]
    p = [(f"cashflow_{c6(x)}", "①", f"p13_cashflow_{c6(x)}", f"/hsstock/financial/cashflow/{x}/{{licence}}", {})
         for x in codes]
    p += [(f"balance_{c6(x)}", "②", f"p13_balance_{c6(x)}", f"/hsstock/financial/balance/{x}/{{licence}}", {})
          for x in codes if x not in BALANCE_SKIP]
    p.append((f"income_{c6(rs)}", "③", f"p13_income_{c6(rs)}", f"/hsstock/financial/income/{rs}/{{licence}}", {}))
    p += [(f"capital_{c6(x)}", "④⑥⑦", f"p13_capital_{c6(x)}", f"/hsstock/financial/capital/{x}/{{licence}}", {})
          for x in CAPITAL_CODES]
    p.append(("hszg_list", "⑤", "p13_hszg_list", "/hszg/list/{licence}", {}))
    p += [(f"zg_{x}", "⑤", f"p13_hszg_zg_{x}", f"/hszg/zg/{x}/{{licence}}", {}) for x in ZG_CODES]
    p += [(f"daily_{c6(x)}", "⑥", f"p13_daily_{c6(x)}", f"/hsstock/history/{x}/d/n/{{licence}}",
           {"st": DAILY_RANGE[0], "et": DAILY_RANGE[1]}) for x in PB_CODES]
    p += [(f"jnfh_{x}", "⑧", f"p13_jnfh_{x}", f"/hscp/jnfh/{x}/{{licence}}", {}) for x in JNFH_CODES]
    p.append((f"balance_{c6(CDR_CODE)}", "⑨", f"p13_balance_{c6(CDR_CODE)}",
              f"/hsstock/financial/balance/{CDR_CODE}/{{licence}}", {}))
    return p


def pick_gg_nodes(list_rows: list) -> list:
    """从 /hszg/list 选 ⑤ 的成分查询节点：银行一级（名称含“银行”、上级为申万根）、保险二级（名称含“保险”）。"""
    sw = [r for r in list_rows if isinstance(r, dict) and (str(r.get("code", "")).startswith("sw")
                                                            or "申万" in str(r.get("name", "")))]
    out = []
    bank = [r for r in sw if "银行" in str(r.get("name", "")) and str(r.get("pcode", "")) == "swhy"] or \
           [r for r in sw if "银行" in str(r.get("name", ""))]
    if bank:
        out.append(("bank", str(bank[0]["code"])))
    ins = [r for r in sw if "保险" in str(r.get("name", "")) and str(r.get("code", "")).startswith("sw2")] or \
          [r for r in sw if "保险" in str(r.get("name", ""))]
    if ins:
        out.append(("insurance", str(ins[0]["code"])))
    return out


def plan_meta(restated: str | None = None) -> dict:
    rs = c6(restated or RESTATED["code"])
    return {"kinds": KINDS, "cashflow": [c6(x) for x in CASHFLOW_CODES] + [rs],
            "balance": [c6(x) for x in CASHFLOW_CODES if x not in BALANCE_SKIP] + [rs, c6(CDR_CODE)],
            "capital": [c6(x) for x in CAPITAL_CODES], "pb": [c6(x) for x in PB_CODES], "jnfh": JNFH_CODES,
            "restated": {**RESTATED, "code": rs}, "verify_pending": VERIFY_PENDING, "expect": an.EXPECT,
            "insurers_sw_l2_web": an.INSURERS_SW}


def _save(res: list, manifest: list, raw: dict, key: str, item: str, name: str, tpl: str, params: dict):
    r = c.call(name, tpl, **params)
    text = r.text or ""
    path = c.write_raw(f"{SUBDIR}/raw_{key}.json", text)
    rows = c.rows(r.data)
    entry = {"key": key, "item": item, "name": name, "url": r.url_redacted, "params": params, "status": r.status,
             "ok": r.ok, "rows": len(rows), "fields": sorted({k for x in rows if isinstance(x, dict) for k in x}),
             "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": r.nbytes,
             "raw_file": str(path.relative_to(c.ctx().run_dir)),
             "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "error": None if r.ok else (text[:300] or r.error)}
    manifest.append(entry)
    res.append({**c.summarize(r), "item": item, "raw_file": entry["raw_file"], "sha256": entry["sha256"]})
    raw[key] = r.data
    return r


def main(res):
    manifest, raw = [], {}
    rs = RESTATED["code"]
    for key, item, name, tpl, params in call_plan(rs):
        r = _save(res, manifest, raw, key, item, name, tpl, params)
        if key == "hszg_list":
            for tag, node in pick_gg_nodes(c.rows(r.data)):
                _save(res, manifest, raw, f"gg_{tag}_{node}", "⑤", f"p13_hszg_gg_{tag}",
                      f"/hszg/gg/{node}/{{licence}}", {})
    meta = plan_meta(rs)
    c.write_raw(f"{SUBDIR}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    c.write_raw(f"{SUBDIR}/plan_meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
    a = an.analyze(raw, meta)
    text = json.dumps(a, ensure_ascii=False, indent=1, default=str)
    c.write_raw("p13_analysis.json", text)
    lines = an.summary_lines(a)
    for line in lines:
        print("  " + line)
    res.append({"name": "p13_summary", "calls": len(manifest), "summary": lines, "analysis_file": "p13_analysis.json"})


if __name__ == "__main__":
    import sys
    import run_all
    sys.exit(run_all.cli(["p13_fin_pit", *sys.argv[1:]]))
