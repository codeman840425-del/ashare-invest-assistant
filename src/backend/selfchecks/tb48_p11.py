# ruff: noqa: E501  自检脚本：检查描述保持单行，便于对照输出
"""T-B48 自检：p11_gaps 嵌套响应解析、小数截断不算前视、离线重放与网络护栏。

不连数据库、不出网（全程套 ``p11_replay.no_network``），不读取证书；环境里有证书变量直接拒绝运行。
重放用例依赖本机的探针运行目录（默认 ``probes/results/run-20261101-190106``，不入库）；目录不存在时
该组用例记为 SKIP，其余用例照常执行。

运行（目录 ``src/backend``）::

    env -u MAIRUI_LICENCE python3 selfchecks/tb48_p11.py [运行目录]

输出逐条 ``PASS`` / ``FAIL`` / ``SKIP``，最后一行 ``N passed, M failed, K skipped``；有 FAIL 时退出码 1。
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

if os.environ.get("MAIRUI_" + "LICENCE"):
    sys.exit("自检拒绝运行：环境里有证书变量（请 env -u 该变量）")

PROBES = Path(__file__).resolve().parents[1] / "probes"
sys.path.insert(0, str(PROBES))

import p11_gaps as g  # noqa: E402
import p11_replay as rp  # noqa: E402

RESULTS = {"pass": 0, "fail": 0, "skip": 0}


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS["pass" if ok else "fail"] += 1
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))


def skip(name: str, why: str) -> None:
    RESULTS["skip"] += 1
    print(f"SKIP {name} — {why}")


NULL_EXPECTED = {
    "north_5d_net": "3/3",
    "north_20d_net": "3/3",
    "limit_up_streak": "3/3",
    "seal_ratio": "3/3",
    "seal_to_float": "3/3",
    "current_ratio": "1/3",
    "peg": "1/3",
}


def unit_cases() -> None:
    for n, ok, d in g.selftest_pure():
        check(f"selftest_pure：{n}", ok, d)
    # factor/all 嵌套与扁平
    nested = {
        "code": 200,
        "msg": "success",
        "data": {
            "code": "000001",
            "name": "平安银行",
            "theme": "t",
            "trade_date": "20261030",
            "factors": {"pe_ttm": 5.1, "peg": None, "pb_rank": 3},
        },
    }
    d, ks = g.factor_keys(nested)
    check(
        "factor_keys：data.factors 嵌套 → 只取因子键，*_rank 与元数据（含 theme）排除",
        sorted(ks) == ["pe_ttm", "peg"] and d["trade_date"] == "20261030" and d["peg"] is None,
        str(ks),
    )
    _, ks2 = g.factor_keys({"data": {"code": "600519", "pe_ttm": 20, "theme": "x"}})
    check("factor_keys：扁平结构仍兼容", ks2 == ["pe_ttm"], str(ks2))
    check("factor_keys：非 dict → (None, None)", g.factor_keys([1, 2]) == (None, None))
    # factor/batch 多种结构
    b1 = {
        "code": 200,
        "data": {
            "items": {"600519": {"profit_yoy": 6.2458449524124315, "roe_ttm": 90.18375499421303}},
            "trade_date": "20260130",
        },
        "msg": "success",
    }
    v1, t1 = g.batch_values(b1, "600519")
    check(
        "batch_values：data.items.{code}（实测结构）",
        v1 == {"profit_yoy": 6.2458449524124315, "roe_ttm": 90.18375499421303} and t1 == "20260130",
        f"{v1} {t1}",
    )
    v2, _ = g.batch_values(
        {"data": {"items": [{"code": "600519.SH", "factors": {"roe_ttm": 1.0}}]}}, "600519"
    )
    check("batch_values：items 为列表 + factors", v2 == {"roe_ttm": 1.0}, str(v2))
    v3, _ = g.batch_values(
        {"data": [{"dm": "000001", "roe_ttm": 2.0}, {"dm": "600519", "roe_ttm": 3.0}]}, "600519"
    )
    check("batch_values：data 为列表，按代码挑行", v3 == {"roe_ttm": 3.0}, str(v3))
    v4, _ = g.batch_values(
        {"data": {"items": {"000001": {"roe_ttm": 1}, "300750": {"roe_ttm": 2}}}}, "600519"
    )
    check("batch_values：多只且没有目标代码 → 空", v4 == {}, str(v4))
    # 截断判定
    check(
        "precision_only：1.4714182949831487 vs 1.471418（截断 6 位）",
        g.precision_only(1.4714182949831487, 1.471418),
    )
    check(
        "precision_only：82.98214819072565 vs 82.982148",
        g.precision_only(82.98214819072565, 82.982148),
    )
    check("precision_only：四舍五入 2.0000005 vs 2.000001", g.precision_only(2.0000005, 2.000001))
    check(
        "precision_only：真实变化 1.471418 vs 1.471518 → 否",
        not g.precision_only(1.471418, 1.471518),
    )
    check(
        "precision_only：6.2458 vs -4.5322 → 否",
        not g.precision_only(6.2458449524124315, -4.532254817158089),
    )
    check(
        "precision_only：相等 / None → 否",
        not g.precision_only(1.0, 1.0) and not g.precision_only(None, 1.0),
    )
    ser = [
        ("2026-07-31", 1.4714182949831487),
        ("2026-08-03", 1.471418),
        ("2026-08-14", 1.4714182949831487),
        ("2026-08-15", -1.9515948550279467),
    ]
    pit = g.classify_pit(g.change_points(ser), [{"jzrq": "2026-06-30", "plrq": "2026-08-15"}])
    check(
        "classify_pit：截断来回两次 → precision_only=2，结论按时点一致",
        pit["counts"]
        == {"after_plrq": 1, "before_disclosure": 0, "unexplained": 0, "precision_only": 2}
        and pit["verdict"] == "consistent_with_pit",
        str(pit["counts"]),
    )
    # T-B05 收紧：较短一方至少 4 位小数才可能算精度差；原用例 1.0↔1.0000001（较短一方 0 位）与 15.0↔14.97 同类，改为 6 位截断
    pit2 = g.classify_pit(
        g.change_points([("2026-08-01", 1.234567), ("2026-08-03", 1.2345671234)]), []
    )
    check(
        "classify_pit：只有精度变化（6 位截断）→ no_change_in_window",
        pit2["verdict"] == "no_change_in_window",
        pit2["verdict"],
    )
    pit3 = g.classify_pit(
        g.change_points([("2026-07-01", 1.0), ("2026-08-03", 2.0)]),
        [{"jzrq": "2026-06-30", "plrq": "2026-08-15"}],
    )
    check(
        "classify_pit：真实披露前跳变仍判前视",
        pit3["verdict"] == "lookahead_suspected",
        pit3["verdict"],
    )


def guard_cases() -> None:
    import common
    import requests

    with rp.no_network() as hits:
        for name, fn in (
            ("socket.create_connection", lambda: socket.create_connection(("203.0.113.1", 443), 1)),
            ("socket.connect", lambda: socket.socket().connect(("203.0.113.1", 443))),
            ("getaddrinfo", lambda: socket.getaddrinfo("example.invalid", 443)),
            ("requests.get", lambda: requests.get("https://example.invalid/", timeout=1)),
            ("common.call", lambda: common.call("x", "/x/{licence}")),
        ):
            try:
                fn()
                check(f"网络护栏拦截 {name}", False, "没有抛异常")
            except rp.NetworkBlocked:
                check(f"网络护栏拦截 {name}", True)
    check("网络护栏记录拦截次数", len(hits) == 5, str(len(hits)))
    check(
        "网络护栏退出后恢复原函数",
        socket.create_connection is not None
        and requests.Session.request.__name__ == "request"
        and common.call.__name__ == "call",
    )


def replay_cases(run_dir: Path) -> None:
    if not (run_dir / "p11_gaps.json").exists():
        skip("离线重放 run-20261101-190106", f"{run_dir} 不存在（结果目录不入库）")
        return
    rep = rp.replay(run_dir)
    items = {e["name"]: e for e in rep["items"]}
    g6, g7 = items["GAP6_factor_nulls_pit"]["conclusion"], items["GAP7_factor_count"]["conclusion"]
    check("重放：网络调用 0 次", rep["network_calls_blocked"] == 0)
    check(
        "重放：GAP7 factor/all 实返 85 个、factor/list 85 个",
        g7["returned_n"] == 85 and g7["factor_list_n"] == 85,
        f"{g7['returned_n']}/{g7['factor_list_n']}",
    )
    check(
        "重放：GAP7 与文档差异只有 ev_ebitda→ev_ebit",
        g7["missing_vs_doc85"] == ["ev_ebitda"] and g7["extra_vs_doc85"] == ["ev_ebit"],
        f"{g7['missing_vs_doc85']} {g7['extra_vs_doc85']}",
    )
    check(
        "重放：GAP6 空值因子与 §16 一致",
        g6["null_factors"] == NULL_EXPECTED,
        str(g6["null_factors"]),
    )
    check(
        "重放：north_holding_ratio、attention_score 不在空值里",
        "north_holding_ratio" not in g6["null_factors"]
        and "attention_score" not in g6["null_factors"],
    )
    check(
        "重放：时点性两因子均 consistent_with_pit（截断不算前视）",
        g6["pit_verdict"]
        == {"profit_yoy": "consistent_with_pit", "roe_ttm": "consistent_with_pit"},
        str(g6["pit_verdict"]),
    )
    check(
        "重放：每个因子 precision_only=2",
        g6["precision_only_changes"] == {"profit_yoy": 2, "roe_ttm": 2},
    )
    cmp_ = g6["history_vs_batch_same_day"]
    check(
        "重放：batch 2026-01-30 值与 history 相等",
        all(v["equal"] and v["date"] == "2026-01-30" for v in cmp_.values())
        and cmp_["profit_yoy"]["batch"] == 6.2458449524124315
        and cmp_["roe_ttm"]["batch"] == 90.18375499421303,
        str(cmp_),
    )


def main() -> int:
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PROBES / "results" / "run-20261101-190106"
    with rp.no_network() as hits:  # 整个自检都不允许出网
        unit_cases()
    guard_cases()
    with rp.no_network() as hits2:
        replay_cases(run_dir)
    check("自检全程未尝试出网", not hits and not hits2, f"{hits} {hits2}")
    print(f"{RESULTS['pass']} passed, {RESULTS['fail']} failed, {RESULTS['skip']} skipped")
    return 1 if RESULTS["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
