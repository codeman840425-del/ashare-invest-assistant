# ruff: noqa: S101
"""Offline source/PIT guards only; no claim of snapshot persistence acceptance."""

import datetime as dt

import pytest

from app.master.public_sources import (
    BEIJING,
    PublicSourceGapError,
    flags,
    point_in_time_available,
    require_public_download,
    snapshot_time,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://query.sse.com.cn/sseQuery/commonQuery.do",
        "https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110&TABKEY=tab1",
        "https://www.bse.cn/nqxxController/nqxxCnzq.do",
        "https://www.sse.com.cn/assortment/stock/list/share/",
        "https://untrusted.invalid/list.csv",
    ],
)
def test_unverified_legacy_api_and_landing_page_never_substitute_download(url: str) -> None:
    with pytest.raises(PublicSourceGapError, match="not_verified"):
        require_public_download(url)


@pytest.mark.parametrize(
    ("name", "status", "st", "delisting"),
    [
        ("合成普通", "listed", False, False),
        ("ST合成", "listed", True, False),
        ("*ST合成", "listed", True, False),
        ("合成退", "delisting_period", True, True),
        ("合成退", "delisted", None, None),
        ("合成普通", "missing_from_list", None, None),
    ],
)
def test_exact_existing_flag_semantics(
    name: str, status: str, st: bool | None, delisting: bool | None
) -> None:
    assert flags(name, status) == {"f.is_st": st, "f.is_delisting_period": delisting}


def test_real_acquisition_timestamp_not_start_of_day_or_historical_date() -> None:
    day = dt.date(2026, 11, 6)
    fetched = dt.datetime(2026, 11, 6, 18, 5, tzinfo=BEIJING)
    assert snapshot_time(day).isoformat().endswith("18:00:00+08:00")
    assert not point_in_time_available(
        day, fetched, fetched - dt.timedelta(seconds=1), trading_day=True, accepted=True
    )
    assert point_in_time_available(day, fetched, fetched, trading_day=True, accepted=True)
    for accepted, trading_day in [(False, True), (True, False), (True, None)]:
        assert not point_in_time_available(
            day, fetched, fetched, trading_day=trading_day, accepted=accepted
        )
    assert not point_in_time_available(
        day - dt.timedelta(days=1), fetched, fetched, trading_day=True, accepted=True
    )
    with pytest.raises(ValueError, match="timezone_required"):
        point_in_time_available(
            day, fetched.replace(tzinfo=None), fetched, trading_day=True, accepted=True
        )


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("", "listed"),
        ("合成普通", "delisting_period"),
        ("合成退", "listed"),
        ("合成普通", "unknown"),
    ],
)
def test_invalid_inputs_not_silently_accepted(name: str, status: str) -> None:
    with pytest.raises(
        ValueError, match=r"name_required|risk_listing_status_mismatch|unknown_listing_status"
    ):
        flags(name, status)
