"""串行依次运行全部探针：同一进程、同一 requests.Session、每个主机一条长连接、无并发、无子进程。

用法（证书只通过环境变量 MAIRUI_LICENCE 提供，详见 README.md）：
  python run_all.py --dry-run            # 离线自检：本地伪造服务端，不出网、不用真实证书
  python run_all.py                      # 真实运行全部探针
  python run_all.py p01 p02              # 只运行指定前缀的探针
  python run_all.py --check-egress       # 运行前用同一 Session 访问 myip.ipip.net 自检出口 IP 是否固定（默认关闭）
  python run_all.py --skip-pro-host      # 跳过 pro.mairuiapi.com 的 2 次调用，全程只连 api.mairuiapi.com
  python run_all.py --use-env-proxy      # 改为使用 HTTP(S)_PROXY/系统代理（默认 --no-env-proxy：忽略代理、本机直连）

results/STOP 存在时拒绝真实调用；删除前请确认已等待 ≥60 秒且出口 IP 固定。
"""
from __future__ import annotations

import argparse
import importlib
import io
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import common as c  # noqa: E402

ORDER = ["p01_realtime", "p02_kline", "p03_moneyflow", "p04_lhb_pool_auction", "p05_fundamental",
         "p06_factors", "p07_sector_index", "p08_news", "p11_gaps", "p10_stability", "p09_ratelimit"]


def select(want: list) -> list:
    return [m for m in ORDER if not want or any(m.startswith(w) for w in want)]


def run_probes(mods: list) -> bool:
    """在当前进程内顺序 import 并运行探针；熔断即停。返回是否全部未熔断。"""
    for mod in mods:
        if c.ctx().stop_file.exists():
            print("STOP 文件存在，终止：", c.ctx().stop_file.read_text(encoding="utf-8")[:200])
            return False
        print(f"===== {mod} =====")
        if not c.run_probe(mod, importlib.import_module(mod).main):
            return False
    return True


# --------------------------------------------------------------------------- 真实运行
def real_run(args) -> int:
    if not os.environ.get("MAIRUI_LICENCE"):
        print("MAIRUI_LICENCE 未设置。请按 README 在当前会话中设置后再运行（不要写进脚本）。")
        return 2
    if c.STOP_FILE.exists():
        print("results/STOP 存在，拒绝调用。内容：", c.STOP_FILE.read_text(encoding="utf-8")[:200])
        print("确认已等待 ≥60 秒、出口 IP 固定、证书未在别处使用后，手动删除 results/STOP 再运行。")
        return 2
    c.cooldown_if_needed()
    ctx = c.init_run(dry_run=False, min_interval=args.min_interval, skip_pro_host=args.skip_pro_host,
                     no_env_proxy=args.no_env_proxy, egress_url=args.egress_url)
    print(f"运行目录：{ctx.run_dir}")
    if args.check_egress:
        print(f"出口 IP 自检：{ctx.egress_url}（与麦蕊调用同一 Session、同一代理设置；不访问麦蕊）")
        stable, ips = c.check_egress_stable(args.egress_rounds)
        if not stable:
            print(f"出口 IP 不固定或无法确认 {ips}，拒绝运行（同一证书 60 秒内 >2 个 IP 会触发 103）。")
            c.close_run()
            return 3
        print(f"出口 IP 固定：{ips[0]}")
    t0 = time.monotonic()
    ok = run_probes(select(args.probes))
    summary = c.close_run()
    summary["elapsed_s"] = round(time.monotonic() - t0, 1)
    print("===== 汇总 =====")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    multi = {h: n for h, n in summary["max_connections_seen"].items() if n > 1 and not _is_egress_host(h)}
    if multi:
        print(f"警告：以下主机建立了多条 TCP 连接（服务端可能关闭了空闲连接），出口 IP 可能变化：{multi}")
    return 0 if ok else 1


def _is_egress_host(pool_key: str) -> bool:
    from urllib.parse import urlsplit
    e = urlsplit(c.ctx().egress_url)
    p = urlsplit(pool_key)
    return (p.hostname, p.port or (443 if p.scheme == "https" else 80)) == \
        (e.hostname, e.port or (443 if e.scheme == "https" else 80))


# --------------------------------------------------------------------------- dry-run
class Tee(io.TextIOBase):
    def __init__(self, stream):
        self.stream, self.buf = stream, io.StringIO()

    def write(self, s):
        self.buf.write(s)
        return self.stream.write(s)

    def flush(self):
        self.stream.flush()


def _snapshot_stop():
    p = c.STOP_FILE
    return (p.exists(), p.stat().st_mtime if p.exists() else None,
            p.read_bytes() if p.exists() else None)


