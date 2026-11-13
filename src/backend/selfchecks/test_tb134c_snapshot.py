# ruff: noqa: S101, E501
"""T-B134c: bb55fd8 §3.8, synthetic data in the explicitly identified disposable PG only."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import Connection, Engine, create_engine, delete, insert, text, update
from sqlalchemy.engine import make_url

from app.aggregates import t_view as tv
from app.api.v1 import portfolio as pf
from app.api.v1.accounts import owned_account, user_account_ids
from app.common.errors import AppError, ErrorCode
from app.db.base import SCHEMAS, metadata
from app.db.tables import accounts as ac
from app.db.tables.market import securities, trading_calendar
from app.db.tables.users import users
from app.schemas.enums import DataStatus, GapReason, SecurityType

BJ = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.date(2026, 11, 10)
UNKNOWN = "当日持仓快照没有可卖数量，无法核实今日可卖，可卖暂按 0 计"
INFERRED = "可卖数按开盘前持仓快照推算（T+1），未扣今日卖出和冻结、限售股份"
TV_UNKNOWN = "持仓快照没有可卖数量，无法核实今日可卖，暂不提供可卖数"


def at(day: int, hour: int = 15, minute: int = 30, second: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, day, hour, minute, second, tzinfo=BJ)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = os.environ.get("TB134C_TEST_DSN", "")
    parsed = make_url(url)
    if (parsed.host, parsed.port, parsed.database) != ("127.0.0.1", 55536, "tb134c_test"):
        pytest.fail("T-B134c requires its dedicated loopback database")
    db = create_engine(url, connect_args={"connect_timeout": 3})
    with db.begin() as conn:
        if conn.execute(text("SHOW cluster_name")).scalar_one() != "tb134c-isolated":
            pytest.fail("Refuse writes to an unrecognized cluster")
        for schema in SCHEMAS:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        metadata.create_all(conn)
    yield db
    db.dispose()


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as connection:
        transaction = connection.begin()
        for day in range(1, 16):
            date = dt.date(2026, 11, day)
            connection.execute(
                insert(trading_calendar).values(date=date, is_open=date.weekday() < 5)
            )
        connection.execute(
            insert(securities).values(code="600000", name="合成证券", type="stock", exchange="SH")
        )
        yield connection
        transaction.rollback()


def snapshot(
    conn: Connection,
    as_of: dt.datetime | None,
    *,
    created: dt.datetime | None = None,
    sellable: Decimal | None = None,
    ledger: bool = False,
    codes: int = 1,
) -> tuple[uuid.UUID, uuid.UUID]:
    user, account, batch, snap = [uuid.uuid4() for _ in range(4)]
    conn.execute(
        insert(users).values(
            id=user,
            username="tb134c_" + user.hex[:16],
            password_hash=uuid.uuid4().hex,
            role="user",
            status="approved",
        )
    )
    conn.execute(insert(ac.accounts).values(id=account, user_id=user, name="synthetic"))
    conn.execute(
        insert(ac.import_batches).values(
            id=batch, user_id=user, account_id=account, status="committed", kind="positions"
        )
    )
    conn.execute(
        insert(ac.broker_position_snapshots).values(
            id=snap,
            account_id=account,
            import_batch_id=batch,
            as_of=as_of,
            created_at=created or at(10, 10, 0),
            version_no=1,
            cash_balance=1000,
        )
    )
    for index in range(codes):
        code = f"{600000 + index:06d}"
        if index:
            conn.execute(
                insert(securities).values(code=code, name="合成证券", type="stock", exchange="SH")
            )
        conn.execute(
            insert(ac.broker_position_snapshot_items).values(
                snapshot_id=snap,
                security_code=code,
                quantity=200,
                sellable_quantity=sellable,
                broker_cost_price=10,
                last_price_ref=10,
            )
        )
    if ledger:
        conn.execute(
            insert(ac.opening_positions).values(
                account_id=account,
                security_code="600000",
                quantity=100,
                as_of_date=dt.date(2026, 11, 9),
            )
        )
        conn.execute(
            insert(ac.holdings).values(
                account_id=account, security_code="600000", quantity=200, avg_cost=10
            )
        )
        conn.execute(
            insert(ac.trades).values(
                account_id=account,
                user_id=user,
                security_code="600000",
                side="buy",
                quantity=100,
                price=10,
                trade_date=TODAY,
                source="manual",
            )
        )
    return user, account


def portfolio(
    conn: Connection,
    account: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    now: dt.datetime | None = None,
) -> dict:
    stamp = now or at(10, 10, 0)

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return stamp if tz is None else stamp.astimezone(tz)

    monkeypatch.setattr(
        pf,
        "dt",
        SimpleNamespace(
            datetime=Clock, date=dt.date, time=dt.time, timedelta=dt.timedelta, timezone=dt.timezone
        ),
    )
    return pf.build_portfolio(conn, [account])


def gaps(value: dict, key: str) -> list[dict]:
    return [gap for gap in value["gaps"] if gap["key"] == key]


@pytest.mark.parametrize(
    ("as_of", "created"),
    [(at(10, 10, 0), None), (None, at(10, 10, 0)), (at(10, 1, 15).replace(tzinfo=dt.UTC), None)],
)
def test_tb134c_portfolio_sellable_zero_when_today_snapshot_lacks_sellable(
    conn: Connection,
    monkeypatch: pytest.MonkeyPatch,
    as_of: dt.datetime | None,
    created: dt.datetime | None,
) -> None:
    _, account = snapshot(conn, as_of, created=created)
    value = portfolio(conn, account, monkeypatch)
    assert value["positions"][0]["sellable_qty"] == "0"
    assert gaps(value, "positions.sellable_qty") == [
        {"key": "positions.sellable_qty", "reason": "user_input_missing", "message": UNKNOWN}
    ]
    assert value["data_status"] == "partial"


@pytest.mark.parametrize(
    ("as_of", "expected", "message"),
    [
        (at(9), "200", INFERRED),
        (at(10, 9, 14, 59), "200", INFERRED),
        (at(10, 9, 15), "0", UNKNOWN),
        (at(10, 9, 26), "0", UNKNOWN),
        (at(10, 1, 14, 59).replace(tzinfo=dt.UTC), "200", INFERRED),
    ],
)
def test_tb134c_portfolio_snapshot_boundary(
    conn: Connection,
    monkeypatch: pytest.MonkeyPatch,
    as_of: dt.datetime,
    expected: str,
    message: str,
) -> None:
    _, account = snapshot(conn, as_of)
    value = portfolio(conn, account, monkeypatch)
    assert value["positions"][0]["sellable_qty"] == expected
    assert [g["message"] for g in gaps(value, "positions.sellable_qty")] == [message]


@pytest.mark.parametrize(
    ("as_of", "sellable", "expected"),
    [
        (at(10, 10, 0), Decimal(150), "150"),
        (at(10, 10, 0), Decimal(300), "200"),
        (at(9), Decimal(20), "200"),
    ],
)
def test_tb134c_existing_sellable_values_unchanged(
    conn: Connection,
    monkeypatch: pytest.MonkeyPatch,
    as_of: dt.datetime,
    sellable: Decimal,
    expected: str,
) -> None:
    _, account = snapshot(conn, as_of, sellable=sellable)
    value = portfolio(conn, account, monkeypatch)
    assert value["positions"][0]["sellable_qty"] == expected
    assert gaps(value, "positions.sellable_qty") == []


def test_tb134c_same_gap_deduplicated_across_codes(
    conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, account = snapshot(conn, at(10, 10, 0), codes=2)
    value = portfolio(conn, account, monkeypatch)
    assert [p["sellable_qty"] for p in value["positions"]] == ["0", "0"]
    assert len(gaps(value, "positions.sellable_qty")) == 1


def test_tb134c_ledger_account_sellable_unchanged(
    conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, account = snapshot(conn, at(5), ledger=True)
    value = portfolio(conn, account, monkeypatch)
    assert value["positions"][0]["sellable_qty"] == "100"
    assert gaps(value, "positions.sellable_qty") == gaps(value, "positions.snapshot") == []


@pytest.mark.parametrize(
    ("view_day", "snapshot_day", "stale"),
    [(10, 6, True), (10, 9, False), (7, 5, True), (7, 6, False), (9, 6, False), (8, 6, False)],
)
def test_tb134c_snapshot_stale_uses_previous_open_day(
    conn: Connection, monkeypatch: pytest.MonkeyPatch, view_day: int, snapshot_day: int, stale: bool
) -> None:
    _, account = snapshot(conn, at(snapshot_day))
    value = portfolio(conn, account, monkeypatch, now=at(view_day, 10, 0))
    found = gaps(value, "positions.snapshot")
    assert bool(found) is stale
    assert value["positions"][0]["sellable_qty"] == "200"
    if stale:
        assert (
            found[0]["message"]
            == f"持仓快照停在 2026-11-{snapshot_day:02d}，早于上一交易日，之后的买卖未反映，持仓与可卖可能已变"
        )
        assert value["data_status"] == "partial"


def test_tb134c_calendar_hole_is_conservatively_stale(
    conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn.execute(delete(trading_calendar).where(trading_calendar.c.date == dt.date(2026, 11, 9)))
    _, account = snapshot(conn, at(9))
    assert gaps(portfolio(conn, account, monkeypatch), "positions.snapshot")


def test_tb134c_empty_calendar_is_conservatively_stale(
    conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn.execute(delete(trading_calendar))
    _, account = snapshot(conn, at(9))
    assert gaps(portfolio(conn, account, monkeypatch), "positions.snapshot")


@pytest.mark.parametrize("permission", ["other_user", "archived", "missing"])
def test_tb134c_permission_negative_account_scope(conn: Connection, permission: str) -> None:
    user, account = snapshot(conn, at(10, 10, 0))
    if permission == "other_user":
        user = uuid.uuid4()
    elif permission == "archived":
        conn.execute(
            update(ac.accounts).where(ac.accounts.c.id == account).values(archived_at=at(10))
        )
    else:
        account = uuid.uuid4()
    auth = SimpleNamespace(user_id=user)
    with pytest.raises(AppError) as error:
        owned_account(conn, auth, account)  # type: ignore[arg-type]
    assert error.value.code is ErrorCode.NOT_FOUND
    if permission != "missing":
        assert account not in user_account_ids(conn, auth)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (at(9), "200"),
        (at(10, 9, 14, 59), "200"),
        (at(10, 9, 15), None),
        (at(10, 9, 26), None),
        (at(10, 10, 0), None),
        (None, None),
        (at(6), "200"),
    ],
)
def test_tb134c_t_view_snapshot_matches_portfolio_safety(
    conn: Connection,
    monkeypatch: pytest.MonkeyPatch,
    as_of: dt.datetime | None,
    expected: str | None,
) -> None:
    _, account = snapshot(conn, as_of)
    holding = portfolio(conn, account, monkeypatch)["positions"][0]
    basis = tv.snapshot_basis(conn, account)
    assert basis is not None
    value = tv.build(
        code="600000",
        security_type=SecurityType.STOCK,
        base_qty=Decimal(200),
        sold_today=Decimal(0),
        holding_sellable=Decimal(holding["sellable_qty"]),
        bars=[tv.Bar(at(10, 10, 0), Decimal(10), Decimal(6000), Decimal(60000))],
        history=[Decimal(24000)] * 5,
        now=at(10, 10, 0),
        trading_day=True,
        scheduled=False,
        interval_s=60,
        thresholds=None,
        base_source="snapshot",
        snapshot_as_of=basis.as_of,
        sellable_known=basis.sellable_known["600000"],
        snapshot_at=basis.snapshot_at,
        previous_open=pf.previous_open_day(conn, TODAY),
    )
    assert value.sellable_qty == expected
    assert value.data_status is DataStatus.PARTIAL
    assert any(
        g.key == "t_view.sellable_qty"
        and g.reason is GapReason.USER_INPUT_MISSING
        and g.message == (TV_UNKNOWN if expected is None else INFERRED)
        for g in value.gaps
    )
    assert holding["sellable_qty"] == ("0" if expected is None else expected)
    if as_of == at(6):
        assert any(
            g.key == "t_view.base_qty" and "早于上一交易日" in (g.message or "") for g in value.gaps
        )


def test_tb134c_snapshot_time_without_zone_is_not_preopen() -> None:
    value = tv.build(
        code="600000",
        security_type=SecurityType.STOCK,
        base_qty=Decimal(200),
        sold_today=Decimal(0),
        holding_sellable=Decimal(200),
        bars=[],
        history=[],
        now=at(10, 10, 0),
        trading_day=True,
        scheduled=False,
        interval_s=60,
        thresholds=None,
        base_source="snapshot",
        snapshot_as_of=at(10, 9, 14, 59).replace(tzinfo=None),
        sellable_known=False,
        previous_open=dt.date(2026, 11, 9),
    )
    assert value.sellable_qty is None
    assert any(g.key == "t_view.sellable_qty" and g.message == TV_UNKNOWN for g in value.gaps)
