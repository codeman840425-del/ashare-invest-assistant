"""第 4 项：龙虎榜、涨跌停股池（含炸板/强势/次新）、集合竞价与涨跌停表现。"""
import common as c
from _helpers import probe

LAST_TRADE_DAY = "2026-10-30"


def main(res):
    probe(res, "hilh_mrxq", "/hilh/mrxq/{licence}", "p04_hilh_mrxq")
    probe(res, "hilh_ggsb_5", "/hilh/ggsb/5/{licence}", "p04_hilh_ggsb")
    probe(res, "hilh_jgxw_5", "/hilh/jgxw/5/{licence}", "p04_hilh_jgxw")
    for pool in ["ztgc", "dtgc", "zbgc", "qsgc", "cxgc"]:
        probe(res, f"{pool}_{LAST_TRADE_DAY}", f"/hslt/{pool}/{LAST_TRADE_DAY}/{{licence}}", f"p04_{pool}")
    probe(res, "ztgc_old_2026-08-03", "/hslt/ztgc/2026-08-03/{licence}")  # 回溯深度（文档约 30 天）
    probe(res, "ztgc_old_2025-10-30", "/hslt/ztgc/2025-10-30/{licence}")
    for code in ["000001", "300030"]:  # 300030 在 10-30 全市场快照中涨幅 20%
        probe(res, f"lup_limit_{code}", f"/hsstock/lup/limit/{code}/{{licence}}", f"p04_lup_limit_{code}")
        probe(res, f"lup_auction_{code}", f"/hsstock/lup/auction/{code}/{{licence}}", f"p04_lup_auction_{code}")


if __name__ == "__main__":
    # 单独运行也走 run_all 的统一入口（同一进程、单长连接、熔断、不覆盖），可加 --dry-run
    import sys
    import run_all
    sys.exit(run_all.cli(["p04_lhb_pool_auction", *sys.argv[1:]]))
