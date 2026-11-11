# ruff: noqa: S101
"""T-R65③：三项状态输入强制预检 + 覆盖比例 + load_status_history 契约。

对应任务：T-R65 阶段③（T-A154 三条件：st_history / listing_history / delisting_list 缺一不可、
coverage 三项非 null、覆盖比例按交易所按年入 summary 首页）。

用例全部走合成 CSV（tmp_path），不读仓库外真实样本、不写库、零麦蕊。
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from retest.t_r58 import data, judgement, runner_data
from retest.t_r58.errors import DataFormatError


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _paths(tmp_path: Path, **overrides: Path | None) -> runner_data.ResearchPaths:
    base = {
        "data_root": tmp_path,
        "single_package": None,
        "main_package": None,
        "calendar": tmp_path / "calendar.csv",
        "st_history": tmp_path / "st.csv",
        "listing_history": tmp_path / "listing.csv",
        "delisting_list": tmp_path / "delisting.csv",
    }
    base.update(overrides)
    return runner_data.ResearchPaths(**base)


def test_require_status_inputs_rejects_each_missing(tmp_path: Path) -> None:
    for name in runner_data.STATUS_INPUTS:
        paths = _paths(tmp_path, **{name: None})
        with pytest.raises(DataFormatError) as excinfo:
            runner_data.require_status_inputs(paths)
        assert name in str(excinfo.value)


def test_require_status_inputs_accepts_complete(tmp_path: Path) -> None:
    runner_data.require_status_inputs(_paths(tmp_path))


def test_preflight_refuses_before_touching_data(tmp_path: Path) -> None:
    paths = _paths(tmp_path, listing_history=None)
    with pytest.raises(DataFormatError, match="T-A154"):
        runner_data.preflight(paths, {})


def test_load_status_history_roundtrip(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path / "st.csv",
        ["exchange", "symbol", "valid_from", "valid_to", "is_st"],
        [
            ["SH", "600001", "2022-01-01", "2023-05-06", "false"],
            ["SH", "600001", "2023-05-06", "", "true"],
            ["SZ", "000001", "2022-01-01", "", "false"],
        ],
    )
    history, summary = data.load_status_history(path, "st")
    assert summary["rows"] == 3
    assert summary["stocks"] == 2
    assert summary["open_ended"] is True
    assert history[("SH", "600001")][1] == (date(2023, 5, 6), None, True)


def test_listing_history_accepts_status_values(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path / "listing.csv",
        ["exchange", "symbol", "valid_from", "valid_to", "status"],
        [
            ["SH", "600001", "2022-01-01", "2024-06-01", "listed"],
            ["SH", "600001", "2024-06-01", "2024-06-20", "delisting_period"],
            ["SH", "600001", "2024-06-20", "", "delisted"],
        ],
    )
    history, summary = data.load_status_history(path, "listing")
    assert summary["stocks"] == 1
    assert [value for _, _, value in history[("SH", "600001")]] == ["listed", "delisting_period", "delisted"]


def test_load_status_history_rejects_overlap_and_bad_flag(tmp_path: Path) -> None:
    overlap = _write_csv(
        tmp_path / "overlap.csv",
        ["exchange", "symbol", "valid_from", "valid_to", "is_st"],
        [
            ["SH", "600001", "2022-01-01", "2024-01-01", "false"],
            ["SH", "600001", "2023-01-01", "", "true"],
        ],
    )
    with pytest.raises(DataFormatError):
        data.load_status_history(overlap, "st")
    bad = _write_csv(
        tmp_path / "bad.csv",
        ["exchange", "symbol", "valid_from", "valid_to", "is_st"],
        [["SH", "600001", "2022-01-01", "", "maybe"]],
    )
    with pytest.raises(DataFormatError):
        data.load_status_history(bad, "st")


def test_coverage_ratios_math() -> None:
    counters = {
        ("SH", 2022): {
            "stock_days": 1000,
            "st": 50,
            "st_unknown": 0,
            "listing_status_unknown": 100,
            "delisting_period": 10,
        },
        ("SH", 2023): {
            "stock_days": 500,
            "st": 0,
            "st_unknown": 50,
            "listing_status_unknown": 0,
            "delisting_period": 0,
        },
        ("SZ", 2022): {
            "stock_days": 2000,
            "st": 200,
            "st_unknown": 0,
            "listing_status_unknown": 0,
            "delisting_period": 20,
        },
    }
    result = runner_data.coverage_ratios(counters)
    by_year = {(row["exchange"], row["year"]): row for row in result["by_exchange_year"]}
    assert by_year[("SH", 2022)]["st_known_share"] == 1.0
    assert by_year[("SH", 2022)]["listing_known_share"] == 0.9
    assert by_year[("SH", 2022)]["st_true_share"] == 0.05
    assert by_year[("SH", 2023)]["st_known_share"] == 0.9
    by_exchange = {row["exchange"]: row for row in result["by_exchange"]}
    assert by_exchange["SH"]["stock_days"] == 1500
    assert by_exchange["SH"]["st_known_share"] == round(1 - 50 / 1500, 6)
    assert by_exchange["SZ"]["st_known_share"] == 1.0


def test_empty_coverage_ratio_is_none() -> None:
    result = runner_data.coverage_ratios({("SH", 2022): {"stock_days": 0}})
    assert result["by_exchange_year"][0]["st_known_share"] is None


def _prepared(
    official: dict[tuple[str, str], date],
    periods: dict[tuple[str, str], list[tuple[date, date | None, str]]] | None = None,
    expected_end: dict[str, date] | None = None,
    pool: list[tuple[str, str, str]] | None = None,
    evidence: dict[tuple[str, str], str] | None = None,
    dates: list[date] | None = None,
    confirmed: set[tuple[str, str, date]] | None = None,
) -> SimpleNamespace:
    coverage = {
        symbol: {"expected_end_date": day} for symbol, day in (expected_end or {}).items()
    }
    return SimpleNamespace(
        meta={
            "termination_list": official,
            "coverage": coverage,
            "termination_evidence": evidence or {},
            "confirmed_suspension": confirmed or set(),
        },
        pool=pool if pool is not None else [(ex, sym, "D") for ex, sym in official],
        listing_history=periods or {},
        dates=dates or [],
        evidence={"stock_pool": {"delisted_hf": len(official)}},
    )


DELIST = date(2024, 6, 20)
PERIOD_START = date(2024, 5, 29)


def test_delisting_passes_with_period_and_tail_bar() -> None:
    prepared = _prepared(
        {("SH", "600001"): DELIST},
        {("SH", "600001"): [(PERIOD_START, DELIST, "delisting_period")]},
    )
    result = judgement._delisting(prepared, {("SH", "600001"): DELIST})
    assert result["state"] == "pass"
    assert result["pass_with_period"] == [("SH", "600001")]
    assert result["official_count"] == 1


def test_delisting_no_period_by_rule_when_last_bar_is_expected_end() -> None:
    prepared = _prepared(
        {("SH", "600002"): DELIST},
        expected_end={"600002": date(2024, 6, 19)},
        evidence={("SH", "600002"): "title_evidence"},
    )
    result = judgement._delisting(prepared, {("SH", "600002"): date(2024, 6, 19)})
    assert result["state"] == "pass"
    assert result["no_delisting_period_by_rule"] == [("SH", "600002")]
    assert result["no_delisting_period_total"] == 1
    assert result["no_period_policy"] == "last_bar_equals_hf_expected_end"


def test_delisting_flags_suspended_until_delisting() -> None:
    # 最后 bar 距终止日 10 天（>5）但与 expected_end 相等：停牌到摘牌形态
    prepared = _prepared(
        {("SH", "600003"): DELIST},
        expected_end={"600003": date(2024, 6, 10)},
        evidence={("SH", "600003"): "title_evidence"},
    )
    result = judgement._delisting(prepared, {("SH", "600003"): date(2024, 6, 10)})
    assert result["state"] == "pass"
    assert result["suspended_until_delisting"] == [("SH", "600003")]
    assert result["no_delisting_period_by_rule"] == []


def test_delisting_marks_evidence_only_and_residual_risk() -> None:
    prepared = _prepared(
        {("SH", "600004"): DELIST},
        expected_end={"600004": date(2024, 6, 19)},
        evidence={("SH", "600004"): "no_title_evidence"},
    )
    result = judgement._delisting(prepared, {("SH", "600004"): date(2024, 6, 19)})
    assert result["state"] == "pass"
    assert result["no_delisting_period_evidence_only"] == [("SH", "600004")]
    assert "交叉核" in (result["residual_risk"] or "")


def test_delisting_tail_gap_confirmed_suspension_is_not_truncated() -> None:
    last = date(2024, 6, 17)
    expected = DELIST
    days = [date(2024, 6, 18)]
    prepared = _prepared(
        {("SH", "600005"): DELIST},
        expected_end={"600005": expected},
        dates=days,
        confirmed={("600005", "SH", days[0])},
    )
    result = judgement._delisting(prepared, {("SH", "600005"): last})
    assert result["state"] == "pass"
    assert result["suspended_until_delisting"] == [("SH", "600005")]
    assert result["tail_missing"] == []


def test_delisting_tail_gap_without_suspension_is_tail_missing() -> None:
    last = date(2024, 6, 17)
    prepared = _prepared(
        {("SH", "600006"): DELIST},
        expected_end={"600006": DELIST},
        dates=[date(2024, 6, 18)],
    )
    result = judgement._delisting(prepared, {("SH", "600006"): last})
    assert result["state"] == "fail"
    assert result["tail_missing"] == [("SH", "600006")]


def test_delisting_unknown_when_expected_end_missing() -> None:
    prepared = _prepared({("SH", "600007"): DELIST})
    result = judgement._delisting(prepared, {("SH", "600007"): date(2024, 6, 19)})
    assert result["state"] == "unknown"
    assert result["period_unknown"] == [("SH", "600007")]


def test_delisting_fails_on_missing_or_truncated_period() -> None:
    missing = _prepared(
        {("SH", "600008"): DELIST},
        {("SH", "600008"): [(PERIOD_START, DELIST, "delisting_period")]},
        pool=[("SH", "600001", "D")],
    )
    assert judgement._delisting(missing, {})["state"] == "fail"
    truncated = _prepared(
        {("SH", "600009"): DELIST},
        {("SH", "600009"): [(PERIOD_START, DELIST, "delisting_period")]},
    )
    result = judgement._delisting(truncated, {("SH", "600009"): date(2024, 5, 20)})
    assert result["state"] == "fail"
    assert result["tail_missing"] == [("SH", "600009")]


def test_delisting_ignores_period_started_after_delisting() -> None:
    prepared = _prepared(
        {("SH", "600010"): DELIST},
        {("SH", "600010"): [(date(2024, 7, 1), None, "delisting_period")]},
        expected_end={"600010": date(2024, 6, 19)},
        evidence={("SH", "600010"): "title_evidence"},
    )
    result = judgement._delisting(prepared, {("SH", "600010"): date(2024, 6, 19)})
    assert result["state"] == "pass"
    assert result["no_delisting_period_by_rule"] == [("SH", "600010")]
