"""T-A29 frozen component aggregation; no live source, DB or current clock."""

# ruff: noqa: S101
import copy
import datetime as dt

import pytest

from app.api.v1.daily_reports import project_component_clock


@pytest.mark.parametrize("previous", [None, "2026-10-28T07:00:00Z"])
def test_missing_and_nonnull_wrong_aggregate(previous: str | None) -> None:
    body = {
        "data_as_of": previous,
        "data_status": "partial",
        "evidence": [{"data_as_of": "2026-10-27T00:00:00Z"}],
        "market": {"data_as_of": "2026-10-30T08:02:00+08:00"},
        "stocks": [
            {
                "dimensions": [
                    {"facts": [], "data_as_of": "2026-10-30T08:01:00+08:00"},
                    {"facts": [], "data_as_of": None},
                ]
            }
        ],
        "gaps": [],
    }
    frozen = copy.deepcopy(body)
    generated = dt.datetime.fromisoformat("2026-10-30T18:00:00+08:00")
    result = project_component_clock(body, generated)
    assert result["data_as_of"] == dt.datetime.fromisoformat("2026-10-30T08:01:00+08:00")
    assert result["data_status"] == "partial"
    assert body == frozen
    assert project_component_clock(result, generated) == result


def test_no_usable_component_never_uses_generation_or_raw_evidence() -> None:
    body = {
        "data_as_of": None,
        "market": {"data_as_of": "bad"},
        "stocks": [
            {"data_as_of": "2026-10-31T00:00:00Z"},
            {"data_as_of": "2026-10-29T00:00:00"},
            {"change_from_previous": "removed", "data_as_of": "2026-10-27T00:00:00Z"},
        ],
        "evidence": [{"data_as_of": "2026-10-26T00:00:00Z"}],
    }
    result = project_component_clock(body, dt.datetime.fromisoformat("2026-10-30T12:00:00Z"))
    assert result["data_as_of"] is None
    assert result["data_status"] == "unavailable"


def test_account_valuation_clock_is_not_lost_to_newer_dimensions() -> None:
    from app.reports.models import Account

    account = Account(
        total_assets="100",
        cash="100",
        position_pct=None,
        pnl_day=None,
        position_vs_regime=None,
        data_as_of=dt.datetime.fromisoformat("2026-10-28T07:00:00Z"),
    )
    body = {
        "account": account.model_dump(mode="json"),
        "data_as_of": None,
        "stocks": [{"dimensions": [{"data_as_of": "2026-10-30T00:00:00Z"}]}],
    }
    result = project_component_clock(body, dt.datetime.fromisoformat("2026-10-30T12:00:00Z"))
    assert result["data_as_of"] == account.data_as_of
