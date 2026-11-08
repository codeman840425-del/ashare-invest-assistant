"""Deterministic draft assembly from real owned state, not an executable order.

Missing capital/budget/fee evidence is a named input gap, never an invented zero.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from decimal import Decimal
from typing import Any, NoReturn

from sqlalchemy import Connection, insert, select

from app.api.v1.portfolio import _account
from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.config_files import MarketRuleSegment
from app.db.tables.accounts import accounts, trades
from app.db.tables.market import securities
from app.db.tables.reviews import data_snapshots
from app.db.tables.signals import plan_drafts
from app.db.tables.strategy import market_rule_versions, strategy_instances, strategy_versions
from app.ingest.owned_quotes import SCHEMA
from app.market_rules.lots import lot_spec
from app.plans import service
from app.plans.models import number
from app.risk.evaluation import inputs
from app.signals.models import Stops
from app.signals.service import transition
from app.workers.assembly import canonical


def missing(*keys: str) -> NoReturn:
    raise AppError(ErrorCode.UPSTREAM_UNAVAILABLE, details={"gaps": list(keys)})


def generate(
    conn: Connection, owner: uuid.UUID, signals: list[Any], settings: Settings, now: dt.datetime
) -> uuid.UUID:
    code, action = signals[0].security_code, signals[0].proposed_action
    if action not in {"buy", "add", "sell", "reduce"}:
        service.invalid("signal_ids", "action_not_draftable")
    instances = conn.execute(
        select(strategy_instances).where(
            strategy_instances.c.id.in_([r.instance_id for r in signals]),
            strategy_instances.c.user_id == owner,
            strategy_instances.c.status == "active",
        )
    ).all()
    aids = {r.account_id for r in instances}
    if len(aids) != 1 or None in aids:
        missing("draft_account_scope")
    by_instance = {r.id: r for r in instances}
    for signal in signals:
        instance = by_instance.get(signal.instance_id)
        if (
            instance is None
            or (instance.derived_strategy_version_id or instance.strategy_version_id)
            != signal.strategy_version_id
        ):
            missing("strategy_version_input_changed")
    aid = next(iter(aids))
    if not conn.execute(
        select(accounts.c.id)
        .where(accounts.c.id == aid, accounts.c.user_id == owner, accounts.c.archived_at.is_(None))
        .with_for_update()
    ).first():
        missing("account")
    day = now.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    account = _account(conn, aid, day)
    pos = account.positions.get(code)
    context = {
        "holding_qty": str(pos.qty if pos else 0),
        "sellable_qty": str(pos.sellable if pos else 0),
        "cash": str(account.cash) if account.cash is not None else None,
        "sector_pct": None,
    }
    if account.cash is None:
        missing("cash")
    from app.db.tables.licences import user_data_licences

    quote = conn.execute(
        select(data_snapshots)
        .join(user_data_licences, data_snapshots.c.licence_id == user_data_licences.c.id)
        .where(
            data_snapshots.c.user_id == owner,
            data_snapshots.c.created_at <= now,
            data_snapshots.c.purpose == "signal",
            data_snapshots.c["items"]["schema_version"].astext == SCHEMA,
            data_snapshots.c["items"]["security_code"].astext == code,
            user_data_licences.c.user_id == owner,
            user_data_licences.c.status == "active",
            user_data_licences.c.deleted_at.is_(None),
        )
        .order_by(data_snapshots.c.created_at.desc(), data_snapshots.c.id.desc())
        .limit(1)
    ).first()
    if quote is None:
        missing("owned_raw_quote")
    raw = quote.items
    if hashlib.sha256(canonical(raw).encode()).hexdigest() != quote.hash:
        missing("quote_hash")
    try:
        price = Decimal(number(raw["price"], positive=True))
        observed = dt.datetime.fromisoformat(raw["data_as_of"])
        available = dt.datetime.fromisoformat(raw["available_at"])
        expiry = dt.datetime.fromisoformat(raw["expires_at"])
    except (KeyError, ValueError, TypeError, ArithmeticError):
        missing("owned_quote_shape")
    if (
        any(t.tzinfo is None for t in (observed, available, expiry))
        or not observed <= available <= now <= expiry
        or raw.get("is_suspended") is not False
        or raw.get("adj_type") != "none"
        or raw.get("data_status") != "fresh"
    ):
        missing("fresh_unsuspended_quote")
    rules = conn.execute(
        select(market_rule_versions)
        .where(
            market_rule_versions.c.effective_from <= day,
            market_rule_versions.c.created_at <= now,
        )
        .order_by(market_rule_versions.c.effective_from.desc())
        .limit(1)
    ).first()
    if rules is None:
        missing("market_rule_version")
    segment = MarketRuleSegment.model_validate(rules.rules)
    security = conn.execute(select(securities).where(securities.c.code == code)).one()
    lot = lot_spec(segment, board=security.board, security_type=security.type)
    source = inputs(
        conn, owner, code, aid, settings, now, feature_set_version=signals[0].feature_set_version
    )
    observations = source.context.observations
    if any(k not in observations for k in ("limit_down_price", "limit_up_price", "total_assets")):
        missing("limit_prices_or_total_assets")
    assets = Decimal(str(observations["total_assets"].value))
    if assets <= 0:
        missing("positive_total_assets")
    if len({canonical(r.stops) for r in signals}) != 1:
        missing("distinct_strategy_stops_no_cross_strategy_synthesis")
    stops = Stops.model_validate(signals[0].stops)
    if stops.stop_loss is None or stops.stop_loss <= 0 or price <= stops.stop_loss:
        missing("positive_per_share_stop_distance")
    rate = segment.fees.commission_rate_default_pct
    fee_source = "market_rule_versions:" + str(rules.id)
    # An above-minimum itemized commission supports an implied user/account rate;
    # a minimum-charge-only trade does NOT reveal the marginal rate.
    previous_fee = conn.execute(
        select(trades)
        .where(
            trades.c.user_id == owner,
            trades.c.account_id == aid,
            trades.c.voided_at.is_(None),
            trades.c.created_at <= now,
            trades.c.traded_at <= now,
            trades.c.commission > segment.fees.commission_min_yuan,
            trades.c.amount > 0,
        )
        .order_by(trades.c.traded_at.desc(), trades.c.id.desc())
        .limit(1)
    ).first()
    if previous_fee is not None:
        rate = Decimal(previous_fee.commission) / Decimal(previous_fee.amount) * 100
        fee_source = "app.trades:" + str(previous_fee.id)
    if rate is None:
        missing("commission_rate")
    # No contract defines a per-trade loss setting or attribution of used budget
    # across multiple instances. Refuse that input, do not spend all available cash.
    if action in {"buy", "add"}:
        missing("per_trade_max_loss_input", "strategy_budget_remaining_attribution")
    upper = min(Decimal(str(context["sellable_qty"])), Decimal(lot.max_qty))
    upper = Decimal(lot.min_buy) + ((upper - lot.min_buy) // lot.step) * lot.step
    if upper < lot.min_buy:
        missing("sellable_minimum_or_odd_lot_draft_range")
    lower = max(Decimal(lot.min_buy), (upper / 2 // lot.step) * lot.step)
    slips = set()
    for instance in instances:
        version = conn.execute(
            select(strategy_versions.c.config).where(
                strategy_versions.c.id
                == (instance.derived_strategy_version_id or instance.strategy_version_id)
            )
        ).scalar_one()
        spec = version.get("spec", version)
        params = {k: v["default"] for k, v in spec.get("params_schema", {}).items()}
        params.update(instance.param_overrides or {})
        slips.add(
            Decimal(str(params["slippage_bp"])) / 10000
            if "slippage_bp" in params
            else segment.fees.slippage_default_pct / 100
        )
    if len(slips) != 1:
        missing("distinct_template_slippage_no_cross_strategy_synthesis")
    slip = slips.pop()
    if not slip.is_finite() or slip < 0:
        missing("invalid_template_slippage")
    low = max(price * (1 - slip), Decimal(str(observations["limit_down_price"].value)))
    high = min(price * (1 + slip), Decimal(str(observations["limit_up_price"].value)))
    if low > high:
        missing("price_range_outside_limits")
    amount = upper * price
    fee = max(amount * rate / 100, segment.fees.commission_min_yuan)
    fee += amount * (segment.fees.transfer_fee_pct + segment.fees.stamp_duty_sell_pct) / 100
    loss = upper * (price - stops.stop_loss)
    untils = [r.valid_until for r in signals if r.valid_until is not None]
    if len(untils) != len(signals) or min(untils) <= now:
        missing("signal_valid_until")
    identifier, snapshot = uuid.uuid4(), uuid.uuid4()
    payload = {
        "schema_version": "p2n07-draft-input-v1",
        "plan_draft_context": {"account_id": str(aid), "quantity_cap": str(upper)},
        "fee_inputs": {
            "source": fee_source,
            "commission_rate_pct": str(rate),
            "commission_min_yuan": str(segment.fees.commission_min_yuan),
        },
        "quote_snapshot_id": str(quote.id),
        "quote_hash": quote.hash,
        "signal_snapshot_ids": [str(r.snapshot_id) for r in signals],
        "valuation_evidence": [e.model_dump(mode="json") for e in observations.values()],
    }
    conn.execute(
        insert(data_snapshots).values(
            id=snapshot,
            user_id=owner,
            licence_id=quote.licence_id,
            purpose="plan",
            hash=hashlib.sha256(canonical(payload).encode()).hexdigest(),
            items=payload,
            created_at=now,
        )
    )
    conn.execute(
        insert(plan_drafts).values(
            id=identifier,
            user_id=owner,
            signal_ids=[r.id for r in signals],
            instance_id=instances[0].id if len(instances) == 1 else None,
            security_code=code,
            action=action,
            qty_range={"min": str(lower), "max": str(upper), "lot": lot.step},
            price_range={"low": str(low), "high": str(high)},
            stops=stops.model_dump(mode="json"),
            max_loss_amount=loss,
            max_loss_pct=loss / assets * 100,
            fee_estimate={
                "amount": str(fee.quantize(Decimal("0.01"))),
                "epistemic_type": "estimate",
            },
            user_context_snapshot=context,
            risk_flags=[f for r in signals for f in (r.risk_flags or [])],
            judgment_checklist=[
                {
                    "id": "risk_announcements",
                    "question": "是否了解该股近期公告？",
                    "required": True,
                },
                {
                    "id": "stop_execution",
                    "question": "如果触发止损，你会执行吗？",
                    "required": True,
                },
            ],
            market_rule_version_id=rules.id,
            snapshot_id=snapshot,
            expires_at=min(untils),
            created_at=now,
            status_changed_at=now,
        )
    )
    for signal in signals:
        if signal.state != "drafted":
            transition(conn, signal, "drafted", "user", now, {"plan_draft_id": str(identifier)})
    service.audit(
        conn, owner, "plan_draft.created", identifier, {"signal_ids": [str(r.id) for r in signals]}
    )
    return identifier
