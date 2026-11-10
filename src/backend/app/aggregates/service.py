"""Owned ledger/product aggregation with honest gaps; DB calendar is the only 503 boundary."""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter
from decimal import Decimal
from typing import Literal

from sqlalchemy import Connection, func, select

from app.aggregates import models as m
from app.aggregates import products, t_view
from app.aggregates.reconciliation import read as read_reconciliation
from app.api.v1.portfolio import _account
from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import (
    accounts,
    broker_position_snapshots,
)
from app.db.tables.market import securities
from app.db.tables.notify import notifications
from app.db.tables.realtime import daily_reports, user_realtime_prefs
from app.db.tables.research import watchlist_items
from app.importing.pipeline import live_snapshots
from app.schemas.enums import (
    DataGapScope,
    DataStatus,
    GapReason,
    MarketSession,
    RiskLevel,
    SecurityType,
)
from app.suggestions.service import summary


def unavailable(issue: str) -> AppError:
    return AppError(ErrorCode.MAINTENANCE, details={"issue": issue})


def select_account(
    conn: Connection, user_id: uuid.UUID, identifier: uuid.UUID | None
) -> uuid.UUID | None:
    query = select(accounts.c.id).where(accounts.c.user_id == user_id)
    if identifier is not None:
        if conn.execute(query.where(accounts.c.id == identifier)).first() is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return identifier
    selected = conn.execute(
        query.where(accounts.c.archived_at.is_(None))
        .order_by(accounts.c.created_at.asc(), accounts.c.id.asc())
        .limit(1)
    ).scalar_one_or_none()
    return uuid.UUID(str(selected)) if selected is not None else None


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
    *,
    _focus_only: bool = False,
) -> m.Terminal:
    gaps = [
        gap("aggregation", "行情与部分事件来源尚未接线，已存在的本人建议按实际产物聚合。"),
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
    current = products.owned_suggestions(conn, user_id, account_id, now)
    reason_counts = Counter(
        r.security_code
        for r in products.reasons(conn, user_id, account_id, now)
        if r.status == "active"
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
                suggestion=m.SuggestionSummary.model_validate_json(
                    products.encoded(summary(current[code]))
                )
                if code in current
                else None,
                active_reason_count=reason_counts[code],
                max_risk_level=max(
                    (RiskLevel(f["level"]) for f in current[code].risk_flags or []),
                    key={
                        RiskLevel.INFO: 0,
                        RiskLevel.WARNING: 1,
                        RiskLevel.CRITICAL: 2,
                    }.__getitem__,
                    default=None,
                )
                if code in current
                else None,
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
    focused_rows, focus_more = products.focus_rows(result_rows)
    value = m.Terminal(
        server_time=now,
        trade_date=clock.trade_date,
        session=clock.session,
        account_id=account_id,
        account=account_out,
        rows=focused_rows[:50] if _focus_only else result_rows[:300],
        truncated=len(result_rows) > 300,
        unread_notifications=int(unread),
        data_status=DataStatus.PARTIAL,
        data_as_of=None,
        gaps=gaps,
    )
    value._focus_more = focus_more
    return value


def today(
    conn: Connection,
    user_id: uuid.UUID,
    account_id: uuid.UUID | None,
    clock: m.MarketClock,
    now: dt.datetime,
    *,
    interval_s: int,
) -> m.Today:
    base = terminal(conn, user_id, account_id, clock, now, "all", _focus_only=True)
    recon = read_reconciliation(conn, account_id, now)
    reconciliation = m.Reconciliation.model_validate_json(
        products.encoded(
            {k: recon[k] for k in ["status", "as_of", "diff_count", "important_count"]}
        )
    )
    current = products.owned_suggestions(conn, user_id, account_id, now)
    reason_rows = products.reasons(conn, user_id, account_id, now)
    names = {r.code: r.name for r in conn.execute(select(securities.c.code, securities.c.name))}
    actual = products.blocks(
        conn, user_id, account_id, now, clock.trade_date, current, names, reason_rows
    )
    base.gaps.extend(gap(key, message) for key, message in actual["gaps"])
    reports = (
        conn.execute(
            select(daily_reports.c.status)
            .where(
                daily_reports.c.user_id == user_id,
                daily_reports.c.trade_date == clock.trade_date,
                daily_reports.c.account_id == account_id,
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
    trades = t_view.today_trades(conn, account_id, clock.trade_date) if account_id else {}
    focus = []
    for row in base.rows:
        view = None
        if row.holding is not None:
            code = row.security_code
            qty = Decimal(row.holding.qty)
            bought, sold = trades.get(code, (Decimal(0), Decimal(0)))
            view = t_view.build(
                code=code,
                security_type=row.holding.security_type,
                base_qty=qty - bought + sold,
                sold_today=sold,
                holding_sellable=Decimal(row.holding.sellable_qty),
                bars=t_view.today_bars(conn, code, clock.trade_date, now),
                history=t_view.history_volumes(conn, code, clock.trade_date),
                now=now,
                trading_day=clock.session is not MarketSession.NON_TRADING_DAY
                and clock.trade_date == now.astimezone(t_view.BEIJING).date(),
                # M3 盘中采集未接线，没有排程信息，按 §3.7⑥ 没数据即 unavailable。
                scheduled=False,
                interval_s=interval_s,
                thresholds=t_view.THRESHOLDS,
            )
        focus.append(
            m.TodayRow(**{k: getattr(row, k) for k in m.TerminalRow.model_fields}, t_view=view)
        )
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
        account_id=account_id,
        market=m.TodayMarket(
            regime=None, regime_position_range=None, data_status=DataStatus.UNAVAILABLE
        ),
        focus=m.Focus(items=focus[:50], more=base._focus_more),
        pending_plan_drafts=actual["pending_plan_drafts"],
        released_reasons=actual["released_reasons"],
        risk_flags=actual["risk_flags"],
        invalidations_today=actual["invalidations_today"],
        daily_report=m.Report(date=clock.trade_date, status=status),
        reconciliation=reconciliation,
        unread_notifications=base.unread_notifications,
        alerts=empty,
        plan_triggers=empty,
        data_gaps=m.GapBlock(items=action_gaps, more=False),
        evidence=actual["evidence"],
        data_status=DataStatus.PARTIAL,
        data_as_of=None,
        gaps=base.gaps,
    )
