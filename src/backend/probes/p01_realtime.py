"""第 1 项：实时行情（单股快照、五档盘口、多股批量、全市场）。"""
import common as c

CODES20 = ["000001", "600519", "300750", "688981", "000858", "601318", "600036", "002594", "000333", "601012",
           "600900", "300059", "002475", "600276", "601888", "000725", "600030", "601166", "002415", "603259"]


def main(res):
    for code in ["000001", "600519", "300750", "688981"]:
        r = c.call(f"real_time_{code}", f"/hsstock/real/time/{code}/{{licence}}")
        res.append(c.summarize(r) | {"sample": r.data})
        if code == "000001":
            c.save_sample("p01_real_time_000001", r)
    for code in ["000001", "600519"]:
        r = c.call(f"real_five_{code}", f"/hsstock/real/five/{code}/{{licence}}")
        res.append(c.summarize(r) | {"sample": r.data})
        if code == "000001":
            c.save_sample("p01_real_five_000001", r)
    r = c.call("hsrl_ssjy_000001", "/hsrl/ssjy/000001/{licence}")
    res.append(c.summarize(r) | {"sample": r.data}); c.save_sample("p01_hsrl_ssjy_000001", r)
    r = c.call("ssjy_more_20", "/hsrl/ssjy_more/{licence}", stock_codes=",".join(CODES20))
    res.append(c.summarize(r)); c.save_sample("p01_ssjy_more_20", r, 3)
    r = c.call("ssjy_more_21", "/hsrl/ssjy_more/{licence}", stock_codes=",".join(CODES20 + ["601398"]))
    res.append(c.summarize(r) | {"note": "测试超过 20 只的行为", "raw_head": r.text[:300]})
    r = c.call("ssjy_all_broker", "/hsrl/ssjy/all/{licence}")
    s = c.summarize(r); res.append(s); c.save_sample("p01_ssjy_all", r, 3)
    r = c.call("real_all_network", "/hsrl/real/all/{licence}")
    res.append(c.summarize(r)); c.save_sample("p01_real_all", r, 3)
    r = c.call("real_time_invalid_code", "/hsstock/real/time/999999/{licence}")
    res.append(c.summarize(r) | {"raw_head": r.text[:300]})


if __name__ == "__main__":
    # 单独运行也走 run_all 的统一入口（同一进程、单长连接、熔断、不覆盖），可加 --dry-run
    import sys
    import run_all
    sys.exit(run_all.cli(["p01_realtime", *sys.argv[1:]]))
