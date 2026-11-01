"""第 3 项：资金流（个股主力资金当日/历史区间；排行与连续净流入）。"""
import common as c
from _helpers import probe


def main(res):
    probe(res, "transaction_latest", "/hsstock/history/transaction/000001/{licence}", "p03_transaction_latest")
    probe(res, "transaction_365d", "/hsstock/history/transaction/600519/{licence}", None, st="20251101", et="20261030")
    probe(res, "transaction_only_st", "/hsstock/history/transaction/600519/{licence}", None, st="20261001")  # 文档：单边应 422
    probe(res, "transaction_day", "/hsstock/history/transaction/20261030/000001/{licence}", "p03_transaction_day")
    probe(res, "transaction_day_2020", "/hsstock/history/transaction/20200110/000001/{licence}")  # 回溯深度
    probe(res, "higg_zljlr", "/higg/zljlr/{licence}", "p03_higg_zljlr")
    probe(res, "hizj_lxlr", "/hizj/lxlr/{licence}", "p03_hizj_lxlr")
    probe(res, "hizj_ggjd_5", "/hizj/ggjd/5/{licence}", "p03_hizj_ggjd")
    probe(res, "hizj_bk", "/hizj/bk/{licence}", "p03_hizj_bk")


if __name__ == "__main__":
    # 单独运行也走 run_all 的统一入口（同一进程、单长连接、熔断、不覆盖），可加 --dry-run
    import sys
    import run_all
    sys.exit(run_all.cli(["p03_moneyflow", *sys.argv[1:]]))
