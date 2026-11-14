"""Offline C2 window execution: injected verified page size, never live transport."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from app.ingest import daily_bars as ingest
from app.marketdata.daily_bars import DailyBar, DailyBarsResult
from test_daily_bars_batch_fetch_c2 import DAY, NOW, OWNER, world  # noqa: F401

DAYS = tuple(DAY - dt.timedelta(days=n) for n in reversed(range(5)))


@pytest.fixture
def window(world, monkeypatch):
    world.pages = []
    world.writes = []
    world.stamps = []
    monkeypatch.setattr(ingest, "window_days", lambda *args: DAYS, raising=False)
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", 5)
    monkeypatch.setattr(ingest, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 9)

    def upsert(conn, result, **options):
        world.writes.extend(result.bars)
        world.stamps.append(options["fetched_at"])
        from app.marketdata.daily_bars import UpsertStats

        return UpsertStats(len(result.bars), 0, 0, ())

    monkeypatch.setattr(ingest, "upsert_daily_bars", upsert)
    return world


def fetch(window, *, page_days=2, days=5, clock=None, **extra):
    return ingest.fetch_mairui_daily_bars(
        object(),
        trade_date=DAY,
        user_id=OWNER,
        window_trading_days=days,
        page_days=page_days,
        transport=window.transport,
        grant_reader=window.grant,
        clock=clock or (lambda: NOW),
        stop_path=window.root / "STOP",
        halt_path=window.root / "HALTED",
        **extra,
    )


def test_window_pages_are_complete_nonoverlapping_and_whole_code_budget(window):
    assert fetch(window) == 0
    assert window.calls == [
        ("999990.SH", DAYS[0], DAYS[1]),
        ("999990.SH", DAYS[2], DAYS[3]),
        ("999990.SH", DAYS[4], DAYS[4]),
    ]
    assert window.runs[-1]["status"] == "partial"
    assert window.runs[-1]["stats"]["issues"].count("daily_bars_quota_deferred") == 4


def test_unknown_k_multi_day_refuses_all_transport(window):
    assert fetch(window, page_days=None, days=700) == 0
    assert window.calls == window.writes == []
    assert window.runs[-1]["status"] == "failed"
    assert "daily_bars_history_page_size_unverified" in window.runs[-1]["stats"]["issues"]


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "2"])
def test_invalid_page_size_never_sends(window, bad):
    with pytest.raises(ValueError):
        fetch(window, page_days=bad)
    assert window.calls == window.writes == []


def test_ready_code_costs_no_pages_and_next_code_fits(window):
    assert fetch(window, code_ready=lambda code: code == "999990.SH") == 0
    assert [call[0] for call in window.calls] == ["999991.SH"] * 3


def test_all_ready_means_no_http_and_ok(window):
    assert fetch(window, code_ready=lambda code: True) == 0
    assert window.calls == []
    assert window.runs[-1]["status"] == "ok"


def test_less_than_one_whole_code_quota_sends_nothing(window, monkeypatch):
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", 2)
    assert fetch(window) == 0
    assert window.calls == []
    assert window.runs[-1]["status"] == "partial"
    assert window.runs[-1]["stats"]["issues"].count("daily_bars_quota_deferred") == 5


@pytest.mark.parametrize("signal", ["STOP", "HALTED", 103, 429])
def test_every_page_rechecks_stop_and_never_retries(window, signal):
    def send(code, start, end):
        window.calls.append((code, start, end))
        if len(window.calls) == 2:
            if isinstance(signal, str):
                (window.root / signal).touch()
            else:
                return signal, None
        return 200, None

    window.transport = send
    assert fetch(window) == 0
    assert len(window.calls) == 2
    assert "daily_bars_upstream_halted" in window.runs[-1]["stats"]["issues"]


def test_history_payload_writes_all_received_days_with_last_response_stamp(window):
    window.now = NOW

    def send(code, start, end):
        window.calls.append((code, start, end))
        window.now += dt.timedelta(seconds=1)
        value = Decimal("1")
        bars = tuple(
            DailyBar(code, day, "none", value, value, value, value, value, value, value, False)
            for day in DAYS
            if start <= day <= end
        )
        return 200, DailyBarsResult(bars=bars)

    window.transport = send
    assert fetch(window, clock=lambda: window.now) == 5
    assert window.stamps == [NOW + dt.timedelta(seconds=3)]
    assert [bar.trade_date for bar in window.writes] == list(DAYS)
    assert {bar.code for bar in window.writes} == {"999990.SH"}


@pytest.mark.parametrize(
    "field,value",
    [("code", "999999.SH"), ("trade_date", DAY + dt.timedelta(days=1)), ("adj_type", "forward")],
)
def test_foreign_or_outside_page_bar_cannot_write(window, field, value):
    from dataclasses import replace

    price = Decimal("1")
    bar = DailyBar(
        "999990.SH", DAYS[0], "none", price, price, price, price, price, price, price, False
    )
    window.transport = lambda *args: (200, DailyBarsResult(bars=(replace(bar, **{field: value}),)))
    with pytest.raises(ValueError):
        fetch(window)
    assert window.writes == []


def test_unset_budget_precedes_calendar_grant_and_transport(window, monkeypatch):
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", 0)
    monkeypatch.setattr(ingest, "window_days", lambda *args: pytest.fail("unset touched calendar"))
    assert fetch(window) == 0
    assert window.grants == window.calls == []
