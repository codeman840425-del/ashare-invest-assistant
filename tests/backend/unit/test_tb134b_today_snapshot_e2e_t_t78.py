"""T-T78 / T-B134b：§3.8 ④ 快照→today 服务层端到端连库用例。

覆盖 reports/T-B134b.md 待办第④项：无成交流水账户的最新持仓快照经 service.today
为持仓行生成 t_view（base_qty gap；可卖为空则为 null + sellable gap）。
只在 o61-pg 127.0.0.1:55461 自建临时库 o61_tmp_b133_*，用后 DROP。不调用麦蕊。
合成代码 600001/600002，无真实样本。
"""

from __future__ import annotations

import datetime as dt
import sys
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.engine import Engine

_BACKEND = Path(__file__).resolve().parents[3] / "src" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.aggregates import service
from app.aggregates import t_view as tv
from app.aggregates.models import MarketClock
from app.db.tables.accounts import (
    accounts,
    broker_position_snapshot_items,
    broker_position_snapshots,
    import_batches,
)
from app.db.tables.market import securities
from app.db.tables.users import users
from app.schemas.enums import DataStatus, GapReason, MarketSession
from selfchecks.test_tb127_daily_bars import _upgrade
from selfchecks.test_tb133_tdx_db import temp_db

BJ = dt.timezone(dt.timedelta(hours=8))
DAY = dt.date(2026, 11, 10)
AS_OF = dt.datetime(2026, 11, 10, 10, 0, tzinfo=BJ)
NOW = dt.datetime(2026, 11, 10, 10, 0, 30, tzinfo=BJ)
CODE_HAS = "600001"
CODE_NULL = "600002"


@pytest.fixture(scope="module")
def db() -> Iterator[Engine]:
    with temp_db() as url:
        _upgrade(url, "head")
        engine = create_engine(url)
        try:
            yield engine
        finally:
            engine.dispose()


def test_t_view_snapshot_without_trades_today_service_e2e(db: Engine) -> None:
    user_id, account_id, batch_id, snap_id = (uuid.uuid4() for _ in range(4))
    with db.begin() as conn:
        conn.execute(
            insert(users).values(
                id=user_id,
                username="tt78c_u1",
                password_hash="x",
                display_name="合成",
                role="user",
                status="approved",
            )
        )
        conn.execute(
            insert(accounts).values(id=account_id, user_id=user_id, name="合成账户")
        )
        for code, name in ((CODE_HAS, "合成有可卖"), (CODE_NULL, "合成无可卖")):
            conn.execute(
                insert(securities).values(
                    code=code,
                    type="stock",
                    name=name,
                    exchange="SH",
                    listing_status="listed",
                )
            )
        conn.execute(
            insert(import_batches).values(
                id=batch_id,
                user_id=user_id,
                account_id=account_id,
                status="committed",
                kind="positions",
            )
        )
        conn.execute(
            insert(broker_position_snapshots).values(
                id=snap_id,
                account_id=account_id,
                import_batch_id=batch_id,
                as_of=AS_OF,
                version_no=1,
                created_at=AS_OF,
            )
        )
        conn.execute(
            insert(broker_position_snapshot_items),
            [
                {
                    "id": uuid.uuid4(),
                    "snapshot_id": snap_id,
                    "security_code": CODE_HAS,
                    "quantity": Decimal(800),
                    "sellable_quantity": Decimal(800),
                    "broker_cost_price": Decimal(10),
                    "last_price_ref": Decimal(10),
                },
                {
                    "id": uuid.uuid4(),
                    "snapshot_id": snap_id,
                    "security_code": CODE_NULL,
                    "quantity": Decimal(500),
                    "sellable_quantity": None,
                    "broker_cost_price": Decimal(10),
                    "last_price_ref": Decimal(10),
                },
            ],
        )

    with db.connect() as conn:
        basis = tv.snapshot_basis(conn, account_id)
        assert basis is not None
        as_of, known = basis
        assert as_of == AS_OF
        assert known == {CODE_HAS: True, CODE_NULL: False}
        out = service.today(
            conn,
            user_id,
            account_id,
            MarketClock(trade_date=DAY, session=MarketSession.MORNING),
            NOW,
            interval_s=60,
        )

    views = {row.security_code: row.t_view for row in out.focus.items}
    assert set(views) == {CODE_HAS, CODE_NULL}
    has = views[CODE_HAS]
    missing = views[CODE_NULL]
    assert has is not None and missing is not None
    assert has.base_qty == "800" and missing.base_qty == "500"
    # 时点 10:00：两行都有 base_qty gap；无分时时 data_status 可为 unavailable（至少 partial）。
    for view in (has, missing):
        base = [g for g in view.gaps if g.key == "t_view.base_qty"]
        assert len(base) == 1
        assert base[0].reason is GapReason.USER_INPUT_MISSING
        assert base[0].message == "未导入今日成交流水，底仓按持仓快照计，可能含今日买入"
        assert view.data_status in {DataStatus.PARTIAL, DataStatus.UNAVAILABLE}
    assert has.sellable_qty == "800"
    assert all(g.key != "t_view.sellable_qty" for g in has.gaps)
    assert missing.sellable_qty is None
    sellable = [g for g in missing.gaps if g.key == "t_view.sellable_qty"]
    assert len(sellable) == 1
    assert sellable[0].reason is GapReason.USER_INPUT_MISSING
    # 未验证 / 待架构确认：message 文案只核对实现现行字，不作为契约验收。
    assert sellable[0].message == "持仓快照无可卖数量，暂不提供可卖数"
