"""第 6 项：技术指标接口 + Quant Pro 因子逐类抽测，统计空值因子。"""
import common as c
from _helpers import probe

CATS = ["valuation", "quality", "growth", "momentum", "capital", "signal", "risk", "dividend", "scale",
        "sentiment", "intraday"]
META = {"code", "name", "trade_date", "update_time", "report_period", "calc_version"}


def null_fields(d):
    if isinstance(d, dict) and isinstance(d.get("data"), dict):
        d = d["data"]
    if not isinstance(d, dict):
        return None, None
    keys = [k for k in d if k not in META]
    return keys, [k for k in keys if d[k] in (None, "", "null")]


def main(res):
    probe(res, "factor_list", "/factor/list/{licence}", "p06_factor_list", 200)
    probe(res, "factor_categories", "/factor/categories/{licence}", "p06_factor_categories")
    nulls = {}
    for code in ["600519", "000001"]:
        for cat in CATS:
            r = probe(res, f"factor_{cat}_{code}", f"/factor/{cat}/{code}/{{licence}}",
                      f"p06_factor_{cat}_{code}" if code == "600519" else None)
            keys, nl = null_fields(r.data)
            res[-1]["factor_keys"], res[-1]["null_factors"] = keys, nl
            nulls[f"{cat}/{code}"] = nl
    r = probe(res, "factor_all_600519", "/factor/all/600519/{licence}", "p06_factor_all")
    probe(res, "factor_history_pe_ttm", "/factor/history/pe_ttm/600519/{licence}", "p06_factor_history")
    probe(res, "factor_percentile_pe_ttm", "/factor/percentile/pe_ttm/600519/{licence}")
    probe(res, "factor_rank_roe_ttm", "/factor/rank/roe_ttm/{licence}")
    probe(res, "factor_top_roe_ttm_10", "/factor/top/roe_ttm/10/{licence}", "p06_factor_top")
    probe(res, "factor_batch", "/factor/batch/{licence}", "p06_factor_batch", method="POST",
          json_body={"codes": ["600519", "000001"], "factor_ids": ["pe_ttm", "roe_ttm", "momentum_20d",
                                                                    "north_5d_net", "attention_score"]})
    probe(res, "factor_screen", "/factor/screen/{licence}", "p06_factor_screen", method="POST",
          json_body={"conditions": [{"factor_id": "pe_ttm", "operator": "between", "value": [5, 30]},
                                    {"factor_id": "roe_ttm", "operator": ">", "value": 15}],
                     "order_by": "roe_ttm", "order": "desc", "page": 1, "page_size": 20,
                     "fields": ["code", "name", "pe_ttm", "roe_ttm"]})
    res.append({"name": "NULL_FACTOR_SUMMARY", "nulls": nulls})


if __name__ == "__main__":
    # 单独运行也走 run_all 的统一入口（同一进程、单长连接、熔断、不覆盖），可加 --dry-run
    import sys
    import run_all
    sys.exit(run_all.cli(["p06_factors", *sys.argv[1:]]))
