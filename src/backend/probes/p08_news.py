"""第 8 项：公告/新闻/消息面（文档中未找到新闻接口；仅测公告、问董秘、交易提示、解禁）。"""
import common as c
from _helpers import probe


def main(res):
    probe(res, "announcement_600519", "/hsstock/announcement/600519/{licence}", "p08_announcement")
    probe(res, "interactiveqa_600519", "/hsstock/interactiveqa/600519/{licence}", "p08_interactiveqa")
    probe(res, "hitc_jrts", "/hitc/jrts/{licence}", "p08_hitc_jrts")
    probe(res, "hscp_jjxs_600519", "/hscp/jjxs/600519/{licence}")
    probe(res, "hitc_jjxs", "/hitc/jjxs/{licence}")


if __name__ == "__main__":
    # 单独运行也走 run_all 的统一入口（同一进程、单长连接、熔断、不覆盖），可加 --dry-run
    import sys
    import run_all
    sys.exit(run_all.cli(["p08_news", *sys.argv[1:]]))
