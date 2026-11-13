"""Real disposable PostgreSQL: default bars reader and authorized ingest ownership.

PGHOST/PGPORT/PGUSER/PGPASSWORD select only a loopback test service. Each test
creates and drops its own random empty s2bars_* database, never an existing DB.
"""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import ProgrammingError
from starlette.datastructures import QueryParams

from app.auth import deps
from app.auth.sessions import SESSION_COOKIE, Session
from app.config import Settings
from app.db.tables.market import daily_bars, trading_calendar
from app.ingest import daily_bars as ingest
from app.main import create_app
from app.marketdata import owned_daily_read
from app.marketdata.bars_read import BarsQuery, BarsResponse, get_bars_reader
from app.marketdata.daily_bars import DailyBar
from selfchecks.test_b04_bars import MemorySessions

NOW = dt.datetime(2026, 11, 12, 10, tzinfo=dt.UTC)
DAY = dt.date(2026, 11, 12)
OWNER, OTHER, LID = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)
CODE = "999991.SH"


def query(raw: str = "freq=d&adjust=none") -> BarsQuery:
    return BarsQuery.parse(QueryParams(raw))


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    assert os.environ.get("PGHOST") in {"127.0.0.1", "::1"}, (
        "explicit loopback PG test service required"
    )
    name = "s2bars_" + uuid.uuid4().hex
    admin = psycopg.connect(dbname="postgres", autocommit=True)
    engine = None
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        url = URL.create(
            "postgresql+psycopg",
            username=os.environ["PGUSER"],
            password=os.environ.get("PGPASSWORD"),
            host=os.environ["PGHOST"],
            port=int(os.environ["PGPORT"]),
            database=name,
        )
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA market"))
            conn.execute(text("CREATE SCHEMA app"))
            conn.execute(text("CREATE TABLE market.securities (code TEXT PRIMARY KEY, name TEXT)"))
            conn.execute(
                text("CREATE TABLE market.security_code_history (code TEXT, old_code TEXT)")
            )
            conn.execute(
                text(
                    "CREATE TABLE app.user_data_licence_status (id UUID, user_id UUID, "
                    "status TEXT, deleted_at TIMESTAMPTZ, paused_until TIMESTAMPTZ, "
                    "expires_on DATE)"
                )
            )
            conn.execute(text("CREATE TABLE app.user_data_licence_holds (user_id UUID)"))
            conn.execute(
                text("INSERT INTO market.securities VALUES (:code,'合成股份')"), {"code": CODE}
            )
            conn.execute(
                text(
                    "INSERT INTO app.user_data_licence_status (id,user_id,status) "
                    "VALUES (:lid,:uid,'active')"
                ),
                {"lid": LID, "uid": OWNER},
            )
            daily_bars.create(conn)
            trading_calendar.create(conn)
            conn.execute(
                insert(trading_calendar),
                [{"date": DAY - dt.timedelta(days=n), "is_open": True} for n in range(5)],
            )
        monkeypatch.setattr(owned_daily_read, "_now", lambda: NOW)
        yield SimpleNamespace(engine=engine, reader=get_bars_reader(engine))
    finally:
        if engine is not None:
            engine.dispose()
        assert name.startswith("s2bars_")
        assert len(name) == 39
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        assert (
            admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone() is None
        )
        admin.close()


def seed(
    world: Any,
    *,
    day: dt.date = DAY,
    lid: uuid.UUID | None = LID,
    source: str | None = "mairui",
    **extra: Any,
) -> None:
    row = {
        "code": CODE,
        "trade_date": day,
        "adj_type": "none",
        "open": Decimal("10"),
        "high": Decimal("12"),
        "low": Decimal("9"),
        "close": Decimal("11"),
        "volume": Decimal("100"),
        "amount": Decimal("1050"),
        "pre_close": None,
        "is_suspended": False,
        "source": source,
        "source_licence_id": lid,
        "fetched_at": NOW,
    }
    row.update(extra)
    with world.engine.begin() as conn:
        conn.execute(insert(daily_bars).values(**row))


def test_default_reader_returns_owned_daily_prices(world: Any) -> None:
    seed(world)
    result = world.reader.read(OWNER, CODE, query())
    BarsResponse.model_validate(result)
    assert result["data_status"] == "fresh"
    assert result["gaps"] == []
    assert result["data_as_of"] == NOW.astimezone(owned_daily_read.BEIJING).isoformat()
    assert result["items"][0] == {
        "t": DAY.isoformat(),
        "open": "10.0000",
        "high": "12.0000",
        "low": "9.0000",
        "close": "11.0000",
        "volume": "100.0000",
        "amount": "1050.0000",
        "pre_close": None,
        "avg_price": "10.5",
        "is_final": True,
    }
    assert result["adjust_as_of"] is None
    assert result["pre_close"] is None
    assert world.reader.read(OTHER, CODE, query())["items"] == []