def _scan_dir_for_licence(d: Path) -> int:
    real = os.environ.get("MAIRUI_LICENCE", "")
    hits = 0
    for f in d.rglob("*"):
        if f.is_file():
            b = f.read_bytes()
            if c.DRY_RUN_LICENCE.encode() in b or (real and real.encode("utf-8") in b):
                hits += 1
    return hits


def _check_gaps(check, run_dir, expect_latency, want):
    """检查 p11_gaps 结果：7 项（GAP1–GAP7）均有结构化结论字段。"""
    if "p11_gaps" not in want:
        return
    files = sorted(run_dir.glob("p11_gaps*.json"))
    items = {}
    if files:
        for x in json.loads(files[-1].read_text(encoding="utf-8")):
            if isinstance(x, dict) and str(x.get("name", "")).startswith("GAP") and "status" in x:
                items[x["name"].split("_")[0]] = x
    need = [f"GAP{i}" for i in range(1, 8)]
    struct_ok = all(k in items and isinstance(items[k].get("conclusion"), dict) and items[k]["status"] in (
        "measured", "skipped", "inconclusive") and "limits" in items[k] for k in need)
    check(f"p11：7 项补测均输出结构化结论（status/conclusion/evidence/limits）", struct_ok,
          ", ".join(f"{k}={items[k]['status']}" if k in items else f"{k}=缺失" for k in need))
    g1 = items.get("GAP1")
    check(f"p11：快照延迟项状态 = {expect_latency}", g1 is not None and g1["status"] == expect_latency,
          (g1 or {}).get("conclusion", {}).get("summary", "")[:120])


