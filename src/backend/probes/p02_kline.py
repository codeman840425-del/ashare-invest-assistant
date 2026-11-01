"""第 2 项：分时与 K 线（1 分钟 Pro、5 分钟、日线；复权口径；历史回溯长度）。"""
import common as c


def add(res, r, sample=None, n=3, **extra):
    s = c.summarize(r)
    rows = c.rows(r.data)
    if rows:
        s["first_row"], s["last_row"] = rows[0], rows[-1]
    s.update(extra)
    res.append(s)
    if sample:
        c.save_sample(sample, r, n)


def main(res):
    # 日线：最新 + 各复权口径
    add(res, c.call("latest_d_n", "/hsstock/latest/000001.SZ/d/n/{licence}", lt=5), "p02_latest_d_n")
    add(res, c.call("latest_d_lt10", "/hsstock/latest/000001.SZ/d/n/{licence}", lt=10), note="文档写 lt 最多 5")
    for fq in ["n", "f", "b", "fr", "br"]:
        add(res, c.call(f"history_d_{fq}_recent", f"/hsstock/history/000001.SZ/d/{fq}/{{licence}}",
                        st="20250601", et="20250610"), fq=fq)
    # 日线全历史（回溯长度）
    add(res, c.call("history_d_n_full", "/hsstock/history/600519.SH/d/n/{licence}"), "p02_history_d_full")
    add(res, c.call("history_w_f", "/hsstock/history/600519.SH/w/f/{licence}", lt=5))
    # 5 分钟：最新 + 回溯
    add(res, c.call("latest_5_n", "/hsstock/latest/000001.SZ/5/n/{licence}", lt=5), "p02_latest_5")
    add(res, c.call("history_5_n_2020", "/hsstock/history/000001.SZ/5/n/{licence}", st="20200102", et="20200103"))
    add(res, c.call("history_5_n_2026", "/hsstock/history/000001.SZ/5/n/{licence}", st="20261030", et="20261030"))
    add(res, c.call("history_5_f", "/hsstock/history/000001.SZ/5/f/{licence}", lt=3), note="分钟级传 f 的行为")
    add(res, c.call("latest_1_nonpro", "/hsstock/latest/000001.SZ/1/n/{licence}", lt=3), note="普通路径 1 分钟")
    # 1 分钟 Pro
    add(res, c.call("pro_latest_1", "/hsstock/pro/latest/000001.SZ/1/n/{licence}", lt=5), "p02_pro_latest_1")
    add(res, c.call("pro_history_1_lastday", "/hsstock/pro/history/000001.SZ/1/n/{licence}",
                    st="20261030", et="20261030"), "p02_pro_history_1", 3)
    add(res, c.call("pro_history_1_2021", "/hsstock/pro/history/000001.SZ/1/n/{licence}",
                    st="20211101", et="20211102"))
    add(res, c.call("pro_history_1_2020", "/hsstock/pro/history/000001.SZ/1/n/{licence}",
                    st="20200102", et="20200103"))
    add(res, c.call("pro_history_1_2015", "/hsstock/pro/history/000001.SZ/1/n/{licence}",
                    st="20150105", et="20150105"))
    # 完整历史（pro 域名，60 次/分钟）
    add(res, c.call("pro_full_1_2012", "/hsstock/history/full/000001/1/n/{licence}", pro=True, year="2012"))
    add(res, c.call("pro_full_5_2000", "/hsstock/history/full/000001/5/n/{licence}", pro=True, year="2000"))
    # Pro 1 分钟技术指标
    add(res, c.call("pro_macd_1", "/hsstock/pro/history/macd/000001.SZ/1/n/{licence}", lt=3), "p02_pro_macd_1")
    # 日线技术指标
    for ind in ["macd", "ma", "boll", "kdj"]:
        add(res, c.call(f"history_{ind}_d", f"/hsstock/history/{ind}/000001.SZ/d/n/{{licence}}", lt=3),
            f"p02_history_{ind}_d")
    add(res, c.call("indicators", "/hsstock/indicators/000001.SZ/{licence}", st="20261001", et="20261031"),
        "p02_indicators")
    add(res, c.call("stopprice", "/hsstock/stopprice/history/000001.SZ/{licence}", st="20261001", et="20261031"),
        "p02_stopprice")
    add(res, c.call("instrument", "/hsstock/instrument/000001.SZ/{licence}"), "p02_instrument")
    add(res, c.call("tcalendar_2026", "/tcalendar/list/2026/{licence}"), "p02_tcalendar")


if __name__ == "__main__":
    # 单独运行也走 run_all 的统一入口（同一进程、单长连接、熔断、不覆盖），可加 --dry-run
    import sys
    import run_all
    sys.exit(run_all.cli(["p02_kline", *sys.argv[1:]]))
