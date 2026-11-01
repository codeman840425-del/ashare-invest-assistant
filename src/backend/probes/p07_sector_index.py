"""第 7 项：板块/概念与成分股、指数行情。"""
import common as c
from _helpers import probe


def main(res):
    probe(res, "hszg_list", "/hszg/list/{licence}", "p07_hszg_list")
    probe(res, "hszg_zg_000001", "/hszg/zg/000001/{licence}", "p07_hszg_zg")
    probe(res, "hszg_gg_sw_bank", "/hszg/gg/sw_yh/{licence}", "p07_hszg_gg")  # 代码需按 hszg/list 实际值调整
    probe(res, "hslt_sectorslist", "/hslt/sectorslist/{licence}", "p07_sectorslist")
    probe(res, "hslt_primarylist", "/hslt/primarylist/{licence}", "p07_primarylist")
    probe(res, "hibk_gnbk", "/hibk/gnbk/{licence}", "p07_hibk_gnbk")
    probe(res, "hibk_zjhhy", "/hibk/zjhhy/{licence}")
    probe(res, "hsindex_list", "/hsindex/list/{licence}", "p07_hsindex_list")
    probe(res, "hsindex_real_000001", "/hsindex/real/time/000001.SH/{licence}", "p07_hsindex_real")
    probe(res, "hsindex_latest_d", "/hsindex/latest/000300.SH/d/{licence}", "p07_hsindex_latest", lt=5)
    probe(res, "hsindex_history_d", "/hsindex/history/000300.SH/d/{licence}", st="20050101", et="20261031")
    probe(res, "hsindex_pro_latest_1", "/hsindex/pro/latest/000001.SH/1/{licence}", lt=5)


if __name__ == "__main__":
    # 单独运行也走 run_all 的统一入口（同一进程、单长连接、熔断、不覆盖），可加 --dry-run
    import sys
    import run_all
    sys.exit(run_all.cli(["p07_sector_index", *sys.argv[1:]]))
