"""T-B59 相关离线用例/独立更正回放；无网络或数据库。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probes"))
import p13_analyze as a

from app.financial_basis import (
    TradingCalendar,
    load_share_classes,
    share_class_at,
    v5g_conditions,
    validate_share_classes,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", nargs="*", type=Path, default=[])
    args = parser.parse_args()
    checks = []

    def check(ok: object, name: str) -> None:
        checks.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name)

    for name, ok, detail in a.selftest_pure():
        check(ok, "原纯函数: " + name + (" " + detail if not ok else ""))
    # Algorithm fixtures, not a replacement for missing 2024 live calendar evidence.
    cal = TradingCalendar.from_mapping(
        {
            "coverage_start": "2024-04-29",
            "coverage_end": "2024-05-07",
            "open_days": ["2024-04-29", "2024-04-30", "2024-05-06", "2024-05-07"],
            "source": "人工离线休市场景用例（非实测交易日历）",
        }
    )
    row = a.capital_rows([{"bdrq": "20240331", "plrq": "2024-04-30", "zgb": 1}])[0]
    # Normal disclosure on the deadline, and a quarter-end backfill, both obey the calendar.
    check(
        a.capital_visible(row, calendar=cal)["visible_from"] == "2024-05-06",
        "注入明确日历后4月30日的下一开市日为5月6日",
    )
    row = a.capital_rows([{"bdrq": "20240331", "plrq": "2024-03-31", "zgb": 1}])[0]
    full = TradingCalendar("2024-03-01", "2024-05-07", ("2024-04-01", *cal.open_days), cal.source)
    vis = a.capital_visible(row, calendar=full)
    check(
        vis["visible_from"] == "2024-05-06" and vis["visible_at"] == "2024-05-06T09:30+08:00",
        "首次回填截止规则不落到5月1日休市日",
    )
    check(vis["pit_basis"] == ["capital_deadline"], "截止日basis仍为字符串数组")
    check(a.capital_visible(row)["visible_from"] is None, "缺真实日历不再退回下一自然日")
    check(a.capital_visible(row, calendar=cal)["visible_from"] is None, "日历覆盖不含plrq时不猜测")
    check(cal.next_day("2024-05-07") is None, "日历尾部不外推开市日")
    inc = a.capital_visible(row, "2024-05-04T01:00:00Z", calendar=full)
    check(
        inc["visible_from"] == "2024-05-06" and not inc["pit_basis"],
        "增量无截止日且first_seen落休市日时映射下一开市时段",
    )
    old = a.capital_rows([{"bdrq": "20240331", "plrq": "2024-03-31", "zgb": 1}])
    check(
        a.zgb_at(old, "2024-05-01", calendar=full) is None
        and a.zgb_at(old, "2024-05-06", calendar=full) is not None,
        "截止后休市日不可见，下一开市日才可见",
    )
    exp = {
        "ratio": 10,
        "source": "离线阈值场景",
        "checkpoints": [
            {
                "name": "test",
                "not_before": "2025-01-01",
                "at": "2025-12-31",
                "cdr_units": 100000,
                "base_shares": 10000,
            }
        ],
    }

    def cdr(z: int) -> dict[str, object]:
        return a.cdr_unit_check([{"bdrq": "20251231", "plrq": "2026-03-31", "zgb": z}], exp)

    check(cdr(100100)["v5j_cdr_unit"] == "zgb≈CDR份数", "份数相差恰好0.1%通过")
    check(
        cdr(100101)["v5j_cdr_unit"] == "neither" and cdr(100101)["data_quality"],
        "份数超过0.1%保留标记并报data_quality",
    )
    check(cdr(10010)["v5j_cdr_unit"] == "zgb≈基础股数", "基础股数也用0.1%相对容差")
    # Only 689009 has a real per-security signoff. A synthetic bar tests arithmetic only.
    pc = TradingCalendar(
        "2025-01-01", "2026-01-01", ("2025-04-21", "2025-08-21", "2025-10-30"), "离线算式场景"
    )
    cap = [{"bdrq": "20250415", "plrq": "2025-04-20", "zgb": 720335580}]
    bal = [{"jzrq": "2025-06-30", "plrq": "2025-08-20", "gsmgdqsyhj": 100}]
    known = a.pb_at(
        {"t": "2025-10-30", "c": 5},
        cap,
        bal,
        ["cdr_unit"],
        is_cdr=True,
        cdr_unit="zgb≈CDR份数",
        security_code="689009.SH",
        calendar=pc,
    )
    other = a.pb_at(
        {"t": "2025-10-30", "c": 5},
        cap,
        bal,
        is_cdr=True,
        cdr_unit="zgb≈CDR份数",
        security_code="689998.SH",
        calendar=pc,
    )
    check(
        known["basis"]["mcap"] == 5 * 720335580
        and "cdr_unit" not in known["basis"]["verify_pending"],
        "689009 c×zgb不乘10且逐只清标记",
    )
    check("cdr_unit" in other["basis"]["verify_pending"], "其他CDR同份数判定也不自动推广签收")
    drafts = load_share_classes(a.SHARE_CLASS_PATH)
    check(
        not drafts["records"]
        and len(drafts["sources"]["pending_records"]) == 283
        and not any(r["verified"] for r in drafts["sources"]["pending_records"]),
        "283条草稿保持verified=false",
    )
    sample = {
        "601318_A+H": {"verdict": "includes_non_a"},
        "000550_A+B": {"verdict": "includes_non_a"},
    }
    actual = v5g_conditions(drafts, sample)
    check(len(actual) == 4 and sum(actual.values()) == 1, "V5g四条件仅A+H/A+B总股本对照已满足")
    check(
        share_class_at(drafts, "601318.SH", "2025-12-31")["share_class_check"] == "unavailable",
        "缺生效日期不臆造历史名单成员",
    )
    fixture = {
        "schema_version": 1,
        "list_version": 2,
        "as_of": "2026-11-01",
        "sources": {"union_complete": True, "discrepancy_211_209_resolved": True},
        "records": [
            {
                "code": "601318.SH",
                "class": "H",
                "paired_code": "02318",
                "paired_market": "HK",
                "effective_from": "2025-01-02",
                "effective_to": "2025-12-31",
                "source": "人工区间用例，非上市日证据",
                "verified": True,
            }
        ],
    }
    validate_share_classes(fixture)
    check(
        share_class_at(fixture, "601318.SH", "2025-01-01")["member"] is None,
        "上市前不套后来的H股对应关系",
    )
    check(
        share_class_at(fixture, "601318.SH", "2025-01-02")["member"] == "A+H"
        and share_class_at(fixture, "601318.SH", "2025-12-31")["member"] is None,
        "生效区间左右闭开",
    )
    flags = a.pb_at(
        {"t": "2025-10-30", "c": 5},
        cap,
        bal,
        share_class_list="A+H",
        lists_configured=True,
        share_class_list_version=2,
        calendar=pc,
    )["basis"]
    check(
        flags["share_class_check"] == "list"
        and flags["share_class_list_version"] == 2
        and "non_a_share_capital" in flags["verify_pending"],
        "有效名单版本入basis并给成员打标",
    )
    check(all(v5g_conditions(fixture, sample).values()), "完整四条件正例")
    broken = copy.deepcopy(fixture)
    broken["records"][0]["effective_from"] = None
    try:
        validate_share_classes(broken)
    except ValueError:
        check(True, "verified=true但缺生效日期必须拒绝")
    else:
        check(False, "缺生效日期未拒绝")
    broken["records"][0]["verified"] = False
    try:
        validate_share_classes(broken)
    except ValueError:
        check(True, "verified=false也不能让缺上市日期的草稿冒充正式记录")
    else:
        check(False, "正式记录缺上市日期未拒绝")

    for run in args.replay:
        original = run / "p13_analysis.json"
        source_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        raw = a.load_raw(run)
        corrected = a.analyze(
            raw, json.loads((run / a.SUBDIR / "plan_meta.json").read_text()), a.load_first_seen(run)
        )
        check(corrected["10_cdr"]["689009"]["cdr_unit_cleared"], run.name + "逐证券CDR签收状态")
        check(
            not corrected["7_share_class_lists"]["v5g_close"]["closed"],
            run.name + "名单缺口不虚报关闭",
        )
        check(
            corrected["4_capital"]["v5i_backfill"]["by_code"]["000550"]["verdict"]
            == "inconclusive",
            run.name + "000550缺报告仍如实保留",
        )
        check(not corrected["trading_calendar"]["confirmed"], run.name + "无真实日历不签收可见日期")
        out = run / "p13_analysis.corrected-T-B59.json"
        with out.open("x") as f:
            json.dump(corrected, f, ensure_ascii=False, indent=2)
        check(
            hashlib.sha256(original.read_bytes()).hexdigest() == source_hash,
            run.name + "不覆盖原始分析",
        )
        print("独立更正: " + str(out))
    print(f"{sum(checks)} passed, {len(checks) - sum(checks)} failed")
    return int(not all(checks))


if __name__ == "__main__":
    raise SystemExit(main())
