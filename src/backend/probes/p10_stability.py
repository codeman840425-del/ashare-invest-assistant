"""第 10 项：稳定性——关键接口各重复 N 次（串行），统计成功率与 p50/p95。"""
import common as c

N = int(__import__("os").environ.get("PROBE_STABILITY_N", "12"))
CASES = [
    ("real_time", "/hsstock/real/time/600519/{licence}", {}),
    ("ssjy_more", "/hsrl/ssjy_more/{licence}", {"stock_codes": "000001,600519,300750,688981,000858"}),
    ("pro_latest_1", "/hsstock/pro/latest/000001.SZ/1/n/{licence}", {"lt": 5}),
    ("transaction", "/hsstock/history/transaction/000001/{licence}", {}),
    ("factor_valuation", "/factor/valuation/600519/{licence}", {}),
]


def main(res):
    for key, tpl, params in CASES:
        ms, ok = [], 0
        for i in range(N):
            r = c.call(f"stab_{key}_{i}", tpl, **params)
            ms.append(r.ms); ok += int(r.ok)
        res.append({"name": key, "success": ok, "total": N, "rate": round(ok / N, 3), **c.latency_stats(ms)})


if __name__ == "__main__":
    # 单独运行也走 run_all 的统一入口（同一进程、单长连接、熔断、不覆盖），可加 --dry-run
    import sys
    import run_all
    sys.exit(run_all.cli(["p10_stability", *sys.argv[1:]]))
