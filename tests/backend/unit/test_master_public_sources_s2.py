"""Offline public-source boundaries and point-in-time visibility, never real securities."""

from __future__ import annotations

import datetime as dt
import socket

import pytest
from app.master import public_sources as p

DAY = dt.date(2025, 1, 6)
AFTER_CLOSE = dt.datetime(2025, 1, 6, 10, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def deny_all_network(monkeypatch):
    def reject(*args, **kwargs):
        pytest.fail("public source preparation attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


@pytest.mark.parametrize(
    "url",
    [
        p.PUBLIC_LANDING_PAGES["SH"],
        p.PUBLIC_LANDING_PAGES["SZ"],
        "https://example.invalid/fallback-must-not-be-inferred",
    ],
)
def test_unreviewed_landing_or_inferred_url_fails_closed(url):
    with pytest.raises(
        p.PublicSourceGapError, match="official_public_download_not_verified"
    ):
        p.require_public_download(url)


@pytest.mark.parametrize("day", [DAY, dt.date(2024, 2, 29)])
def test_snapshot_schedule_stays_beijing_regardless_of_local_zone(day):
    stamp = p.snapshot_time(day)
    assert (stamp.hour, stamp.minute, stamp.utcoffset()) == (
        18,
        0,
        dt.timedelta(hours=8),
    )
    assert stamp.astimezone(dt.UTC).hour == 10


def test_pit_exact_opening_boundary_is_visible_for_fallback_free_display():
    stamp = p.snapshot_time(DAY)
    assert p.point_in_time_available(DAY, stamp, stamp, trading_day=True, accepted=True)
    assert p.point_in_time_available(
        DAY, stamp, AFTER_CLOSE, trading_day=True, accepted=True
    )


@pytest.mark.parametrize(
    "trading_day,accepted", [(False, True), (None, True), (True, False), (False, False)]
)
def test_calendar_unknown_or_rejected_snapshot_has_no_history_signal(
    trading_day, accepted
):
    assert not p.point_in_time_available(
        DAY, AFTER_CLOSE, AFTER_CLOSE, trading_day=trading_day, accepted=accepted
    )


def test_wrong_photo_or_fetch_day_is_not_historic_evidence():
    previous = DAY - dt.timedelta(days=3)
    assert not p.point_in_time_available(
        DAY, p.snapshot_time(previous), AFTER_CLOSE, trading_day=True, accepted=True
    )
    assert not p.point_in_time_available(
        DAY,
        AFTER_CLOSE,
        AFTER_CLOSE - dt.timedelta(microseconds=1),
        trading_day=True,
        accepted=True,
    )


@pytest.mark.parametrize("argument", ["fetched_at", "as_of"])
def test_pit_requires_timezone(argument):
    naive = dt.datetime(2025, 1, 6, 18)
    fetched = naive if argument == "fetched_at" else AFTER_CLOSE
    as_of = naive if argument == "as_of" else AFTER_CLOSE
    with pytest.raises(ValueError, match="timezone_required"):
        p.point_in_time_available(DAY, fetched, as_of, trading_day=True, accepted=True)


@pytest.mark.parametrize("listing_status", ["delisted", "missing_from_list"])
def test_history_unavailable_returns_unknown_not_false(listing_status):
    assert p.flags("合成证券", listing_status) == {
        "f.is_st": None,
        "f.is_delisting_period": None,
    }


@pytest.mark.parametrize(
    "name,expected",
    [
        ("ST合成", True),
        ("*ST合成", True),
        ("合成普通", False),
    ],
)
def test_st_normalized_prefix(name, expected):
    assert p.flags(name, "listed") == {
        "f.is_st": expected,
        "f.is_delisting_period": False,
    }


def test_delisting_period_requires_name_and_status_consistency():
    assert p.flags("合成退", "delisting_period") == {
        "f.is_st": True,
        "f.is_delisting_period": True,
    }


@pytest.mark.parametrize(
    "name,status,reason",
    [
        ("", "listed", "name_required"),
        ("合成普通", "delisting_period", "risk_listing_status_mismatch"),
        ("合成退", "listed", "risk_listing_status_mismatch"),
        ("合成普通", "suspended", "unknown_listing_status"),
    ],
)
def test_incompatible_name_or_status_rejected(name, status, reason):
    with pytest.raises(ValueError, match=reason):
        p.flags(name, status)
