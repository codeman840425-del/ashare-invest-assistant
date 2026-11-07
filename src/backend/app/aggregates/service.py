"""T-B77 conservative skeleton: own imported ledger facts, no shared vendor reads.

Clock/default-account policies are NOT guessed. Missing clock is an explicit 503;
nonempty unintegrated products also fail closed rather than pretending they are empty.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from sqlalchemy import Connection, Table, func, literal, select, union_all

from app.aggregates import models as m
from app.api.v1.portfolio import _account
from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import (
    accounts,
    broker_position_snapshots,
    reconciliation_items,
    reconciliation_runs,
)
from app.db.tables.market import securities
from app.db.tables.notify import notifications
from app.db.tables.realtime import daily_reports, suggestions, user_realtime_prefs
from app.db.tables.research import action_plans, alerts, watchlist_items
from app.db.tables.signals import non_executable_reasons, plan_drafts
from app.db.tables.strategy import risk_events
from app.importing.pipeline import live_snapshots
from app.schemas.enums import (
    DataGapScope,
    DataStatus,
    GapReason,
    ReconciliationStatus,
    SecurityType,
)


def unavailable(issue: str) -> AppError:
    return AppError(ErrorCode.MAINTENANCE, details={"issue": issue})


def select_account(
    conn: Connection, user_id: uuid.UUID, identifier: uuid.UUID | None
) -> uuid.UUID | None:
    query = select(accounts.c.id).where(
        accounts.c.user_id == user_id, accounts.c.archived_at.is_(None)
    )
    if identifier is not None:
        if conn.execute(query.where(accounts.c.id == identifier)).first() is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return identifier
    identifiers = list(conn.execute(query.limit(2)).scalars())
    if len(identifiers) > 1:
        raise unavailable("default_account_not_defined")
    return uuid.UUID(str(identifiers[0])) if identifiers else None


def ensure_empty_products(conn: Connection, user_id: uuid.UUID) -> None:
    tables: tuple[Table, ...] = (
        suggestions,
        plan_drafts,
        non_executable_reasons,
        risk_events,
        alerts,
        action_plans,
    )
    query = union_all(
        *(
            select(literal(table.name)).where(
                select(table.c.id).where(table.c.user_id == user_id).exists()
            )
            for table in tables
        )
    )
    if conn.execute(query).first() is not None:
        raise unavailable("nonempty_products_require_full_aggregation")


def gap(key: str, message: str, reason: GapReason = GapReason.NO_SOURCE) -> m.Gap:
    return m.Gap(key=key, reason=reason, message=message)


def market(clock: m.MarketClock) -> m.MarketOverview:
    return m.MarketOverview(
        trade_date=clock.trade_date,
        session=clock.session,
        indices=[],
        breadth=None,
        regime=None,
        regime_position_range=None,
        turnover_total=None,
        data_status=DataStatus.UNAVAILABLE,
        data_as_of=None,
        gaps=[gap("market", "行情聚合尚未接线；没有伪造指数、宽度或市场环境。")],
    )


def terminal(
    conn: Connection,
    user_id: uuid.UUID,
    account_id: uuid.UUID | None,
    clock: m.MarketClock,
    now: dt.datetime,
    scope: str,
) -> m.Terminal:
    ensure_empty_products(conn, user_id)
    gaps = [
        gap("aggregation", "契约桩：建议/行情尚未接线，不代表完整聚合验收通过。"),
        gap("account.pnl_day", "缺少上日基准，日盈亏不可计算。"),
    ]
    watched = conn.execute(
        select(watchlist_items)
        .where(watchlist_items.c.user_id == user_id, watchlist_items.c.removed_at.is_(None))
        .order_by(watchlist_items.c.added_at)
    ).all()
    watch_codes = [row.security_code for row in watched]
    focused = set(
        conn.execute(
            select(user_realtime_prefs.c.focus_codes).where(
                user_realtime_prefs.c.user_id == user_id
            )
        ).scalar_one_or_none()
        or []
    )
    # Existing own-account reader reuses real imports/holdings/T+1; unlike build_portfolio,
    # it never reads unscoped market.daily_bars or another certificate's cache.
    account = (
        _account(conn, account_id, now.astimezone(dt.timezone(dt.timedelta(hours=8))).date())
        if account_id
        else None
    )
    positions = account.positions if account else {}
    codes = set(
        watch_codes
        if scope == "watchlist"
        else positions
        if scope == "holdings"
        else list(positions) + watch_codes
    )
    master = (
        {
            row.code: row
            for row in conn.execute(select(securities).where(securities.c.code.in_(codes)))
        }
        if codes
        else {}
    )
    values = {
        code: position.qty
        * (
            position.price
            if position.price is not None and code in master
            else position.cost_total / position.qty
        )
        for code, position in positions.items()
    }
    cash_known = account is not None and account.cash is not None
    cash = account.cash if account and account.cash is not None else Decimal(0)
    total = sum(values.values(), Decimal(0)) + cash
    if not cash_known:
        gaps.append(
            gap("cash", "未录入可核实的现金余额，仓位比例不可计算。", GapReason.USER_INPUT_MISSING)
        )
    result_rows = []
    for code in codes:
        position = positions.get(code)
        info = master.get(code)
        holding = None
        if position is not None:
            if not position.cost_known:
                gaps.append(
                    gap(
                        "positions.cost",
                        "持仓成本缺失，成本按0输出但不可视为真实成本。",
                        GapReason.USER_INPUT_MISSING,
                    )
                )
            cost = position.cost_total / position.qty
            known = info is not None and position.price is not None and position.cost_known
            pnl = (
                position.qty * (position.price - cost)
                if known and position.price is not None
                else None
            )
            holding = m.TerminalHolding(
                qty=str(position.qty),
                sellable_qty=str(position.sellable),
                cost_price=str(cost),
                weight_pct=str(values[code] / total * 100) if total > 0 else "0",
                pnl=str(pnl) if pnl is not None else None,
                pnl_pct=str(pnl / position.cost_total * 100)
                if pnl is not None and position.cost_total > 0
                else None,
                security_type=SecurityType(info.type) if info else None,
                estimated=not known,
            )
        result_rows.append(
            m.TerminalRow(
                security_code=code,
                name=info.name if info else code,
                in_watchlist=code in watch_codes,
                focus=code in focused,
                quote=None,
                holding=holding,
                suggestion=None,
                active_reason_count=0,
                max_risk_level=None,
                data_status=DataStatus.PARTIAL,
                data_as_of=None,
            )
        )
    watch_order = {code: index for index, code in enumerate(watch_codes)}
    result_rows.sort(
        key=lambda row: (
            0 if row.holding else 1 if row.focus else 2,
            -Decimal(row.holding.weight_pct)
            if row.holding
            else Decimal(watch_order.get(row.security_code, 0)),
            row.security_code,
        )
    )
    account_out = None
    if account_id is not None:
        snap = conn.execute(
            live_snapshots(account_id)
            .order_by(broker_position_snapshots.c.version_no.desc())
            .limit(1)
        ).first()
        available = snap.cash_available if snap and snap.cash_available is not None else cash
        account_out = m.Account(
            account_id=account_id,
            total_assets=str(total),
            cash_available=str(available),
            position_pct=str(sum(values.values(), Decimal(0)) / total * 100)
            if cash_known and total > 0
            else None,
            pnl_day=None,
            regime=None,
            regime_position_range=None,
            data_status=DataStatus.PARTIAL,
        )
    unread = conn.execute(
        select(func.count())
        .select_from(notifications)
        .where(notifications.c.user_id == user_id, notifications.c.read_at.is_(None))
    ).scalar_one()
    return m.Terminal(
        server_time=now,
        trade_date=clock.trade_date,
        session=clock.session,
        account=account_out,
        rows=result_rows[:300],
        truncated=len(result_rows) > 300,
        unread_notifications=int(unread),
        data_status=DataStatus.PARTIAL,
        data_as_of=None,
        gaps=gaps,
    )


def today(
    conn: Connection,
    user_id: uuid.UUID,
    account_id: uuid.UUID | None,
    clock: m.MarketClock,
    now: dt.datetime,
) -> m.Today:
    base = terminal(conn, user_id, account_id, clock, now, "all")
    if base.truncated:
        raise unavailable("focus_aggregation_pending_large_universe")
    reconciliation = m.Reconciliation(
        status=ReconciliationStatus.NOT_IMPORTED, as_of=None, diff_count=0, important_count=0
    )
    if account_id:
        run = conn.execute(
            select(reconciliation_runs)
            .where(reconciliation_runs.c.account_id == account_id)
            .order_by(reconciliation_runs.c.created_at.desc())
            .limit(1)
        ).first()
        if run is not None:
            count = conn.execute(
                select(func.count())
                .select_from(reconciliation_items)
                .where(reconciliation_items.c.run_id == run.id)
            ).scalar_one()
            if count:
                raise unavailable("reconciliation_item_importance_adapter_pending")
            reconciliation = m.Reconciliation(
                status=ReconciliationStatus(run.status),
                as_of=run.created_at,
                diff_count=0,
                important_count=0,
            )
    reports = (
        conn.execute(
            select(daily_reports.c.status)
            .where(
                daily_reports.c.user_id == user_id, daily_reports.c.trade_date == clock.trade_date
            )
            .order_by(daily_reports.c.revision.desc())
        )
        .scalars()
        .all()
    )
    status: Literal["ready", "generating", "not_yet"] = (
        "ready"
        if any(state in {"ready", "partial"} for state in reports)
        else "generating"
        if "building" in reports
        else "not_yet"
    )
    focus = [row for row in base.rows if row.focus]
    empty = m.EmptyBlock(items=(), more=False)
    action_gaps = [
        m.TodayGap(
            key=item.key,
            reason=item.reason,
            scope=DataGapScope.ACCOUNT,
            dataset=None,
            message=item.message,
            security_count=0,
            securities=[],
            since=None,
            route="/portfolio/import",
        )
        for item in base.gaps
        if item.reason is GapReason.USER_INPUT_MISSING
    ]
    return m.Today(
        server_time=now,
        trade_date=clock.trade_date,
        session=clock.session,
        market=m.TodayMarket(
            regime=None, regime_position_range=None, data_status=DataStatus.UNAVAILABLE
        ),
        focus=m.Focus(items=focus[:50], more=len(focus) > 50),
        pending_plan_drafts=empty,
        released_reasons=empty,
        risk_flags=empty,
        invalidations_today=empty,
        daily_report=m.Report(date=clock.trade_date, status=status),
        reconciliation=reconciliation,
        unread_notifications=base.unread_notifications,
        alerts=empty,
        plan_triggers=empty,
        data_gaps=m.GapBlock(items=action_gaps, more=False),
        evidence=(),
        data_status=DataStatus.PARTIAL,
        data_as_of=None,
        gaps=base.gaps,
    )
