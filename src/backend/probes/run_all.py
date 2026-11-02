"""串行依次运行全部探针：同一进程、同一 requests.Session、每个主机一条长连接、无并发、无子进程。

用法（证书只通过环境变量 MAIRUI_LICENCE 提供，详见 README.md）：
  python run_all.py --dry-run            # 离线自检：本地伪造服务端，不出网、不用真实证书
  python run_all.py                      # 真实运行全部探针
  python run_all.py p01 p02              # 只运行指定前缀的探针
  python run_all.py --check-egress       # 运行前用同一 Session 访问 myip.ipip.net 自检出口 IP 是否固定（默认关闭）
  python run_all.py --skip-pro-host      # 跳过 pro.mairuiapi.com 的 2 次调用，全程只连 api.mairuiapi.com
  python run_all.py --use-env-proxy      # 改为使用 HTTP(S)_PROXY/系统代理（默认 --no-env-proxy：忽略代理、本机直连）

T-B05 复测开关（缺省 = 原行为；调用次数见 README §6A）：
  python run_all.py p11 --p11-only gap1 --gap1-codes 000001,600519,300750,688981,920000 \
                    --ntp-file ntp_am_before.txt --ntp-file ntp_am_after.txt     # 复测 1：只跑 GAP1，5 只
  python run_all.py p11 --p11-only gap6-history [--history-baseline <run_id 或样例目录>]   # 复测 3：2 次
  python run_all.py p11 --p11-only gap6-nulls [--zt-codes 002001,603001]          # 复测 2：8 次
  python run_all.py p12 --p12-only hslt                                           # 复测 4：1 次
  python run_all.py p13 [--p13-restated 600525.SH]                                # T-R12/T-R12a ①–⑨：28 次（只点名运行）
  python p13_analyze.py results/run-<ts>                                          # 离线重算 p13 分析（不联网）

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
         "p06_factors", "p07_sector_index", "p08_news", "p11_gaps", "p12_code_lists", "p10_stability",
         "p09_ratelimit"]
# 只在显式点名时运行（不进缺省全量，缺省全量的调用次数不变）
OPT_IN = ["p13_fin_pit"]


def select(want: list) -> list:
    base = [m for m in ORDER if not want or any(m.startswith(w) for w in want)]
    return base + [m for m in OPT_IN if want and any(m.startswith(w) for w in want)]


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


def _load_gap_items(run_dir) -> dict:
    files = sorted(run_dir.glob("p11_gaps*.json"))
    items = {}
    if files:
        for x in json.loads(files[-1].read_text(encoding="utf-8")):
            if isinstance(x, dict) and str(x.get("name", "")).startswith("GAP") and "status" in x:
                items[x["name"]] = x
    return items


def _check_gaps(check, run_dir, expect_latency, want, label=""):
    """检查 p11_gaps 结果：缺省 7 项（GAP1–GAP7）；--p11-only 时只应有该模式的项，且不多不少。"""
    if "p11_gaps" not in want:
        return {}
    import p11_gaps as g
    items = _load_gap_items(run_dir)
    if g.ONLY is None:
        by_pre = {k.split("_")[0]: v for k, v in items.items()}
        need = [f"GAP{i}" for i in range(1, 8)]
        extra = []
    else:
        by_pre = dict(items)
        need = [x[0] for x in g.ONLY_PLAN[g.ONLY]]
        extra = [k for k in items if k not in need]
    struct_ok = not extra and all(k in by_pre and isinstance(by_pre[k].get("conclusion"), dict) and by_pre[k][
        "status"] in ("measured", "skipped", "inconclusive") and "limits" in by_pre[k] for k in need)
    check(f"p11{label}：{len(need)} 项补测均输出结构化结论（status/conclusion/evidence/limits）"
          + ("" if g.ONLY is None else f"，且只有 --p11-only {g.ONLY} 的项"), struct_ok,
          ", ".join(f"{k}={by_pre[k]['status']}" if k in by_pre else f"{k}=缺失" for k in need)
          + (f"；多余 {extra}" if extra else ""))
    if expect_latency is not None:
        g1 = by_pre.get("GAP1") or by_pre.get("GAP1_snapshot_latency")
        check(f"p11{label}：快照延迟项状态 = {expect_latency}", g1 is not None and g1["status"] == expect_latency,
              (g1 or {}).get("conclusion", {}).get("summary", "")[:160])
    return items


def _p12_expected_calls(sel) -> int:
    """p12 在本次选择下应实际调用几次：可复用的接口（p01 的两个全市场、p11 GAP4 的 /hslt/list）不再调用。"""
    import p11_gaps as g
    import p12_code_lists as p12
    reusable = set()
    if "p01_realtime" in sel:
        reusable |= {"hsrl_ssjy_all", "hsrl_real_all"}
    if "p11_gaps" in sel and g.ONLY is None:
        reusable.add("hslt_list")
    return sum(1 for e in p12.active_endpoints() if e[0] not in reusable)


SWITCH_DEFAULTS = {}     # apply_switches 首次调用前的模块变量，开关矩阵用来复原


def apply_switches(args) -> dict:
    """把命令行开关写进 p11_gaps / p12_code_lists 的模块变量；非法输入抛 ValueError（cli 返回 2）。
    只读本地文件（--ntp-file、--history-baseline），不发任何请求。返回本次生效的开关（写进日志）。"""
    import p11_gaps as g
    import p12_code_lists as p12
    if not SWITCH_DEFAULTS:
        SWITCH_DEFAULTS.update({
            "g": {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                  for k, v in vars(g).items() if k in ("LAT_CODES", "ONLY", "LOCAL_AHEAD_S", "NTP_SOURCES",
                                                       "NTP_RAW", "HISTORY_BASELINE", "ZT_CODES", "PIT_BATCH_DAY")},
            "p12": {"ONLY_KEYS": p12.ONLY_KEYS}, "p13": {"RESTATED": dict(_p13().RESTATED)}})
    cfg = {}
    if args.gap1_codes:
        codes = g.parse_codes(args.gap1_codes)
        if not 1 <= len(codes) <= g.LAT_MAX_CODES:
            raise ValueError(f"--gap1-codes 需要 1–{g.LAT_MAX_CODES} 只，给了 {len(codes)} 只")
        g.LAT_CODES = codes
        cfg["gap1_codes"] = codes
    if args.p11_only:
        g.ONLY = args.p11_only
        cfg["p11_only"] = args.p11_only
    ahead, srcs, raw = [], [], {}
    for v in args.local_ahead_s or []:
        ahead.append(float(v))
        srcs.append(f"--local-ahead-s {float(v)}")
    for f in args.ntp_file or []:
        fp = Path(f)
        if not fp.is_file():
            raise ValueError(f"--ntp-file 不存在：{f}")
        txt = fp.read_text(encoding="utf-8", errors="replace")
        vals = g.parse_w32tm(txt)
        if not vals:
            raise ValueError(f"--ntp-file 里没有可解析的 w32tm 偏差行：{f}")
        ahead.append(sum(vals) / len(vals))
        srcs.append(f"{fp.name}（{len(vals)} 个样本）")
        raw[fp.name] = txt[:4000]
    if ahead:
        g.LOCAL_AHEAD_S, g.NTP_SOURCES, g.NTP_RAW = ahead, srcs, raw
        cfg["local_ahead_s"] = ahead
    if args.history_baseline:
        g.HISTORY_BASELINE = args.history_baseline
        cfg["history_baseline"] = args.history_baseline
        bd = g._baseline_dir()
        if bd is None or not bd.is_dir():
            raise ValueError(f"--history-baseline 找不到目录：{args.history_baseline}")
    if args.zt_codes:
        g.ZT_CODES = g.parse_codes(args.zt_codes)
        cfg["zt_codes"] = g.ZT_CODES
    if args.p12_only:
        p12.ONLY_KEYS = p12.ONLY_CHOICES[args.p12_only]
        cfg["p12_only"] = args.p12_only
    if getattr(args, "p13_restated", None):
        code = args.p13_restated.strip().upper()
        if not __import__("re").fullmatch(r"\d{6}\.(SH|SZ|BJ)", code):
            raise ValueError(f"--p13-restated 需要 6 位代码加 .SH/.SZ/.BJ，给了 {args.p13_restated!r}")
        _p13().RESTATED = {**_p13().RESTATED, "code": code}
        if args.p13_announce:
            _p13().RESTATED["announce"] = args.p13_announce
        if args.p13_periods:
            _p13().RESTATED["periods"] = [x.strip() for x in args.p13_periods.split(",") if x.strip()]
        cfg["p13_restated"] = _p13().RESTATED
    elif getattr(args, "p13_announce", None) or getattr(args, "p13_periods", None):
        raise ValueError("--p13-announce / --p13-periods 只配合 --p13-restated")
    if (args.history_baseline and g.ONLY != "gap6-history") or (args.zt_codes and g.ONLY != "gap6-nulls"):
        raise ValueError("--history-baseline 只配合 --p11-only gap6-history；--zt-codes 只配合 --p11-only gap6-nulls")
    return cfg


def _p13():
    import p13_fin_pit
    return p13_fin_pit


def restore_switches():
    import p11_gaps as g
    import p12_code_lists as p12
    for k, v in SWITCH_DEFAULTS.get("p13", {}).items():
        setattr(_p13(), k, dict(v))
    for k, v in SWITCH_DEFAULTS.get("g", {}).items():
        setattr(g, k, list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
    for k, v in SWITCH_DEFAULTS.get("p12", {}).items():
        setattr(p12, k, v)


def _check_codes(check, run_dir, want, expect_calls, label):
    """检查 p12_code_lists：本次启用的接口（缺省 5 个；--p12-only hslt 时 1 个）原始响应 + codes.csv + dm 文本可被 compare_mairui_codes.py 直接读取。"""
    if "p12_code_lists" not in want:
        return
    import csv
    import hashlib
    import p12_code_lists as p12
    files = sorted(run_dir.glob("p12_code_lists*.json"))
    items = json.loads(files[-1].read_text(encoding="utf-8")) if files else []
    per = {x["name"][6:]: x for x in items if isinstance(x, dict) and str(x.get("name", "")).startswith("CODES_")
           and x["name"] != "CODES_SUMMARY"}
    summ = next((x for x in items if isinstance(x, dict) and x.get("name") == "CODES_SUMMARY"), {})
    keys = [e[0] for e in p12.active_endpoints()]
    check(f"p12（{label}）：{len(keys)} 个接口均有记录且成功、没有多余接口", all(k in per and per[k]["ok"] for k in keys) and set(per) == set(keys),
          ", ".join(f"{k}={per[k]['rows']}行/{per[k]['source']}" if k in per else f"{k}=缺失" for k in keys))
    raw_ok, dm_ok, detail = True, True, []
    for k in keys:
        x = per.get(k) or {}
        rp = run_dir / (x.get("raw_file") or "_missing_")
        try:
            b = rp.read_bytes()
            json.loads(b.decode("utf-8"))
            raw_ok &= hashlib.sha256(b).hexdigest() == x.get("sha256")
        except (OSError, ValueError):
            raw_ok = False
        dp = run_dir / (x.get("dm_file") or "_missing_")
        try:
            # 与 /tmp/t7/compare_mairui_codes.py 完全相同的读法：每行一个 dm，strip 后去空行
            m = {ln.strip() for ln in open(dp, encoding="utf-8") if ln.strip()}
            dm_ok &= len(m) == x.get("codes_6digit") and all(len(v) == 6 and v.isdigit() for v in m)
            detail.append(f"{k}={len(m)}")
        except OSError:
            dm_ok = False
    check(f"p12（{label}）：原始响应 JSON 可解析且 sha256 与记录一致", raw_ok)
    lists = {ln.strip() for ln in open(run_dir / (summ.get("lists_union_file") or "_x_"), encoding="utf-8")
             if ln.strip()} if summ.get("lists_union_file") else set()
    check(f"p12（{label}）：dm 文本按 compare 脚本读法得到 6 位代码集合", dm_ok and len(lists) == summ.get("lists_union_n"),
          "; ".join(detail) + f"; lists∪={len(lists)}")
    try:
        with open(run_dir / summ["csv_file"], encoding="utf-8", newline="") as f:
            rd = csv.DictReader(f)
            n_csv, hdr = sum(1 for _ in rd), rd.fieldnames
    except (OSError, KeyError):
        n_csv, hdr = -1, None
    check(f"p12（{label}）：codes.csv 表头与行数正确", hdr == p12.CSV_FIELDS and n_csv == sum(
        per[k]["rows"] for k in keys if k in per), f"rows={n_csv}")
    check(f"p12（{label}）：实际调用 {expect_calls} 次（其余复用）", summ.get("calls_made") == expect_calls,
          f"calls_made={summ.get('calls_made')} reused={summ.get('reused')}")


def _switch_matrix(check, args, st_api, st_pro, base_api, base_pro, echo_url):
    import tempfile

    import p11_gaps as g
    import p12_code_lists as p12
    saved_cli = {k: getattr(g, k) for k in ("LAT_CODES", "ONLY", "LOCAL_AHEAD_S", "NTP_SOURCES", "NTP_RAW",
                                            "HISTORY_BASELINE", "ZT_CODES")}
    saved_p12 = p12.ONLY_KEYS
    tmp = Path(tempfile.mkdtemp(prefix="tb05-ntp-"))
    (tmp / "ntp_before.txt").write_text(
        "Tracking ntp.aliyun.com [203.0.113.123:123].\nCollecting 3 samples.\n"
        "09:20:01, +01.5000000s\n09:20:03, +01.4000000s\n09:20:05, +01.6000000s\n", encoding="utf-8")
    (tmp / "ntp_after.txt").write_text("11:31:01, +01.5000000s\n11:31:03, error: 0x800705B4\n", encoding="utf-8")

    def one(label, argv, probes, expect_calls, force_session=None):
        restore_switches()
        cfg = apply_switches(_switch_args(argv))
        g.FORCE_SESSION = force_session
        ctx = c.init_run(dry_run=True, base=base_api, pro_base=base_pro, min_interval=args.dry_interval,
                         skip_pro_host=True, no_env_proxy=args.no_env_proxy, egress_url=echo_url,
                         tag=f"dryrun-switch-{label}")
        print(f"[dry-run] 阶段 5 开关 {label} {cfg}，输出目录 {ctx.run_dir}")
        a0, p0 = st_api.requests, st_pro.requests
        ok = run_probes(probes)
        s = c.close_run()
        delta = st_api.requests - a0 + st_pro.requests - p0
        check(f"开关 {label}：客户端 {expect_calls} 次 = 服务端增量、未熔断",
              ok and s["calls"] == expect_calls and delta == expect_calls,
              f"client={s['calls']} server=+{delta} argv={' '.join(argv)}")
        check(f"开关 {label}：输出不含证书", _scan_dir_for_licence(ctx.run_dir) == 0)
        return ctx

    try:
        five = "000001,600519,300750,688981,920000"
        # 复测 1：GAP1 5 只 + NTP 文件；盘中 1 + 5×2×6 = 61 次；盘后 0 次
        ctx = one("gap1", ["--p11-only", "gap1", "--gap1-codes", five, "--ntp-file", str(tmp / "ntp_before.txt"),
                           "--ntp-file", str(tmp / "ntp_after.txt")], ["p11_gaps"], 1 + 5 * 2 * g.LAT_SAMPLES, True)
        items = _check_gaps(check, ctx.run_dir, "measured", ["p11_gaps"], "（开关 gap1）")
        cc = (items.get("GAP1_snapshot_latency") or {}).get("conclusion", {})
        st_ = cc.get("stale_threshold") or {}
        check("开关 gap1：5 只 × 2 源分别给分位数；未修正与 NTP 修正两套；stale 参考 = 修正后 p95",
              len(cc.get("per_source_stock") or {}) == 10 and cc.get("codes") == five.split(",")
              and all(v.get("ntp_corrected", {}).get("p95") is not None for v in (cc.get("per_source") or {}).values())
              and st_.get("basis") == "ntp_corrected_p95"
              and abs((cc.get("ntp_offset") or {}).get("local_ahead_s", 0) - 1.5) < 1e-9,
              f"stale={st_} ntp={(cc.get('ntp_offset') or {}).get('local_ahead_s')}")
        ctx = one("gap1-afterhours", ["--p11-only", "gap1", "--gap1-codes", five], ["p11_gaps"], 0, False)
        _check_gaps(check, ctx.run_dir, "skipped", ["p11_gaps"], "（开关 gap1 盘后）")
        # 复测 3：GAP6 history only，先取基线，再以基线目录比对（各 2 次，比对离线）
        ctx_a = one("gap6-history", ["--p11-only", "gap6-history"], ["p11_gaps"], 2)
        ia = _check_gaps(check, ctx_a.run_dir, None, ["p11_gaps"], "（开关 gap6-history）")
        ctx_b = one("gap6-history-baseline", ["--p11-only", "gap6-history", "--history-baseline",
                                              str(ctx_a.samples_dir)], ["p11_gaps"], 2)
        ib = _check_gaps(check, ctx_b.run_dir, None, ["p11_gaps"], "（开关 gap6-history+基线）")
        vb = (ib.get("GAP6_history_only") or {}).get("conclusion", {})
        check("开关 gap6-history：首次作为基线；带基线复取逐日比对 → no_rewrite（mock 序列不变）",
              (ia.get("GAP6_history_only") or {}).get("status") == "measured"
              and vb.get("verdict") == {f: "no_rewrite" for f in g.PIT_FACTORS},
              str(vb.get("verdict")))
        # 复测 2：空值复测，1 次涨停池 + 2 只涨停股 + 5 只原样本 = 8 次
        ctx = one("gap6-nulls", ["--p11-only", "gap6-nulls"], ["p11_gaps"], 1 + g.NULLS_ZT_PICK
                  + len(g.NULLS_BASE_CODES))
        inl = _check_gaps(check, ctx.run_dir, None, ["p11_gaps"], "（开关 gap6-nulls）")
        cn = (inl.get("GAP6_nulls_retest") or {}).get("conclusion", {})
        smp = cn.get("limit_up_sampling") or {}
        check("开关 gap6-nulls：只选取样时刻前已封板的涨停股、记录取样时刻、排除原样本",
              cn.get("zt_codes") == ["002001", "603001"] and smp.get("sampled_at_bj")
              and smp.get("rejected", {}).get("fbt_after_sample") == 1 and smp.get("rejected", {}).get("no_fbt") == 1
              and smp.get("rejected", {}).get("excluded") == 1,
              f"zt={cn.get('zt_codes')} sampled_at={smp.get('sampled_at_bj')} rejected={smp.get('rejected')}")
        one("gap6-nulls-zt-codes", ["--p11-only", "gap6-nulls", "--zt-codes", "002001,603001"], ["p11_gaps"],
            1 + 2 + len(g.NULLS_BASE_CODES))
        # 复测 4：p12 只取 /hslt/list：单独 1 次；与完整 p11 同次运行时复用 GAP4（p12 为 0 次）
        ctx = one("p12-hslt", ["--p12-only", "hslt"], ["p12_code_lists"], 1)
        _check_codes(check, ctx.run_dir, ["p12_code_lists"], 1, "开关 hslt 单独")
        restore_switches()
        apply_switches(_switch_args(["--p12-only", "hslt"]))
        g.FORCE_SESSION = False
        ctx = c.init_run(dry_run=True, base=base_api, pro_base=base_pro, min_interval=args.dry_interval,
                         skip_pro_host=True, no_env_proxy=args.no_env_proxy, egress_url=echo_url,
                         tag="dryrun-switch-p11-p12-hslt")
        run_probes(["p11_gaps", "p12_code_lists"])
        c.close_run()
        _check_codes(check, ctx.run_dir, ["p12_code_lists"], 0, "开关 hslt 与 p11 同次运行")
        # 非法输入 → ValueError（cli 返回 2）
        bad = []
        for argv in (["--gap1-codes", "1234567"], ["--gap1-codes", ",".join(f"{i:06d}" for i in range(11))],
                     ["--ntp-file", str(tmp / "missing.txt")], ["--history-baseline", "x", "--p11-only", "gap1"]):
            restore_switches()
            try:
                apply_switches(_switch_args(argv))
                bad.append(argv)
            except ValueError:
                pass
        check("开关参数非法时拒绝（返回 2，不发请求）", not bad, f"未拒绝：{bad}")
    finally:
        restore_switches()
        for k, v in saved_cli.items():
            setattr(g, k, v)
        p12.ONLY_KEYS = saved_p12
        g.FORCE_SESSION = None


P13_EXPECT_CALLS = 28


def _p13_phase(check, args, st_api, st_pro, base_api, base_pro, echo_url):
    import hashlib
    import p13_analyze as an
    p13 = _p13()
    check("p13：缺省全量不含 p13（只点名运行）", "p13_fin_pit" not in select([]) and "p13_fin_pit" in select(["p13"]))
    for label, argv, restated in (("p13", [], "600525.SH"), ("p13-restated", ["--p13-restated", "600590.SH",
                                  "--p13-announce", "2024-11-09", "--p13-periods", "2023-12-31,2024-06-30"],
                                  "600590.SH")):
        restore_switches()
        apply_switches(_switch_args(argv))
        ctx = c.init_run(dry_run=True, base=base_api, pro_base=base_pro, min_interval=args.dry_interval,
                         skip_pro_host=args.skip_pro_host, no_env_proxy=args.no_env_proxy, egress_url=echo_url,
                         tag=f"dryrun-{label}")
        print(f"[dry-run] 阶段 6 {label}，输出目录 {ctx.run_dir}")
        a0, p0 = st_api.requests, st_pro.requests
        ok = run_probes(["p13_fin_pit"])
        s = c.close_run()
        delta = st_api.requests - a0 + st_pro.requests - p0
        check(f"{label}：未熔断且客户端 {P13_EXPECT_CALLS} 次 = 服务端增量",
              ok and s["calls"] == P13_EXPECT_CALLS == delta, f"client={s['calls']} server=+{delta}")
        sub = ctx.run_dir / p13.SUBDIR
        try:
            man = json.loads((sub / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            man = []
        good = bool(man)
        for e in man:
            try:
                b = (ctx.run_dir / e["raw_file"]).read_bytes()
                good &= hashlib.sha256(b).hexdigest() == e["sha256"] and e["ok"]
            except (OSError, KeyError):
                good = False
        check(f"{label}：manifest {len(man)} 条，原始响应齐全、sha256 一致、全部 200", good and len(man) == P13_EXPECT_CALLS)
        items = {x for e in man for x in e.get("item", "")}
        check(f"{label}：条目 ①–⑨ 都有调用", set("①②③④⑤⑥⑦⑧⑨") <= items, "".join(sorted(items)))
        rs_ok = any(e["key"] == f"income_{restated[:6]}" for e in man)
        check(f"{label}：更正样例公司 = {restated}（③ income 已取）", rs_ok)
        try:
            a = json.loads((ctx.run_dir / "p13_analysis.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            a = {}
        meta = json.loads((sub / "plan_meta.json").read_text(encoding="utf-8")) if (sub / "plan_meta.json").exists() else {}
        again = json.loads(json.dumps(an.analyze(an.load_raw(ctx.run_dir), meta), ensure_ascii=False, default=str))
        check(f"{label}：p13_analysis.json 存在且与离线脚本对原始文件重算结果一致", bool(a) and a == again)
        if label == "p13":
            cf = a.get("1_cashflow", {})
            check("p13 mock：① 银行 OCF 走 jyhdcsdxjlje、一般企业走 jyhdcsdxjlxj、累计口径判定 ytd",
                  cf.get("000001", {}).get("ocf_field_used_latest", {}).get("jyhdcsdxjlje", 0) > 0
                  and cf.get("600519", {}).get("ocf_field_used_latest", {}).get("jyhdcsdxjlxj", 0) > 0
                  and cf.get("600519", {}).get("ytd", {}).get("verdict") == "ytd_cumulative")
            b = a.get("4_capital", {}).get("600519_bonus_2011", {})
            check("p13 mock：④ 600519 2011-07-01 股本行被找到", b.get("first_after_bdrq_eq_ex_date") is True,
                  str(b.get("first_row_on_or_after")))
            sc = a.get("7_share_class", {})
            check("p13 mock：⑦ 601318 判定 includes_non_a、000550 判定 includes_non_a",
                  sc.get("601318_A+H", {}).get("verdict") == "includes_non_a"
                  and sc.get("000550_A+B", {}).get("verdict") == "includes_non_a")
            v = a.get("8_dividend", {}).get("visibility", {})
            check("p13 mock：⑧ 两个送转事件都匹配到股本行", sum(x.get("matched", 0) for x in v.values()) == 2,
                  json.dumps({k: x.get("decision") for k, x in v.items()}, ensure_ascii=False))
            check("p13 mock：⑧ 总判定 = must_integrate_dividend_feed（mock 000001 股本行晚于除权日）",
                  a.get("8_dividend", {}).get("overall_decision") == "must_integrate_dividend_feed")
            cu = a.get("9_currency_unit", {})
            check("p13 mock：⑨ 无币种/单位字段 → 结论“只靠数量级不连续检查”",
                  not cu.get("fields_found") and "只靠数量级不连续检查" in (cu.get("conclusion") or ""),
                  str(cu.get("fields_found")))
            reasons = {x["basis"].get("null_reason") for xs in a.get("6_pb", {}).values() for x in xs}
            check("p13 mock：⑥ null_reason 只取 plan 2.12.1 封闭 14 码", reasons - {None} <= set(an.NULL_REASONS)
                  and len(an.NULL_REASONS) == 14, str(reasons))
            pb = a.get("6_pb", {})
            check("p13 mock：⑥ 三只 PB 均有值且 basis 含 zgb_bdrq/mcap_basis",
                  all(x and x[-1].get("value") and x[-1]["basis"].get("zgb_bdrq") for x in pb.values()) and len(pb) == 3)
            sw = a.get("5_sw", {})
            check("p13 mock：⑤ 识别出银行/保险节点与申万二级", sw.get("has_sw_l2") and sw.get("bank_nodes")
                  and sw.get("insurance_nodes"))
        check(f"{label}：输出不含证书", _scan_dir_for_licence(ctx.run_dir) == 0)
    restore_switches()
    check("p13：开关复原（更正样例回到 600525.SH）", p13.RESTATED["code"] == "600525.SH")
    for n_, ok_, d_ in an.selftest_pure():
        check("p13 纯函数单测：" + n_, ok_, d_)


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
        import p11_gaps as _g
        _check_gaps(check, ctx1.run_dir, expect_latency="measured" if _g.ONLY in (None, "gap1") else None,
                    want=select(args.probes))
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
        if "p11_gaps" in select(args.probes) and p11_gaps.ONLY in (None, "gap1"):
            p11_gaps.FORCE_SESSION = False
            ctx1b = c.init_run(dry_run=True, base=base_api, pro_base=base_pro, min_interval=args.dry_interval,
                               skip_pro_host=args.skip_pro_host, no_env_proxy=args.no_env_proxy,
                               egress_url=echo_url, tag="dryrun-p11-afterhours")
            print(f"[dry-run] 阶段 1b p11 盘后分支，输出目录 {ctx1b.run_dir}")
            run_probes(["p11_gaps"])
            s1b = c.close_run()
            _check_gaps(check, ctx1b.run_dir, expect_latency="skipped", want=["p11_gaps"])
            names = [json.loads(x).get("name", "") for x in ctx1b.call_log.read_text(encoding="utf-8").splitlines()] \
                if ctx1b.call_log.exists() else []     # --p11-only gap1 盘后 0 次调用时不生成 calls.jsonl
            check("p11 盘后：不发快照延迟采样请求（lat_*/tcalendar 为 0）",
                  not any(n.startswith("lat_") or n.startswith("tcalendar") for n in names),
                  f"本阶段调用 {s1b['calls']} 次")
            check("p11 输出不含证书", _scan_dir_for_licence(ctx1b.run_dir) == 0)
            p11_gaps.FORCE_SESSION = None
        if "p11_gaps" in select(args.probes):
            for n_, ok_, d_ in p11_gaps.selftest_pure():
                check("p11 纯函数单测：" + n_, ok_, d_)
        # ---- p12：阶段 1 中复用 p01/p11 的响应，只新增 2 次调用（开关生效时按启用接口重算）
        sel = select(args.probes)
        exp12 = _p12_expected_calls(sel)
        _check_codes(check, ctx1.run_dir, sel, exp12, "全流程")
        import p12_code_lists as _p12
        if "p12_code_lists" in sel and _p12.ONLY_KEYS is None and p11_gaps.ONLY is None \
                and "p01_realtime" in sel:
            import p12_code_lists
            n12 = [json.loads(x).get("name", "") for x in ctx1.call_log.read_text(encoding="utf-8").splitlines()]
            check("p12（全流程）：/hslt/list、两个全市场接口在本次运行中各只调用 1 次",
                  all(sum(1 for n in n12 if n == nm) == 1 for nm in
                      ("delisted_stock_list", "ssjy_all_broker", "real_all_network"))
                  and not any(n in ("code_list_hslt_list", "code_list_hsrl_ssjy_all", "code_list_hsrl_real_all")
                              for n in n12))
            # ---- 阶段 1c：单独运行 p12（没有可复用的响应）→ 自己调用 5 次
            ctx1c = c.init_run(dry_run=True, base=base_api, pro_base=base_pro, min_interval=args.dry_interval,
                               skip_pro_host=args.skip_pro_host, no_env_proxy=args.no_env_proxy,
                               egress_url=echo_url, tag="dryrun-p12-alone")
            print(f"[dry-run] 阶段 1c 单独运行 p12，输出目录 {ctx1c.run_dir}")
            a0 = st_api.requests
            run_probes(["p12_code_lists"])
            s1c = c.close_run()
            _check_codes(check, ctx1c.run_dir, ["p12_code_lists"], 5, "单独运行")
            check("p12（单独运行）：客户端 5 次 = 服务端 +5", s1c["calls"] == 5 and st_api.requests - a0 == 5,
                  f"client={s1c['calls']} server=+{st_api.requests - a0}")
            check("p12 输出不含证书", _scan_dir_for_licence(ctx1c.run_dir) == 0)
            for n_, ok_, d_ in p12_code_lists.selftest_pure():
                check("p12 纯函数单测：" + n_, ok_, d_)
        # ---- 阶段 5：T-B05 开关矩阵（每个开关单独跑，核对调用次数 = 服务端增量、结构、无证书；跑完复原）
        if not args.skip_switch_matrix:
            _switch_matrix(check, args, st_api, st_pro, base_api, base_pro, echo_url)
        # ---- 阶段 6：p13（T-R12/T-R12a）只点名运行：28 次 = 服务端增量、原始响应完整、离线分析可复算
        if not args.skip_switch_matrix or "p13_fin_pit" in select(args.probes):
            _p13_phase(check, args, st_api, st_pro, base_api, base_pro, echo_url)
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
    ap.add_argument("--skip-switch-matrix", action="store_true", help="dry-run 不跑 T-B05 开关矩阵（默认会跑）")
    add_switch_args(ap)
    args = ap.parse_args(argv)
    try:
        cfg = apply_switches(args)
    except ValueError as e:
        print(f"开关参数错误：{e}")
        return 2
    if cfg:
        print("T-B05 开关：" + json.dumps(cfg, ensure_ascii=False))
    return dry_run(args) if args.dry_run else real_run(args)


def add_switch_args(ap):
    s = ap.add_argument_group("T-B05 复测开关（缺省 = 原行为）")
    s.add_argument("--gap1-codes", help="GAP1 采样股票，逗号分隔 6 位代码（≤10 只），如 000001,600519,300750,688981,920000")
    s.add_argument("--p11-only", choices=("gap1", "gap6-history", "gap6-nulls"),
                   help="p11 只跑一项：gap1=快照延迟；gap6-history=因子历史复取(2 次)；gap6-nulls=空值复测(8 次)")
    s.add_argument("--local-ahead-s", type=float, action="append",
                   help="本机比 NTP 快的秒数（本机−NTP），可给多次取均值；用于 GAP1 修正延迟")
    s.add_argument("--ntp-file", action="append",
                   help="w32tm /stripchart ... /dataonly 的输出文件，可给多次（时段前、后）；只读本地文件")
    s.add_argument("--history-baseline", help="gap6-history 比对基线：样例目录或真实运行的 run_id（只读本地文件）")
    s.add_argument("--zt-codes", help="gap6-nulls 收盘后复跑：沿用盘中选出的涨停股代码")
    s.add_argument("--p12-only", choices=("hslt",), help="p12 只取 /hslt/list（同次运行 p11 GAP4 已取过则复用 0 次）")
    s.add_argument("--p13-restated", help="p13 ③ 差错更正样例公司（缺省 600525.SH 长园集团），如 600590.SH")
    s.add_argument("--p13-announce", help="配合 --p13-restated：更正公告日 YYYY-MM-DD")
    s.add_argument("--p13-periods", help="配合 --p13-restated：受影响报告期，逗号分隔 YYYY-MM-DD")


def _switch_args(argv):
    ap = argparse.ArgumentParser(add_help=False)
    add_switch_args(ap)
    return ap.parse_args(argv)


if __name__ == "__main__":
    sys.exit(cli())
