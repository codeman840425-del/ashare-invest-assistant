# ruff: noqa: S101, ANN401, F811
"""T-A12 isolated seed/reader permissions and real calendar selection; no provider IO."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import ProgrammingError

from app.aggregates.calendar import market_clock, seed_calendar
from app.cli.calendar_seed import main
from app.common.errors import AppError, ErrorCode
from app.config_files import MarketRulesConfig
from app.db.tables.accounts import accounts
from app.db.tables.market import trading_calendar
from app.reference_files import REFERENCE_FILES, CalendarReference, load_reference_file
from app.strategy.cards.importing import _block
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]


def reference() -> CalendarReference:
    seed = load_reference_file(ROOT / "config", "trading_calendar.json")
    assert isinstance(seed, CalendarReference)
    return seed


def rules() -> MarketRulesConfig:
    return MarketRulesConfig.model_validate(_block((ROOT / "config/market_rules.yaml").read_text()))


def test_reference_exact_source_and_dry_command(capsys: Any) -> None:
    seed = reference()
    assert (ROOT / "config/trading_calendar.json").read_bytes() == (
        ROOT / "docs/strategies/calendar/trading_calendar_2026.json"
    ).read_bytes()
    assert REFERENCE_FILES["trading_calendar.json"] is CalendarReference
    assert len(seed.open_days) == 242
    assert "2025-12-22" in seed.source
    assert "sse.com.cn" in seed.source
    assert "szse.cn" in seed.source
    assert main(["--config-dir", str(ROOT / "config")]) == 0
    assert "dry-run" in capsys.readouterr().out


def test_seed_idempotence_db_clock_bounds_permissions(
    integration: Any, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    engine, _, _, _, _ = integration
    seed = reference()
    with engine.begin() as conn:
        seed_calendar(conn, seed)
        assert seed_calendar(conn, seed) == 0
        count, opens = conn.execute(
            select(func.count(), func.count().filter(trading_calendar.c.is_open)).where(
                trading_calendar.c.date.between(dt.date(2026, 1, 1), dt.date(2026, 12, 31))
            )
        ).one()
        assert (count, opens) == (365, 242)
        for instant, date, session in [
            ("2026-11-07T12:00:00+08:00", "2026-11-06", "non_trading_day"),
            ("2026-10-01T12:00:00+08:00", "2026-09-30", "non_trading_day"),
            ("2026-10-08T09:00:00+08:00", "2026-10-08", "pre_open"),
            ("2026-10-08T09:20:00+08:00", "2026-10-08", "call_auction"),
            ("2026-10-08T10:00:00+08:00", "2026-10-08", "morning"),
            ("2026-10-08T12:00:00+08:00", "2026-10-08", "lunch_break"),
            ("2026-10-08T14:00:00+08:00", "2026-10-08", "afternoon"),
            ("2026-10-08T14:59:00+08:00", "2026-10-08", "closing_auction"),
            ("2026-10-08T15:00:00+08:00", "2026-10-08", "closed"),
        ]:
            value = market_clock(conn, dt.datetime.fromisoformat(instant), rules())
            assert value.trade_date.isoformat() == date
            assert value.session == session
        for day in ("2025-12-31", "2027-01-01", "2026-01-01"):
            with pytest.raises(AppError) as failure:
                market_clock(conn, dt.datetime.fromisoformat(day + "T12:00:00+08:00"), rules())
            assert failure.value.code == ErrorCode.CALENDAR_NOT_COVERED
            assert failure.value.details["coverage_start"] == "2026-01-01"
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    assert main(["--config-dir", str(ROOT / "config"), "--apply"]) == 0
    assert main(["--config-dir", str(ROOT / "config"), "--apply"]) == 0
    role = "tb77_reader_" + uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f"create role {role} nologin"))
        conn.execute(text(f"grant usage on schema market to {role}"))
        conn.execute(text(f"grant select on market.trading_calendar to {role}"))
    try:
        with engine.begin() as conn:
            conn.execute(text(f"set local role {role}"))
            assert (
                market_clock(conn, dt.datetime(2026, 11, 6, 2, tzinfo=dt.UTC), rules()).session
                == "morning"
            )
        with pytest.raises(ProgrammingError), engine.begin() as conn:  # noqa: PT012
            conn.execute(text(f"set local role {role}"))
            seed_calendar(conn, seed)
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"revoke all on market.trading_calendar from {role}"))
            conn.execute(text(f"revoke all on schema market from {role}"))
            conn.execute(text(f"drop role {role}"))
    assert no_network == []


def test_account_order_archival_echo_and_no_account(integration: Any) -> None:
    engine, client, stranger, _, _ = integration
    with engine.begin() as conn:
        seed_calendar(conn, reference())
    for endpoint in ("terminal", "today"):
        value = stranger.get("/api/v1/" + endpoint)
        assert value.status_code == 200
        assert value.json()["account_id"] is None
    ids = []
    for name in ("合成甲", "合成乙"):
        response = client.post("/api/v1/accounts", json={"alias": name, "broker_name": "虚构券商"})
        assert response.status_code == 201
        ids.append(uuid.UUID(response.json()["id"]))
    tied = dt.datetime(2026, 1, 6, tzinfo=dt.UTC)
    with engine.begin() as conn:
        conn.execute(update(accounts).where(accounts.c.id.in_(ids)).values(created_at=tied))
    for endpoint in ("terminal", "today"):
        value = client.get("/api/v1/" + endpoint).json()
        assert value["account_id"] == str(min(ids))
        assert (
            stranger.get("/api/v1/" + endpoint, params={"account_id": str(min(ids))}).status_code
            == 404
        )
    with engine.begin() as conn:
        conn.execute(update(accounts).where(accounts.c.id == min(ids)).values(archived_at=tied))
    assert client.get("/api/v1/terminal").json()["account_id"] == str(max(ids))
    assert client.get("/api/v1/today", params={"account_id": str(min(ids))}).json()[
        "account_id"
    ] == str(min(ids))
