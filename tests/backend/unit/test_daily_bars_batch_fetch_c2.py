"""C2 fetch must use its explicit batch gate before any grant or transport access."""

from __future__ import annotations

import datetime as dt
import socket
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.ingest import daily_bars as ingest

OWNER = uuid.UUID(int=731)
DAY = dt.date(2026, 11, 10)
NOW = dt.datetime(2026, 11, 10, 10, tzinfo=dt.UTC)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    state = SimpleNamespace(calls=[], grants=[], runs=[], root=tmp_path)
    monkeypatch.setattr(ingest, "covered", lambda *_: True)
    monkeypatch.setattr(
        ingest, "daily_universe", lambda *_: [f"99999{i}.SH" for i in range(5)]
    )
    monkeypatch.setattr(ingest, "_record_run", lambda *_, **kw: state.runs.append(kw))

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("offline budget test attempted credentials or external IO")

    from app.ingest import daily_lists, egress

    monkeypatch.setattr(egress, "mairui_get", forbidden)
    monkeypatch.setattr(daily_lists, "credential", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    def grant() -> ingest.DailyBarsGrant:
        state.grants.append(OWNER)
        return ingest.DailyBarsGrant(
            OWNER,
            uuid.UUID(int=732),
            uuid.UUID(int=733),
            NOW - dt.timedelta(hours=1),
            NOW + dt.timedelta(hours=1),
            "synthetic-grant-digest",
        )

    def transport(code: str, start: dt.date, end: dt.date) -> tuple[int, None]:
        state.calls.append((code, start, end))
        return 200, None

    state.grant = grant
    state.transport = transport
    return state


def fetch(world: Any, kind: str = "daily", window: int | None = None) -> int:
    return ingest.fetch_mairui_daily_bars(
        object(),
        trade_date=DAY,
        user_id=OWNER,
        batch_kind=kind,
        window_trading_days=window,
        transport=world.transport,
        grant_reader=world.grant,
        clock=lambda: NOW,
        stop_path=world.root / "STOP",
        halt_path=world.root / "HALTED",
    )


def test_c2_removes_unlimited_and_keeps_both_effective_defaults_closed(
    world: Any,
) -> None:
    assert not hasattr(ingest, "DAILY_BARS_HTTP_UNLIMITED")
    assert not hasattr(ingest, "DAILY_BARS_HTTP_LIMIT")
    assert ingest.DAILY_BARS_BATCH_LIMIT == ingest.DAILY_BARS_BACKFILL_BATCH_LIMIT == 0
    assert fetch(world) == 0
    assert fetch(world, "backfill") == 0
    assert world.grants == world.calls == []
    assert all(
        "daily_bars_http_budget_unset" in run["stats"]["issues"] for run in world.runs
    )


@pytest.mark.parametrize(
    "kind,daily,backfill,expected",
    [
        ("daily", 2, 4, 2),
        ("backfill", 2, 4, 4),
        ("daily", 0, 4, 0),
        ("backfill", 4, 0, 0),
        ("daily", 500, 0, 5),
        ("daily", 501, 0, 0),
        ("daily", 2000, 0, 0),
        ("backfill", 0, 2000, 5),
        ("backfill", 0, 2001, 0),
        ("daily", "unlimited", 4, 0),
        ("backfill", 4, "unlimited", 0),
        ("daily", True, 4, 0),
        ("unsupported", 4, 4, 0),
    ],
)
def test_fetch_uses_only_selected_bounded_batch_before_grant_or_send(
    world: Any,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    daily: Any,
    backfill: Any,
    expected: int,
) -> None:
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", daily)
    monkeypatch.setattr(ingest, "DAILY_BARS_BACKFILL_BATCH_LIMIT", backfill)
    assert fetch(world, kind) == 0
    assert len(world.calls) == expected
    assert len(world.grants) == int(expected > 0)
    if expected == 0:
        assert "daily_bars_http_budget_unset" in world.runs[-1]["stats"]["issues"]
    elif expected < 5:
        assert (
            world.runs[-1]["stats"]["issues"].count("daily_bars_quota_deferred")
            == 5 - expected
        )


def test_window_never_selects_larger_backfill_gate_implicitly(
    world: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", 2)
    monkeypatch.setattr(ingest, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 4)
    assert fetch(world, window=700) == 0
    assert len(world.calls) == 2