def dry_run(args) -> int:
    import dryrun_mock as m

    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    stop_before = _snapshot_stop()
    guard = m.NetGuard().install()
    srv_api, st_api, base_api = m.start_server("api")
    srv_pro, st_pro, base_pro = m.start_server("pro")
    srv_echo, st_echo, echo_url = m.start_ip_echo()
    srv_proxy, st_proxy, proxy_url = m.start_proxy_recorder()
    tee = Tee(sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = tee
    try:
        # ---- 阶段 1：全流程
        ctx1 = c.init_run(dry_run=True, base=base_api, pro_base=base_pro, min_interval=args.dry_interval,
                          skip_pro_host=args.skip_pro_host, no_env_proxy=args.no_env_proxy, egress_url=echo_url)
        print(f"[dry-run] 阶段 1 全流程，输出目录 {ctx1.run_dir}")
        stable, ips = c.check_egress_stable(3)
        check("出口自检（模拟 myip.ipip.net，同一 Session）：3 次 IP 一致 → 放行", stable and ips[0] == "203.0.113.7",
              f"ips={ips} 回显服务连接数={st_echo.connections}")
        import p11_gaps
        p11_gaps.FORCE_SESSION = True          # 阶段 1 强制走“盘中采样”分支（仅 dry-run 生效）
        ok1 = run_probes(select(args.probes))
        s1 = c.close_run()
        _check_gaps(check, ctx1.run_dir, expect_latency="measured", want=select(args.probes))
        check("全流程跑完未熔断", ok1)
        check("客户端调用数 = 服务端请求数", s1["calls"] == st_api.requests + st_pro.requests,
              f"client={s1['calls']} server={st_api.requests}+{st_pro.requests}")
        check("api 主机只建立 1 条 TCP 连接（服务端 accept 计数）", st_api.connections == 1,
              f"accept={st_api.connections} 端口={len(st_api.client_ports)} 请求={st_api.requests}")
        exp_pro = 0 if (args.skip_pro_host or st_pro.requests == 0) else 1
        check(f"pro 主机建立 {exp_pro} 条 TCP 连接", st_pro.connections == exp_pro,
              f"accept={st_pro.connections} 请求={st_pro.requests}")
        mr_conns = {h: n for h, n in s1["max_connections_seen"].items() if not _is_egress_host(h)}
        check("客户端连接池：麦蕊每主机最多 1 条连接（不含 IP 回显主机）", all(n <= 1 for n in mr_conns.values()),
              str(mr_conns))
        check("summary.json 记录代理模式与出口自检", "proxy_mode" in s1 and (s1.get("egress_check") or {}).get("stable"),
              s1.get("proxy_mode", ""))
        check("串行：服务端同时处理中的请求数峰值 = 1", max(st_api.max_active, st_pro.max_active) <= 1,
              f"api={st_api.max_active} pro={st_pro.max_active}")
        check("请求路径中证书均为假证书、真实证书从未发送",
              st_api.bad_licence == 0 and st_pro.bad_licence == 0 and not (st_api.saw_real_licence or st_pro.saw_real_licence))
        n_files = sum(1 for f in ctx1.run_dir.rglob("*") if f.is_file())
        check("输出文件不含证书（假证书/真实证书）", _scan_dir_for_licence(ctx1.run_dir) == 0, f"扫描 {n_files} 个文件")
        # ---- 阶段 1b：p11 盘后分支（强制视为盘后）→ 快照延迟项记“盘后无法测”，不发采样请求
        if "p11_gaps" in select(args.probes):
            p11_gaps.FORCE_SESSION = False
            ctx1b = c.init_run(dry_run=True, base=base_api, pro_base=base_pro, min_interval=args.dry_interval,
                               skip_pro_host=args.skip_pro_host, no_env_proxy=args.no_env_proxy,
                               egress_url=echo_url, tag="dryrun-p11-afterhours")
            print(f"[dry-run] 阶段 1b p11 盘后分支，输出目录 {ctx1b.run_dir}")
            run_probes(["p11_gaps"])
            s1b = c.close_run()
            _check_gaps(check, ctx1b.run_dir, expect_latency="skipped", want=["p11_gaps"])
            names = [json.loads(x).get("name", "") for x in ctx1b.call_log.read_text(encoding="utf-8").splitlines()]
            check("p11 盘后：不发快照延迟采样请求（lat_*/tcalendar 为 0）",
                  not any(n.startswith("lat_") or n.startswith("tcalendar") for n in names),
                  f"本阶段调用 {s1b['calls']} 次")
            check("p11 输出不含证书", _scan_dir_for_licence(ctx1b.run_dir) == 0)
            p11_gaps.FORCE_SESSION = None
            for n_, ok_, d_ in p11_gaps.selftest_pure():
                check("p11 纯函数单测：" + n_, ok_, d_)
        # ---- 阶段 2：熔断（第 3 个请求起返回 429 + 103）
        ctx2 = c.init_run(dry_run=True, base=base_api, pro_base=base_pro, min_interval=args.dry_interval,
                          tag="dryrun-limit", no_env_proxy=args.no_env_proxy, egress_url=echo_url)
        print(f"[dry-run] 阶段 2 熔断测试，输出目录 {ctx2.run_dir}")
        st_api.fail_after = st_api.requests + 2
        ok2 = run_probes(select(["p01", "p02"]))
        req_after_stop = st_api.requests
        blocked_ok = False
        try:
            c.call("after_stop", "/hsstock/real/time/000001/{licence}")
        except c.LimitHit:
            blocked_ok = True
        check("遇到 429/103 立即熔断并停止后续探针", ok2 is False and ctx2.stop_file.exists())
        check("熔断后 STOP 生效：不再发出任何请求", blocked_ok and st_api.requests == req_after_stop)
        check("熔断只写 dry-run 目录内的 STOP", ctx2.stop_file.parent == ctx2.run_dir)
        st_api.fail_after = None
        # ---- 阶段 3：不覆盖
        p_a = c.write_results("overwrite_test", [{"n": 1}])
        p_b = c.write_results("overwrite_test", [{"n": 2}])
        check("同名结果不覆盖（自动加序号）", p_a != p_b and json.loads(p_a.read_text(encoding="utf-8"))[0]["n"] == 1,
              f"{p_a.name} / {p_b.name}")
        check("每次运行使用独立的时间戳目录", ctx1.run_dir != ctx2.run_dir, f"{ctx1.run_id} / {ctx2.run_id}")
        # 出口不固定 → 拒绝
        st_echo.rotate = True
        unstable, ips2 = c.check_egress_stable(3)
        st_echo.rotate = False
        check("出口自检：多次 IP 不一致 → 拒绝运行", unstable is False and all(ips2) and len(set(ips2)) > 1,
              f"ips={ips2}")
        c.close_run()
        check("阶段 2 输出不含证书", _scan_dir_for_licence(ctx2.run_dir) == 0)
        # ---- 阶段 4：代理环境变量（假 HTTP(S)_PROXY 指向本地记录端口）
        names = c.PROXY_ENV_NAMES + ("NO_PROXY", "no_proxy")
        saved_env = {n: os.environ.get(n) for n in names}
        try:
            for n in c.PROXY_ENV_NAMES:
                os.environ[n] = proxy_url
            os.environ.pop("NO_PROXY", None); os.environ.pop("no_proxy", None)
            ctx3 = c.init_run(dry_run=True, base=base_api, pro_base=base_pro, min_interval=args.dry_interval,
                              no_env_proxy=True, egress_url=echo_url, tag="dryrun-proxy-default")
            api0, echo0, px0 = st_api.requests, st_echo.requests, st_proxy.requests
            for i in range(3):
                c.call(f"direct_{i}", "/hsstock/real/time/000001/{licence}")
            c.check_egress_stable(2)
            s3 = c.close_run()
            check("默认 --no-env-proxy：假代理端口收到 0 个请求，请求直达目标",
                  st_proxy.requests == px0 == 0 and st_api.requests == api0 + 3 and st_echo.requests == echo0 + 2,
                  f"代理端口请求={st_proxy.requests} 连接={st_proxy.connections}；api +{st_api.requests - api0}，"
                  f"ip回显 +{st_echo.requests - echo0}；{s3['proxy_mode']}")
            ctx4 = c.init_run(dry_run=True, base=base_api, pro_base=base_pro, min_interval=args.dry_interval,
                              no_env_proxy=False, egress_url=echo_url, tag="dryrun-proxy-env")
            api1, px1 = st_api.requests, st_proxy.requests
            for i in range(2):
                c.call(f"via_proxy_{i}", "/hsstock/real/time/000001/{licence}")
            c.check_egress_stable(1)
            s4 = c.close_run()
            check("--use-env-proxy：请求改走代理（代理端口收到 3 个，目标收到 0 个）",
                  st_proxy.requests - px1 == 3 and st_api.requests == api1,
                  f"代理端口请求 +{st_proxy.requests - px1}；api +{st_api.requests - api1}；{s4['proxy_mode']}")
            check("代理测试输出不含证书",
                  _scan_dir_for_licence(ctx3.run_dir) == 0 and _scan_dir_for_licence(ctx4.run_dir) == 0)
        finally:
            for n, v in saved_env.items():
                if v is None:
                    os.environ.pop(n, None)
                else:
                    os.environ[n] = v
    finally:
        sys.stdout = old_stdout
        for srv in (srv_api, srv_pro, srv_echo, srv_proxy):
            srv.shutdown()
            srv.server_close()
        guard.uninstall()
    out = tee.buf.getvalue()
    real = os.environ.get("MAIRUI_LICENCE", "")
    check("控制台输出不含证书", c.DRY_RUN_LICENCE not in out and not (real and real in out))
    check("无任何非回环出网尝试（DNS/connect 均被拦截记录）", not guard.blocked, f"blocked={guard.blocked[:5]}")
    check("真实 results/STOP 状态未改变", _snapshot_stop() == stop_before,
          "存在" if stop_before[0] else "不存在")
    print("\n===== dry-run 自检结果 =====")
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    report = {"checks": [{"name": n, "pass": ok, "detail": d} for n, ok, d in checks],
              "api_server": {"connections": st_api.connections, "requests": st_api.requests},
              "pro_server": {"connections": st_pro.connections, "requests": st_pro.requests},
              "ip_echo_server": {"connections": st_echo.connections, "requests": st_echo.requests},
              "proxy_recorder": {"connections": st_proxy.connections, "requests": st_proxy.requests},
              "finished_at": c.now_iso()}
    c.write_new(ctx1.run_dir / "selftest.json", json.dumps(report, ensure_ascii=False, indent=1))
    all_ok = all(ok for _, ok, _ in checks)
    print("全部通过" if all_ok else "存在失败项")
    return 0 if all_ok else 1


def cli(argv=None) -> int:
    c.setup_console()
    ap = argparse.ArgumentParser(description="麦蕊 API 能力探测（串行、单长连接）")
    ap.add_argument("probes", nargs="*", help="探针前缀过滤，如 p01 p02；缺省为全部")
    ap.add_argument("--dry-run", action="store_true", help="离线自检：本地伪造服务端，不出网，不使用真实证书")
    ap.add_argument("--dry-interval", type=float, default=0.01, help="dry-run 调用间隔秒数（默认 0.01）")
    ap.add_argument("--min-interval", type=float, default=None,
                    help="真实运行调用间隔秒数（默认取 PROBE_MIN_INTERVAL 或 0.25）")
    ap.add_argument("--check-egress", action="store_true",
                    help="真实运行前自检出口 IP 是否固定（默认关闭；会访问公开 IP 回显服务）")
    ap.add_argument("--egress-rounds", type=int, default=3)
    ap.add_argument("--egress-url", default=c.EGRESS_URL, help="出口自检用的 IP 回显地址（默认 https://myip.ipip.net）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--no-env-proxy", dest="no_env_proxy", action="store_true", default=True,
                   help="（默认）忽略 HTTP(S)_PROXY/ALL_PROXY 与系统代理，本机直连")
    g.add_argument("--use-env-proxy", dest="no_env_proxy", action="store_false",
                   help="使用环境变量/系统代理（关闭 --no-env-proxy）")
    ap.add_argument("--skip-pro-host", action="store_true", help="跳过 pro.mairuiapi.com 的调用（只用一个主机）")
    args = ap.parse_args(argv)
    return dry_run(args) if args.dry_run else real_run(args)


if __name__ == "__main__":
    sys.exit(cli())
