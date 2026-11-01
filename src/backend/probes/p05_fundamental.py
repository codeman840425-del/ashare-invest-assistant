"""第 5 项：财务与估值（三大报表、主要指标、股本、股东、机构持股；是否有公告日 → 时点取数）。"""
import common as c
from _helpers import probe


def main(res):
    for t in ["income", "balance", "cashflow", "pershareindex", "capital", "topholder", "flowholder", "hm"]:
        probe(res, f"fin_{t}", f"/hsstock/financial/{t}/600519.SH/{{licence}}", f"p05_fin_{t}", 2,
              st="20200101", et="20261031")
    probe(res, "fin_income_full", "/hsstock/financial/income/000001.SZ/{licence}")  # 不带区间看回溯
    for t in ["cwzb", "yjyg", "jjcg", "sdgd", "jnfh"]:
        probe(res, f"hscp_{t}", f"/hscp/{t}/600519/{{licence}}", f"p05_hscp_{t}", 2)
    probe(res, "hicw_yjbb_2026Q3", "/hicw/yjbb/2026/3/{licence}", "p05_hicw_yjbb", 2)
    probe(res, "hicw_yjyg_2026Q4", "/hicw/yjyg/2026/4/{licence}")
    probe(res, "hijg_jgcghz_2026Q2", "/hijg/jgcghz/2026/2/{licence}", "p05_hijg_jgcghz", 2)
    probe(res, "hijg_jj_2026Q2", "/hijg/jj/2026/2/{licence}")


if __name__ == "__main__":
    # 单独运行也走 run_all 的统一入口（同一进程、单长连接、熔断、不覆盖），可加 --dry-run
    import sys
    import run_all
    sys.exit(run_all.cli(["p05_fundamental", *sys.argv[1:]]))
