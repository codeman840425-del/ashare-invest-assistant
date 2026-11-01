"""第 9 项：限流与配额温和实测（最后运行）。

只做：①连续 30 次串行单股快照，观察是否出现 503/429；②错误格式（无效证书/404）。
不做压测；全市场批量接口（文档 1 次/分钟）不重复测试。触发超限即由 common 写 STOP 并中止。
"""
import common as c

N = 30


def main(res):
    ms, codes = [], {}
    for i in range(N):
        r = c.call(f"rl_real_time_{i}", "/hsstock/real/time/000001/{licence}")
        ms.append(r.ms); codes[r.status] = codes.get(r.status, 0) + 1
    res.append({"name": "serial_burst", "n": N, "status_counts": codes, **c.latency_stats(ms)})
    r = c.call("err_404_path", "/hsstock/real/notexist/000001/{licence}")
    res.append(c.summarize(r) | {"raw": r.text[:200]})


if __name__ == "__main__":
    # 单独运行也走 run_all 的统一入口（同一进程、单长连接、熔断、不覆盖），可加 --dry-run
    import sys
    import run_all
    sys.exit(run_all.cli(["p09_ratelimit", *sys.argv[1:]]))