@pytest.mark.parametrize(
    ("lid", "source"),
    [
        (None, "mairui"),
        (uuid.UUID(int=9), "mairui"),
        (LID, "fake"),
        (LID, "tdx_local"),
        (LID, None),
    ],
)
def test_unowned_and_wrong_source_rows_are_never_used(world: Any, lid: Any, source: Any) -> None:
    seed(world, lid=lid, source=source)
    result = world.reader.read(OWNER, CODE, query())
    assert result["items"] == []
    assert result["data_as_of"] is None
    assert result["gaps"][0]["reason"] == "no_source"


@pytest.mark.parametrize("change", ["invalid", "expired", "deleted", "paused", "held", "replaced"])
def test_unavailable_or_replaced_certificate_cannot_reuse_cache(world: Any, change: str) -> None:
    seed(world)
    statements = {
        "invalid": "status='invalid'",
        "expired": "expires_on='2026-11-11'",
        "deleted": "deleted_at='2026-11-12T09:00:00Z'",
        "paused": "paused_until='2026-11-13T00:00:00Z'",
        "replaced": "id=:replacement",
    }
    with world.engine.begin() as conn:
        if change == "held":
            conn.execute(
                text("INSERT INTO app.user_data_licence_holds VALUES (:uid)"), {"uid": OWNER}
            )
        else:
            conn.execute(
                text("UPDATE app.user_data_licence_status SET " + statements[change]),  # noqa: S608
                {"replacement": uuid.UUID(int=99)},
            )
    result = world.reader.read(OWNER, CODE, query())
    assert result["items"] == []
    assert result["data_as_of"] is None
    assert result["gaps"][0]["reason"] == (
        "no_source" if change == "replaced" else "data_licence_unavailable"
    )


def test_daily_dates_pagination_and_no_relabelling(world: Any) -> None:
    for n in range(4):
        seed(world, day=DAY - dt.timedelta(days=n))
    page = world.reader.read(OWNER, CODE, query("freq=d&adjust=none&limit=2"))
    assert [item["t"] for item in page["items"]] == ["2026-11-11", "2026-11-12"]
    assert page["next_before"] == "2026-11-11"
    older = world.reader.read(OWNER, CODE, query("freq=d&adjust=none&limit=2&before=2026-11-11"))
    assert [item["t"] for item in older["items"]] == ["2026-11-09", "2026-11-10"]
    assert older["next_before"] is None
    bounded = world.reader.read(
        OWNER, CODE, query("freq=d&adjust=none&from=2026-11-10&to=2026-11-11")
    )
    assert [item["t"] for item in bounded["items"]] == ["2026-11-10", "2026-11-11"]
    for raw in ("freq=d", "freq=w&adjust=none", "freq=1m", "freq=d&adjust=hfq"):
        assert world.reader.read(OWNER, CODE, query(raw))["items"] == []


def test_suspension_incomplete_future_and_calendar_gap(world: Any) -> None:
    seed(world, is_suspended=True, open=None)
    seed(world, day=DAY - dt.timedelta(days=1), amount=None)
    seed(world, day=DAY - dt.timedelta(days=2), fetched_at=NOW + dt.timedelta(seconds=1))
    result = world.reader.read(OWNER, CODE, query())
    assert result["items"] == []
    assert {gap["reason"] for gap in result["gaps"]} == {
        "suspended",
        "no_source",
    }
    with world.engine.begin() as conn:
        conn.execute(daily_bars.delete())
        conn.execute(trading_calendar.delete())
    seed(world)
    assert world.reader.read(OWNER, CODE, query())["data_status"] == "stale"


