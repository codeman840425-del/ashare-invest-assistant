# ruff: noqa: E501  自检脚本：检查描述保持单行，便于对照输出
"""T-R12 / T-R12a 财务时点自算准备自检：p13 离线分析纯函数、调用计划、开关解析、可选离线回放。

不连数据库、不出网（全程套 ``p11_replay.no_network``），不读取证书；环境里有证书变量直接拒绝运行。
p13 的端到端调用次数（28 次 = 服务端增量）在 ``probes/run_all.py --dry-run`` 的“阶段 6”里核对（本地伪造服务端）。

运行（目录 ``src/backend``）::

    env -u MAIRUI_LICENCE python3 selfchecks/tr12_fin.py [p13 运行目录]

给了运行目录时，对其中 ``p13_fin_pit/raw_*.json`` 离线重算并与 ``p13_analysis.json`` 比对。
输出逐条 ``PASS`` / ``FAIL`` / ``SKIP``，最后一行 ``N passed, M failed, K skipped``；有 FAIL 时退出码 1。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if os.environ.get("MAIRUI_" + "LICENCE"):
    sys.exit("自检拒绝运行：环境里有证书变量（请 env -u 该变量）")

PROBES = Path(__file__).resolve().parents[1] / "probes"
sys.path.insert(0, str(PROBES))

import p11_replay as rp  # noqa: E402
import p13_analyze as an  # noqa: E402
import p13_fin_pit as p13  # noqa: E402
import run_all as ra  # noqa: E402

RESULTS = {"pass": 0, "fail": 0, "skip": 0}


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS["pass" if ok else "fail"] += 1
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))


def skip(name: str, why: str) -> None:
    RESULTS["skip"] += 1
    print(f"SKIP {name} — {why}")


def plan_checks() -> None:
    plan = p13.call_plan()
    keys = [k for k, *_ in plan]
    check(
        "调用计划：静态 26 次 + ⑤ gg 2 次 = 28（与 run_all.P13_EXPECT_CALLS 一致）",
        len(plan) + 2 == ra.P13_EXPECT_CALLS == 28,
        str(len(plan)),
    )
    check("调用计划：无重复 key", len(keys) == len(set(keys)))
    check(
        "调用计划：①② 含银行 000001/600000、保险 601318、更正样例 600525",
        all(
            f"{t}_{x}" in keys
            for t in ("cashflow", "balance")
            for x in ("000001", "600000", "601318", "600525")
        ),
    )
    check(
        "调用计划：⑦ A+H 601318、A+B 000550 取 capital；⑨ CDR 689009 取 balance",
        {"capital_601318", "capital_000550", "balance_689009"} <= set(keys),
    )
    check(
        "调用计划：⑥ 日线是不复权 /d/n、区间 20260901–20261031",
        all(
            "/d/n/" in t and p == {"st": "20260901", "et": "20261031"}
            for k, _, _, t, p in plan
            if k.startswith("daily_")
        ),
    )
    check(
        "调用计划：所有路径模板证书只以占位符出现",
        all(t.endswith("{licence}") for *_, t, _ in plan),
    )
    nodes = p13.pick_gg_nodes(
        [
            {"name": "申万行业-银行", "code": "sw_yx", "pcode": "swhy"},
            {"name": "申万二级-保险Ⅱ", "code": "sw2_490200", "pcode": "sw_fy"},
            {"name": "概念-银行", "code": "gn_yh"},
        ]
    )
    check(
        "⑤ gg 节点选择：银行取申万一级、保险取申万二级",
        nodes == [("bank", "sw_yx"), ("insurance", "sw2_490200")],
        str(nodes),
    )
    check(
        "⑤ gg 节点选择：list 里没有对应节点 → 不调用（不猜代码）",
        p13.pick_gg_nodes([{"name": "x", "code": "sw_mt", "pcode": "swhy"}]) == [],
    )
    alt = p13.call_plan("600590.SH")
    check(
        "--p13-restated：更正样例替换进 ①②③",
        {"cashflow_600590", "balance_600590", "income_600590"} <= {k for k, *_ in alt}
        and "income_600525" not in {k for k, *_ in alt},
    )


def switch_checks() -> None:
    ra.apply_switches(ra._switch_args([]))
    ok = True
    try:
        ra.apply_switches(ra._switch_args(["--p13-restated", "600590"]))
        ok = False
    except ValueError:
        pass
    check("--p13-restated 格式不对 → ValueError", ok)
    ok = True
    try:
        ra.apply_switches(ra._switch_args(["--p13-announce", "2024-11-09"]))
        ok = False
    except ValueError:
        pass
    ra.restore_switches()
    check("--p13-announce 单独给 → ValueError", ok)
    ra.apply_switches(
        ra._switch_args(
            [
                "--p13-restated",
                "600590.sh",
                "--p13-announce",
                "2024-11-09",
                "--p13-periods",
                "2023-12-31, 2024-06-30",
            ]
        )
    )
    r = dict(p13.RESTATED)
    ra.restore_switches()
    check(
        "--p13-restated/--announce/--periods 写入、restore 复原",
        r["code"] == "600590.SH"
        and r["periods"] == ["2023-12-31", "2024-06-30"]
        and p13.RESTATED["code"] == "600525.SH",
        str(r),
    )
    check(
        "p13 只点名运行：缺省全量不含、p13 前缀选中",
        "p13_fin_pit" not in ra.select([]) and ra.select(["p13"]) == ["p13_fin_pit"],
    )


def replay(run_dir: Path) -> None:
    meta = run_dir / an.SUBDIR / "plan_meta.json"
    got = run_dir / "p13_analysis.json"
    if not meta.is_file() or not got.is_file():
        skip("离线回放", f"{run_dir} 里没有 p13 输出")
        return
    again = json.loads(
        json.dumps(
            an.analyze(an.load_raw(run_dir), json.loads(meta.read_text(encoding="utf-8"))),
            ensure_ascii=False,
            default=str,
        )
    )
    check(
        f"离线回放：{run_dir.name} 重算 = p13_analysis.json",
        again == json.loads(got.read_text(encoding="utf-8")),
    )


def main() -> int:
    with rp.no_network():
        for n, ok, d in an.selftest_pure():
            check("p13_analyze " + n, ok, d)
        plan_checks()
        switch_checks()
        if len(sys.argv) > 1:
            replay(Path(sys.argv[1]))
    print(f"{RESULTS['pass']} passed, {RESULTS['fail']} failed, {RESULTS['skip']} skipped")
    return 1 if RESULTS["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
