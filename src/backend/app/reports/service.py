"""Owned, immutable partial daily reports. Never invent missing evaluation outputs."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, func, insert, or_, select, text, update

from app.aggregates.service import select_account
from app.api.v1.portfolio import _account
from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import reconciliation_items, reconciliation_runs
from app.db.tables.market import securities, trading_calendar
from app.db.tables.realtime import daily_report_items, daily_reports, pipeline_runs, suggestions
from app.db.tables.research import watchlist_items
from app.db.tables.signals import non_executable_reasons, plan_drafts
from app.db.tables.strategy import strategy_instances
from app.reports.comparison import apply as apply_comparison
from app.reports.models import DailyReport
from app.suggestions.service import summary

COMPLETE = ("ready", "partial")


def canonical(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


def covered(conn: Connection, date: dt.date) -> bool:
    opened = conn.execute(
        select(trading_calendar.c.is_open).where(trading_calendar.c.date == date)
    ).scalar_one_or_none()
    if opened is None:
        raise AppError(ErrorCode.MAINTENANCE, details={"issue": "CALENDAR_NOT_COVERED"})
    return bool(opened)


def latest(conn: Connection, user_id: uuid.UUID, date: dt.date) -> Any:  # noqa: ANN401
    return conn.execute(
        select(daily_reports)
        .where(
            daily_reports.c.user_id == user_id,
            daily_reports.c.trade_date == date,
            daily_reports.c.status.in_(COMPLETE),
        )
        .order_by(daily_reports.c.revision.desc())
        .limit(1)
    ).first()


def _gap(key: str, message: str) -> dict[str, str]:
    return {"key": key, "reason": "no_source", "message": message}


def build(conn: Connection, user_id: uuid.UUID, date: dt.date, now: dt.datetime) -> uuid.UUID:
    # Same owner lock as candidates/suggestions: no torn report vs concurrent archive.
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"), {"owner": str(user_id)}
    )
    identifier = select_account(conn, user_id, None)
    account = _account(conn, identifier, date) if identifier else None
    positions = account.positions if account else {}
    watches = set(
        conn.execute(
            select(watchlist_items.c.security_code).where(
                watchlist_items.c.user_id == user_id, watchlist_items.c.removed_at.is_(None)
            )
        ).scalars()
    )
    codes = sorted(set(positions) | watches)
    master = {
        row.code: row
        for row in conn.execute(select(securities).where(securities.c.code.in_(codes)))
    }
    gaps = [_gap("market", "市场环境、宽度与现金估值基准尚未接线，不作默认推断。")]
    analysis = conn.execute(
        select(pipeline_runs.c.stats)
        .where(
            pipeline_runs.c.kind == "daily_batch",
            pipeline_runs.c.run_date == date,
            pipeline_runs.c.step == "tb76.daily_analysis",
            pipeline_runs.c.status.in_(["partial", "ok"]),
        )
        .order_by(pipeline_runs.c.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    own_analysis = (analysis or {}).get("users", {}).get(str(user_id))
    if own_analysis is None:
        gaps.append(_gap("pipeline.analysis", "盘后策略装配尚无本人完成记录。"))
    else:
        gaps.extend(
            _gap("pipeline." + issue, "策略装配缺口；未填造置信度、止损或正式卡批准。")
            for issue in own_analysis.get("issues", [])
        )
    report_account = None
    if account:
        priced = all(
            p.price is not None
            and p.price_at is not None
            and p.price_at.astimezone(dt.timezone(dt.timedelta(hours=8))).date() == date
            for p in positions.values()
        )
        value = (
            sum((p.qty * p.price for p in positions.values() if p.price is not None), Decimal(0))
            if priced
            else None
        )
        total = value + account.cash if value is not None and account.cash is not None else None
        report_account = {
            "total_assets": str(total) if total is not None else None,
            "cash": str(account.cash) if account.cash is not None else None,
            "position_pct": str(value / total * 100)
            if value is not None and total is not None and total > 0
            else None,
            "pnl_day": None,
            "position_vs_regime": None,
        }
        gaps.append(_gap("account.pnl_day", "缺上日净值；未计算日盈亏或以成本代替市值。"))
        if total is None:
            gaps.append(
                _gap("account.total_assets", "缺行情估值或重建现金，净资产与仓位不可计算。")
            )
    reconciliation = {
        "status": "not_imported",
        "as_of": None,
        "diff_count": 0,
        "important_count": 0,
    }
    run = (
        conn.execute(
            select(reconciliation_runs)
            .where(reconciliation_runs.c.account_id == identifier)
            .order_by(reconciliation_runs.c.created_at.desc(), reconciliation_runs.c.id.desc())
            .limit(1)
        ).first()
        if identifier
        else None
    )
    if run:
        count = conn.execute(
            select(func.count())
            .select_from(reconciliation_items)
            .where(reconciliation_items.c.run_id == run.id)
        ).scalar_one()
        if count:
            # Important-count policy is not defined by the existing reader; never invent 0.
            raise AppError(
                ErrorCode.MAINTENANCE,
                details={"issue": "reconciliation_item_importance_adapter_pending"},
            )
        reconciliation.update(status=run.status, as_of=run.created_at)
    rows = (
        conn.execute(
            select(suggestions)
            .where(
                suggestions.c.user_id == user_id,
                suggestions.c.security_code.in_(codes),
                suggestions.c.status == "active",
                suggestions.c.created_at <= now,
                or_(suggestions.c.valid_until > now, suggestions.c.valid_until.is_(None)),
            )
            .order_by(suggestions.c.created_at.desc(), suggestions.c.id.desc())
        ).all()
        if identifier
        else []
    )
    own: dict[str, Any] = {}
    for row in rows:
        strategies = row.strategies or []
        # Existing archives freeze expiry per conclusion, not always on the row.
        # Missing expiry is not permission to invent a freshness TTL.
        if not strategies or any(
            s.get("valid_until") is None or dt.datetime.fromisoformat(s["valid_until"]) <= now
            for s in strategies
        ):
            continue
        ids = {uuid.UUID(s["instance_id"]) for s in strategies if s.get("instance_id")}
        attributed = (
            set(
                conn.execute(
                    select(strategy_instances.c.id).where(
                        strategy_instances.c.id.in_(ids),
                        strategy_instances.c.user_id == user_id,
                        strategy_instances.c.account_id == identifier,
                    )
                ).scalars()
            )
            if ids
            else set()
        )
        if ids and ids == attributed:
            own.setdefault(row.security_code, row)
    stocks: list[dict[str, Any]] = []
    for code in codes:
        suggestion = own.get(code)
        if suggestion is None:
            gaps.append(
                _gap("stocks." + code, "没有可用的本人建议；正式卡运行门禁或结论装配尚待完成。")
            )
        stocks.append(
            {
                "security_code": code,
                "name": master[code].name if code in master else code,
                "close": None,
                "change_pct": None,
                "data_status": "partial",
                "max_risk_level": max(
                    (f["level"] for f in (suggestion.risk_flags or [])),
                    key={"info": 0, "warning": 1, "critical": 2}.__getitem__,
                    default=None,
                )
                if suggestion
                else None,
                "suggestion_id": str(suggestion.id) if suggestion else None,
                "suggestion": summary(suggestion) if suggestion else None,
                "change_from_previous": None,
                "change_fields": [],
                "highlights": [],
                "invalidation": [],
                "next_watch": [],
            }
        )
    pending = {
        "plan_drafts": int(
            conn.execute(
                select(func.count())
                .select_from(plan_drafts)
                .where(plan_drafts.c.user_id == user_id, plan_drafts.c.status == "pending")
            ).scalar_one()
        ),
        "active_reasons": int(
            conn.execute(
                select(func.count())
                .select_from(non_executable_reasons)
                .where(
                    non_executable_reasons.c.user_id == user_id,
                    non_executable_reasons.c.status == "active",
                )
            ).scalar_one()
        ),
    }
    body: dict[str, Any] = {
        "date": str(date),
        "generated_at": now.isoformat(),
        "account_id": str(identifier) if identifier else None,
        "market": {"regime": None, "regime_position_range": None, "breadth": None, "summary": []},
        "account": report_account,
        "reconciliation": reconciliation,
        "stocks": stocks,
        "pending": pending,
        "explanation": {
            "source": "template",
            "text": "缺口日报；不代表正式卡或真实闭环验收通过。",
            "llm_call_id": None,
        },
        "evidence": [],
        "data_status": "partial",
        "data_as_of": None,
        "gaps": gaps,
    }
    if not apply_comparison(conn, user_id, date, stocks):
        gaps.append(
            _gap("stocks.change_from_previous", "最近开市日没有完成版日报，不推断全部为新增。")
        )
    # Include owned holdings even when the public report cannot estimate their value.
    fingerprint = {
        "analysis": own_analysis,
        "body": {k: v for k, v in body.items() if k != "generated_at"},
        "positions": {
            code: {
                "qty": str(p.qty),
                "sellable": str(p.sellable),
                "cost_total": str(p.cost_total),
                "cost_known": p.cost_known,
            }
            for code, p in sorted(positions.items())
        },
    }
    digest = hashlib.sha256(canonical(fingerprint).encode()).hexdigest()
    previous = latest(conn, user_id, date)
    if previous and (previous.summary or {}).get("input_hash") == digest:
        return uuid.UUID(str(previous.id))
    body = DailyReport.model_validate_json(canonical(body)).model_dump(mode="json")
    revision = (
        int(
            conn.execute(
                select(func.coalesce(func.max(daily_reports.c.revision), 0)).where(
                    daily_reports.c.user_id == user_id, daily_reports.c.trade_date == date
                )
            ).scalar_one()
        )
        + 1
    )
    report_id = uuid.uuid4()
    conn.execute(
        insert(daily_reports).values(
            id=report_id,
            user_id=user_id,
            account_id=identifier,
            trade_date=date,
            revision=revision,
            status="building",
            summary={"input_hash": digest},
            body=json.loads(canonical(body)),
            explanation_text=body["explanation"]["text"],
            explanation_source="template",
            gaps=gaps,
            generated_at=now,
        )
    )
    for stock in stocks:
        conn.execute(
            insert(daily_report_items).values(
                id=uuid.uuid4(),
                report_id=report_id,
                security_code=stock["security_code"],
                relation="holding" if stock["security_code"] in positions else "watchlist",
                facts=stock,
                strategy_results=[],
                suggestion_id=stock["suggestion_id"],
            )
        )
    conn.execute(
        update(daily_reports).where(daily_reports.c.id == report_id).values(status="partial")
    )
    return report_id