def test_registered_http_uses_default_owned_reader(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(world)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=None,
        redis_url=None,
        session_cookie_secure=False,
    )
    app = create_app(settings)
    store = MemorySessions(
        {
            key: Session("synthetic", str(uid), "synthetic", NOW.isoformat())
            for key, uid in (("a", OWNER), ("b", OTHER))
        }
    )
    app.dependency_overrides[deps.get_engine] = lambda: world.engine
    app.dependency_overrides[deps.get_session_store] = lambda: store
    monkeypatch.setattr(
        deps, "load_user", lambda _engine, uid: SimpleNamespace(id=uid, status="approved")
    )
    path = f"/api/v1/securities/{CODE}/bars?freq=d&adjust=none&user_id={OTHER}"
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, "a")
        first = client.get(path)
        assert first.status_code == 200
        assert first.json()["items"][0]["close"] == "11.0000"
        assert first.headers["cache-control"] == "private, no-store"
        cached = client.get(path, headers={"If-None-Match": first.headers["etag"]})
        assert cached.status_code == 304
        assert cached.content == b""
        client.cookies.set(SESSION_COOKIE, "b")
        other = client.get(path, headers={"If-None-Match": first.headers["etag"]})
        assert other.status_code == 200
        assert other.json()["items"] == []
        assert other.json()["gaps"][0]["reason"] == "data_licence_unavailable"
        client.cookies.clear()
        assert client.get(path, headers={"If-None-Match": first.headers["etag"]}).status_code == 401


def test_read_never_writes_and_sql_errors_propagate(world: Any) -> None:
    seed(world)
    with world.engine.begin() as conn:
        before = list(conn.execute(select(daily_bars)))
    world.reader.read(OWNER, CODE, query())
    with world.engine.begin() as conn:
        assert list(conn.execute(select(daily_bars))) == before
        conn.execute(text("DROP TABLE market.daily_bars"))
    with pytest.raises(ProgrammingError):
        world.reader.read(OWNER, CODE, query())


def test_authorized_ingest_persists_same_grant_and_default_reader_consumes(
    world: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    grant = ingest.DailyBarsGrant(
        OWNER,
        LID,
        uuid.UUID(int=4),
        NOW - dt.timedelta(hours=1),
        NOW + dt.timedelta(hours=1),
        "0" * 64,
    )
    calls: list[str] = []

    def transport(code: str, start: dt.date, end: dt.date) -> tuple[int, DailyBar]:
        calls.append(code)
        return 200, DailyBar(
            code,
            DAY,
            "none",
            Decimal(10),
            Decimal(12),
            Decimal(9),
            Decimal(11),
            Decimal(9),
            Decimal(100),
            Decimal(1050),
            False,
        )

    monkeypatch.setattr(ingest, "DAILY_BARS_HTTP_LIMIT", 1)
    monkeypatch.setattr(ingest, "daily_universe", lambda *_: [CODE])
    monkeypatch.setattr(ingest, "_record_run", lambda *_args, **_kwargs: None)
    with world.engine.begin() as conn:
        written = ingest.fetch_mairui_daily_bars(
            conn,
            trade_date=DAY,
            user_id=OWNER,
            transport=transport,
            grant_reader=lambda: grant,
            clock=lambda: NOW,
            stop_path=tmp_path / "STOP",
            halt_path=tmp_path / "HALT",
        )
        assert written == 1
        assert conn.execute(select(daily_bars.c.source_licence_id)).scalar_one() == LID
    assert calls == [CODE]
    assert world.reader.read(OWNER, CODE, query())["items"][0]["close"] == "11.0000"
    assert world.reader.read(OTHER, CODE, query())["items"] == []


@pytest.mark.parametrize(
    "bad", [None, object(), {"limit": "unlimited"}, "other", "expired", "future"]
)
def test_invalid_grant_never_reaches_transport(
    world: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, bad: Any
) -> None:
    grant = bad
    if isinstance(bad, str):
        grant = ingest.DailyBarsGrant(
            OTHER if bad == "other" else OWNER,
            LID,
            uuid.UUID(int=4),
            NOW + dt.timedelta(seconds=1) if bad == "future" else NOW - dt.timedelta(hours=1),
            NOW if bad == "expired" else NOW + dt.timedelta(hours=1),
            "0" * 64,
        )
    monkeypatch.setattr(ingest, "DAILY_BARS_HTTP_LIMIT", 1)
    monkeypatch.setattr(ingest, "_record_run", lambda *_args, **_kwargs: None)
    calls: list[str] = []
    with world.engine.begin() as conn:
        written = ingest.fetch_mairui_daily_bars(
            conn,
            trade_date=DAY,
            user_id=OWNER,
            transport=lambda *_: calls.append("forbidden"),
            grant_reader=lambda: grant,
            clock=lambda: NOW,
            stop_path=tmp_path / "STOP",
            halt_path=tmp_path / "HALT",
        )
        assert written == 0
        assert calls == []
        assert conn.execute(select(daily_bars.c.code)).all() == []
