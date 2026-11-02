# ruff: noqa: E501  自检脚本：检查描述保持单行，便于对照输出
"""T-B05 准备自检：精度差规则收紧（反例）、factor/batch 数据日期裁定、复测开关的参数解析与纯函数。

不连数据库、不出网（全程套 ``p11_replay.no_network``），不读取证书；环境里有证书变量直接拒绝运行。
开关的端到端调用次数在 ``probes/run_all.py --dry-run`` 的“阶段 5 开关矩阵”里核对（本地伪造服务端）。

运行（目录 ``src/backend``）::

    env -u MAIRUI_LICENCE python3 selfchecks/tb05_switches.py [运行目录]

输出逐条 ``PASS`` / ``FAIL`` / ``SKIP``，最后一行 ``N passed, M failed, K skipped``；有 FAIL 时退出码 1。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

if os.environ.get("MAIRUI_" + "LICENCE"):
    sys.exit("自检拒绝运行：环境里有证书变量（请 env -u 该变量）")

PROBES = Path(__file__).resolve().parents[1] / "probes"
sys.path.insert(0, str(PROBES))

import p11_gaps as g  # noqa: E402
import p11_replay as rp  # noqa: E402
import p12_code_lists as p12  # noqa: E402
import run_all as ra  # noqa: E402

RESULTS = {"pass": 0, "fail": 0, "skip": 0}


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS["pass" if ok else "fail"] += 1
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))


def skip(name: str, why: str) -> None:
    RESULTS["skip"] += 1
    print(f"SKIP {name} — {why}")


class FakeResp:
    def __init__(self, data: object) -> None:
        self.data, self.ok, self.status, self.text, self.headers, self.ms = (
            data,
            True,
            200,
            "",
            {},
            1.0,
        )
        self.url_redacted, self.error = "http://fake/***", None


def precision_cases() -> None:
    check(
        "精度差：反例 15.0→14.97 不算",
        not g.precision_only(15.0, 14.97) and not g.precision_only(14.97, 15.0),
    )
    check(
        "精度差：1.4714182949831487↔1.471418 算（截断 6 位）",
        g.precision_only(1.4714182949831487, 1.471418),
    )
    check("精度差：82.98214819072565↔82.982148 算", g.precision_only(82.98214819072565, 82.982148))
    check("精度差：四舍五入到 4 位 2.12345678↔2.1235 算", g.precision_only(2.12345678, 2.1235))
    check(
        "精度差：1.4714182949831487↔1.471419（既非截断也非舍入）不算",
        not g.precision_only(1.4714182949831487, 1.471419),
    )
    check(
        "精度差：较短一方不足 4 位（1.47、100.0↔99.99999）不算",
        not g.precision_only(1.4714182949831487, 1.47) and not g.precision_only(100.0, 99.99999),
    )
    check("精度差：小数位相同（1.471418↔1.471419）不算", not g.precision_only(1.471418, 1.471419))
    pit = g.classify_pit(
        g.change_points([("2026-04-01", 15.0), ("2026-04-02", 14.97)]),
        [{"jzrq": "2026-03-31", "plrq": "2026-04-28"}],
    )
    check(
        "精度差：15.0→14.97 在披露前 → 计入真实跳变，判前视嫌疑",
        pit["counts"]["precision_only"] == 0 and pit["verdict"] == "lookahead_suspected",
        str(pit["counts"]),
    )


def asof_cases() -> None:
    real = {
        "code": 200,
        "data": {
            "items": {"600519": {"profit_yoy": 6.2, "roe_ttm": 90.1}},
            "trade_date": "20260130",
        },
    }
    a = g.batch_asof("2026-01-30", *g.batch_dates(real, "600519"))
    check(
        "as-of：请求日 = 响应日 → ok、用于回填、来源 response",
        a["status"] == "ok" and a["use_for_backfill"] and a["date_source"] == "response",
        str(a),
    )
    a = g.batch_asof("2026-04-17", *g.batch_dates(real, "600519"))
    check(
        "as-of：请求 2026-04-17、响应 20260130 → as_of_mismatch、不回填、data_date 取响应",
        a["status"] == "as_of_mismatch"
        and not a["use_for_backfill"]
        and a["data_date"] == "2026-01-30"
        and a["reason"] == "data_date_differs_from_request",
        str(a),
    )
    a = g.batch_asof(
        "2026-01-30", *g.batch_dates({"data": {"items": {"600519": {"roe_ttm": 1}}}}, "600519")
    )
    check(
        "as-of：响应不带日期 → as_of_mismatch（missing_data_date）",
        a["status"] == "as_of_mismatch"
        and a["reason"] == "missing_data_date"
        and a["data_date"] is None,
        str(a),
    )
    a = g.batch_asof(
        "2026-01-30",
        *g.batch_dates(
            {
                "data": {
                    "trade_date": "20260130",
                    "items": [{"code": "600519", "trade_date": "20260129", "roe_ttm": 1}],
                }
            },
            "600519",
        ),
    )
    check(
        "as-of：记录层日期与响应层不同 → as_of_mismatch（record_vs_response_differ）",
        a["reason"] == "record_vs_response_differ" and not a["use_for_backfill"],
        str(a),
    )
    a = g.batch_asof(
        "2026-01-30",
        *g.batch_dates(
            {
                "data": {
                    "items": [
                        {"code": "600519", "factors": {"trade_date": "2026-01-30", "roe_ttm": 1}}
                    ]
                }
            },
            "600519",
        ),
    )
    check(
        "as-of：记录自带日期（含 factors 内）优先 → 来源 record",
        a["status"] == "ok" and a["date_source"] == "record",
        str(a),
    )
    # item67 集成：batch 返回别的日期 → equal=null、batch_as_of 记录 mismatch
    hist = {
        "code": 200,
        "data": {
            "list": [
                {"trade_date": "20260130", "value": 1.0},
                {"trade_date": "20260417", "value": 2.0},
            ]
        },
    }
    fx = {
        "factor_list": FakeResp({"data": [{"factor_id": "pe_ttm"}]}),
        "pit_batch_hist_date": FakeResp(
            {
                "code": 200,
                "data": {
                    "trade_date": "20260130",
                    "items": {"600519": dict.fromkeys(g.PIT_FACTORS, 1.0)},
                },
            }
        ),
    }
    for fid in g.PIT_FACTORS:
        fx[f"pit_history_{fid}_600519"] = FakeResp(hist)

    def fake_probe(res: list, name: str, *a: object, **k: object) -> FakeResp:
        return fx.get(name) or FakeResp(
            {"code": 200, "data": {"code": "600519", "factors": {"pe_ttm": 1.0}}}
        )

    out: list = []
    saved, saved_day = g.probe, g.PIT_BATCH_DAY
    g.probe, g.PIT_BATCH_DAY = fake_probe, "2026-04-17"
    try:
        g.item67_factors(out, {"income_600519": []})
    finally:
        g.probe, g.PIT_BATCH_DAY = saved, saved_day
    c6 = next(x for x in out if x["name"].startswith("GAP6"))["conclusion"]
    cmp_ = c6["history_vs_batch_same_day"]
    check(
        "as-of 集成：GAP6 记录 batch_as_of=as_of_mismatch，逐因子 equal=null（不参与比对/回填）",
        c6["batch_as_of"]["status"] == "as_of_mismatch"
        and all(
            v["equal"] is None and v["as_of_status"] == "as_of_mismatch" for v in cmp_.values()
        ),
        str(c6["batch_as_of"]),
    )


def switch_cases() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="tb05-sc-"))
    (tmp / "ntp.txt").write_text(
        "09:20:01, +01.5000000s\n09:20:03, +01.7000000s\n", encoding="utf-8"
    )
    hb = tmp / "base"
    hb.mkdir()
    (hb / "p11_pit_history_profit_yoy_600519.json").write_text("{}", encoding="utf-8")
    try:
        cfg = ra.apply_switches(
            ra._switch_args(
                [
                    "--p11-only",
                    "gap1",
                    "--gap1-codes",
                    "000001,600519,300750,688981,920000",
                    "--ntp-file",
                    str(tmp / "ntp.txt"),
                    "--local-ahead-s",
                    "1.0",
                ]
            )
        )
        check(
            "开关：gap1 + 5 只 + NTP 文件/命令行 → 模块变量生效",
            g.ONLY == "gap1"
            and g.LAT_CODES == ["000001", "600519", "300750", "688981", "920000"]
            and g.LOCAL_AHEAD_S == [1.0, 1.6]
            and "ntp.txt" in g.NTP_RAW,
            str(cfg),
        )
        ra.restore_switches()
        check(
            "开关：restore 后回到缺省（ONLY=None、LAT_CODES=[000001]、无 NTP）",
            g.ONLY is None
            and g.LAT_CODES == ["000001"]
            and g.LOCAL_AHEAD_S == []
            and p12.ONLY_KEYS is None,
        )
        ra.apply_switches(
            ra._switch_args(["--p11-only", "gap6-history", "--history-baseline", str(hb)])
        )
        check("开关：gap6-history + 基线目录", g.ONLY == "gap6-history" and g._baseline_dir() == hb)
        ra.restore_switches()
        ra.apply_switches(ra._switch_args(["--p12-only", "hslt"]))
        check("开关：p12 只取 hslt_list", [e[0] for e in p12.active_endpoints()] == ["hslt_list"])
        ra.restore_switches()
        bad = []
        for argv in (
            ["--gap1-codes", "00001"],
            ["--gap1-codes", ",".join(f"{i:06d}" for i in range(11))],
            ["--ntp-file", str(tmp / "none.txt")],
            ["--zt-codes", "002001"],
            ["--history-baseline", str(tmp / "nodir"), "--p11-only", "gap6-history"],
        ):
            try:
                ra.apply_switches(ra._switch_args(argv))
                bad.append(argv)
            except ValueError:
                pass
            ra.restore_switches()
        check(
            "开关：非法参数（5 位代码、11 只、NTP 文件不存在、--zt-codes 不配 gap6-nulls、基线目录不存在）均拒绝",
            not bad,
            str(bad),
        )
        check(
            "开关：--p11-only 各模式只含对应项",
            {k: [x[0] for x in v] for k, v in g.ONLY_PLAN.items()}
            == {
                "gap1": ["GAP1_snapshot_latency"],
                "gap6-history": ["GAP6_history_only"],
                "gap6-nulls": ["GAP6_nulls_retest"],
            },
        )
        sel = ra.select([])
        check(
            "p12 预期调用：缺省全流程 2 次；--p12-only hslt 且完整 p11 同跑 0 次；单独 hslt 1 次",
            ra._p12_expected_calls(sel) == 2
            and (ra.apply_switches(ra._switch_args(["--p12-only", "hslt"])) is not None)
            and ra._p12_expected_calls(sel) == 0
            and ra._p12_expected_calls(["p12_code_lists"]) == 1,
        )
    finally:
        ra.restore_switches()
    for n, ok, d in g.selftest_pure():
        check("p11 纯函数：" + n, ok, d)


def replay_cases(run_dir: Path) -> None:
    if not (run_dir / "p11_gaps.json").exists():
        skip("离线重放（收紧规则后）", f"{run_dir} 不存在（结果目录不入库）")
        return
    rep = rp.replay(run_dir)
    g6 = next(e for e in rep["items"] if e["name"] == "GAP6_factor_nulls_pit")["conclusion"]
    check(
        "重放：batch 请求日取原运行的 2026-01-30（不再用重建序列中点）",
        rep["batch_request_day"] == "2026-01-30",
        str(rep["batch_request_day"]),
    )
    check(
        "重放：收紧精度规则后 §16 不变（两因子 consistent_with_pit、precision_only=2）",
        g6["pit_verdict"] == {"profit_yoy": "consistent_with_pit", "roe_ttm": "consistent_with_pit"}
        and g6["precision_only_changes"] == {"profit_yoy": 2, "roe_ttm": 2},
        f"{g6['pit_verdict']} {g6['precision_only_changes']}",
    )
    check(
        "重放：batch_as_of=ok（响应 20260130 = 请求 20260130），比对 equal=true",
        g6["batch_as_of"]["status"] == "ok"
        and all(v["equal"] is True for v in g6["history_vs_batch_same_day"].values()),
        str(g6["batch_as_of"]),
    )


def main() -> int:
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PROBES / "results" / "run-20261101-190106"
    with rp.no_network() as hits:
        precision_cases()
        asof_cases()
        switch_cases()
        replay_cases(run_dir)
    check("自检全程未尝试出网", not hits, str(hits))
    print(f"{RESULTS['pass']} passed, {RESULTS['fail']} failed, {RESULTS['skip']} skipped")
    return 1 if RESULTS["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
