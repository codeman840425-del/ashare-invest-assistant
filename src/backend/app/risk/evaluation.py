"""Owned, cached RiskHook inputs. No fetches, writes, inferred cash or memberships."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, select

from app.aggregates.service import select_account
from app.api.v1.portfolio import _account, _has_ledger, _ledger_as_of, latest_daily_close
from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.config_files import RiskControlsConfig
from app.db.tables.accounts import accounts, broker_position_snapshots
from app.db.tables.market import feature_bars_daily, securities
from app.db.tables.realtime import suggestions
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import feature_catalog, strategy_instances
from app.feedback.plans import Facts as RC6Facts
from app.importing.pipeline import live_snapshots
from app.market_rules.lots import LotSpec, lot_spec
from app.risk.rc1 import Facts as RC1Facts
from app.risk.settings import canonical
from app.schemas.enums import (
    Action,
    DataProvider,
    EpistemicType,
    GapReason,
    Horizon,
    MarketRegime,
    RiskControl,
    RiskLevel,
    TLeg,
)
from app.signals.models import Evidence, Gap, RiskFlag, Stops
from app.suggestions.risk import (
    CONTROL_FIELDS,
    RiskContext,
    RiskResult,
    effective_config,
    evaluate_risk,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
EMPTY_STOPS = Stops(stop_loss=None, take_profit=None, time_stop_days=None)
GAP_CONTROLS = {
    "price": {"stop_take", "position_cap", "total_exposure", "sector_concentration"},
    "limit_down_price": {"stop_take"},
    "limit_up_price": {"stop_take"},
    "total_assets": {"position_cap", "total_exposure", "sector_concentration"},
    "security_value": {"position_cap"},
    "total_value": {"total_exposure"},
    "proposed_quantity": {"position_cap", "total_exposure", "sector_concentration"},
    "market_lot_rules": {"position_cap", "total_exposure", "sector_concentration"},
    "market_regime": {"total_exposure"},
    "sector_memberships": {"sector_concentration"},
}


def gap(key: str) -> Gap:
    return Gap(
        key=key,
        reason=GapReason.NO_SOURCE,
        message=(
            "大盘环境未知；仅接受F25已核实缓存，不以F50代替。"
            if key == "market_regime"
            else "缺少可判定风控事实：" + key + "；未以零或无限额度替代。"
        ),
    )


def observation(key: str, value: Any, at: dt.datetime, endpoint: str) -> Evidence:  # noqa: ANN401
    return Evidence(
        id="risk:" + key,
        key=key,
        value=str(value),
        unit={
            "total_assets": "CNY",
            "total_value": "CNY",
            "security_value": "CNY",
            "price": "CNY/share",
            "limit_up_price": "CNY/share",
            "limit_down_price": "CNY/share",
        }.get(key),
        provider=DataProvider.SYSTEM,
        endpoint=endpoint,
        data_as_of=at,
        fetched_at=at,
        epistemic_type=EpistemicType.ESTIMATE,
    )


@dataclass
class Inputs:
    account_id: uuid.UUID | None
    context: RiskContext
    lot: LotSpec | None
    position_known: bool
    gaps: list[str]
    rc1: RC1Facts | None = None
    owner_id: uuid.UUID | None = None
    security_code: str | None = None
    rc6: RC6Facts | None = None
    rc6_source_evidence: tuple[Evidence, ...] = ()
    rc6_source_gaps: tuple[str, ...] = ()


def inputs(
    conn: Connection,
    owner: uuid.UUID,
    code: str,
    account_id: uuid.UUID | None,
    settings: Settings,
    at: dt.datetime,
    *,
    t_leg: TLeg | None = None,
    feature_set_version: str | None = None,
) -> Inputs:
    # Computed exposure is deterministic at sufficient precision, never float.
    with localcontext() as precision:
        precision.prec = 256
        return _inputs(
            conn,
            owner,
            code,
            account_id,
            settings,
            at,
            t_leg=t_leg,
            feature_set_version=feature_set_version,
        )


def _inputs(
    conn: Connection,
    owner: uuid.UUID,
    code: str,
    account_id: uuid.UUID | None,
    settings: Settings,
    at: dt.datetime,
    *,
    t_leg: TLeg | None,
    feature_set_version: str | None,
) -> Inputs:
    aid = select_account(conn, owner, account_id)
    security = conn.execute(select(securities).where(securities.c.code == code)).first()
    if security is None:
        raise AppError(ErrorCode.NOT_FOUND)
    today = at.astimezone(SHANGHAI).date()
    obs: dict[str, Evidence] = {}
    missing: list[str] = []
    known = False
    # Already persisted whole-account evidence is required even for zero holdings.
    snap = (
        None
        if aid is None
        else conn.execute(
            live_snapshots(aid).order_by(broker_position_snapshots.c.version_no.desc()).limit(1)
        ).first()
    )
    ledger_at = None if aid is None else _ledger_as_of(conn, [aid])
    future = (ledger_at is not None and ledger_at > at) or (
        snap is not None and (snap.as_of or snap.created_at) > at
    )
    currency = (
        conn.execute(select(accounts.c.base_currency).where(accounts.c.id == aid)).scalar_one()
        if aid is not None
        else None
    )
    if aid is not None and not future and currency == "CNY":
        known = snap is not None or _has_ledger(conn, aid)
        account = _account(conn, aid, today)
        # Reject unclosed future daily prices rather than using them as current.
        closed_day = today if at.astimezone(SHANGHAI).hour >= 15 else today - dt.timedelta(days=1)
        prices = latest_daily_close(conn, set(account.positions) | {code}, closed_day)
        values: dict[str, Decimal] = {}
        marks: list[dt.datetime] = []
        for symbol, position in account.positions.items():
            price, stamp = prices.get(symbol, (position.price, position.price_at))
            if price is None or not price.is_finite() or stamp is None or stamp > at or price <= 0:
                missing.append("position_price:" + symbol)
            else:
                values[symbol] = price * position.qty
                marks.append(stamp)
        stamp = ledger_at or (snap.as_of or snap.created_at if snap is not None else None)
        if stamp is not None and known:
            endpoint = "app.accounts/" + str(aid) + "/cached-valuation"
            target = account.positions.get(code)
            if target is None or code in values:
                obs["security_value"] = observation(
                    "security_value", values.get(code, Decimal(0)), stamp, endpoint
                )
            if len(values) == len(account.positions):
                total = sum(values.values(), Decimal(0))
                obs["total_value"] = observation(
                    "total_value", total, max(marks, default=stamp), endpoint
                )
                if (
                    account.cash is not None
                    and account.cash.is_finite()
                    and total + account.cash >= 0
                ):
                    obs["total_assets"] = observation(
                        "total_assets", total + account.cash, max(marks, default=stamp), endpoint
                    )
            if account.cash is None:
                missing.append("cash")
        price, stamp = prices.get(code, (None, None))
        if price is None and code in account.positions:
            position = account.positions[code]
            price, stamp = position.price, position.price_at
        if (
            price is not None
            and stamp is not None
            and stamp <= at
            and price.is_finite()
            and price > 0
        ):
            obs["price"] = observation(
                "price", price, stamp, "market.daily_bars|owned-broker-snapshot"
            )
    else:
        missing.append(
            "account_as_of" if future else "account_currency" if aid is not None else "account"
        )

    # No registry upgrade, no alternate F50. verified_doc is not live risk evidence.
    cached = conn.execute(
        select(feature_bars_daily)
        .where(
            feature_bars_daily.c.code == code,
            feature_bars_daily.c.trade_date <= today,
            feature_bars_daily.c.computed_at <= at,
            *(
                [feature_bars_daily.c.feature_set_version == feature_set_version]
                if feature_set_version is not None
                else []
            ),
        )
        .order_by(
            feature_bars_daily.c.trade_date.desc(),
            feature_bars_daily.c.computed_at.desc(),
            feature_bars_daily.c.feature_set_version.desc(),
        )
        .limit(1)
    ).first()
    registry = {
        r.feature_key: r
        for r in conn.execute(
            select(feature_catalog).where(
                feature_catalog.c.feature_key.in_(
                    ["f.market_regime", "f.limit_up_price", "f.limit_down_price"]
                )
            )
        )
    }
    regime = None
    for source, key in [
        ("f.market_regime", "market_regime"),
        ("f.limit_up_price", "limit_up_price"),
        ("f.limit_down_price", "limit_down_price"),
    ]:
        entry = registry.get(source)
        if cached is None or entry is None or entry.status != "verified_live":
            continue
        value = cached._mapping["values"].get(source)
        if value is None:
            continue
        if key == "market_regime":
            if value not in {v.value for v in MarketRegime}:
                continue
            regime = MarketRegime(value)
        else:
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                continue
            if not number.is_finite() or number <= 0:
                continue
        obs[key] = observation(
            key,
            value,
            cached.computed_at,
            "market.feature_bars_daily:" + source + ":" + cached.feature_set_version,
        )
    segment = settings.business.market_rules.segment_for(today)
    lot = (
        lot_spec(segment, board=security.board, security_type=security.type)
        if (segment is not None and security.board in {"main_board", "star", "chinext", "bse"})
        else None
    )
    from app.feedback.plan_source import load as load_plan_source

    plan_source = load_plan_source(conn, owner, aid, code, at=at)
    return Inputs(
        aid,
        RiskContext(
            observations=obs,
            regime=regime,
            t_leg=t_leg,
            sector_memberships=None,
            trade_action=None,
            plan_action=None,
            invalidated=None,
            plan_stop_loss=None,
        ),
        lot,
        known,
        missing,
        owner_id=owner,
        security_code=code,
        rc6=plan_source.facts,
        rc6_source_evidence=plan_source.evidence,
        rc6_source_gaps=plan_source.gaps,
    )


def assessed(
    config: RiskControlsConfig,
    source: Inputs,
    *,
    action: Action,
    horizon: Horizon,
    stops: Stops,
    at: dt.datetime,
) -> tuple[RiskResult, list[dict[str, Any]]]:
    result = evaluate_risk(
        config, source.context, action=action, horizon=horizon, stops=stops, lot=source.lot
    )
    evidence = {e.id: e for e in result.evidence}
    policy = observation(
        "settings",
        json.dumps(canonical(config.model_dump(mode="json")), sort_keys=True),
        at,
        "app.risk_control_settings:effective",
    )
    evidence[policy.id] = policy
    flags = list(result.flags)
    extra: set[str] = set()
    if not config.rc1_stop_take.enabled:
        flags.append(
            RiskFlag(
                control=RiskControl.STOP_TAKE,
                level=RiskLevel.WARNING,
                message="RC1已关闭；止损/止盈/时间止损保护未启用，仅警示，不改变动作。",
                gated_actions=[],
                quantity_cap=None,
                evidence_ids=[policy.id],
            )
        )
    else:
        if all(
            v is None
            for v in [result.stops.stop_loss, result.stops.take_profit, result.stops.time_stop_days]
        ):
            extra.add("strategy_stops")
        from app.risk.rc1 import assess as assess_rc1

        rc_flags, rc_evidence, rc_gaps = assess_rc1(result.stops, source.rc1, at)
        flags.extend(
            f.model_copy(update={"evidence_ids": [*f.evidence_ids, policy.id]}) for f in rc_flags
        )
        evidence.update({e.id: e for e in rc_evidence})
        extra.update(rc_gaps)
    if config.rc6_plan_violation.enabled:
        extra.update(source.rc6_source_gaps)
    if config.rc6_plan_violation.enabled and source.rc6 is not None:
        from app.feedback.plans import assess as assess_rc6

        # Never trust an assessment's self-declared owner/account in another
        # caller's Inputs. The owned DB reader must supply the binding.
        flags = [f for f in flags if f.control != RiskControl.PLAN_VIOLATION]
        result = result.model_copy(
            update={
                "gaps": [
                    g
                    for g in result.gaps
                    if g
                    not in {
                        "plan_trade_context",
                        "traded_quantity",
                        "planned_quantity",
                        "plan_invalidation",
                        "holding_quantity",
                    }
                ]
            }
        )
        if source.owner_id is None or (
            source.owner_id,
            source.account_id,
            source.security_code,
        ) != (
            source.rc6.owner,
            source.rc6.account,
            source.rc6.code,
        ):
            extra.add("plan_owner_or_account_unresolved")
        else:
            evidence.update({e.id: e for e in source.rc6_source_evidence})
            plan_result = assess_rc6(
                source.rc6, at=at, checks=tuple(config.rc6_plan_violation.checks)
            )
            flags.extend(
                f.model_copy(update={"evidence_ids": [*f.evidence_ids, policy.id]})
                for f in plan_result.flags
            )
            evidence.update({e.id: e for e in plan_result.evidence})
            extra.update(plan_result.gaps)
    result = result.model_copy(
        update={
            "flags": flags,
            "evidence": list(evidence.values()),
            "gaps": sorted(set(result.gaps) | extra),
        }
    )
    controls = []
    for control, field in CONTROL_FIELDS.items():
        enabled = getattr(config, field).enabled
        selected = [f for f in flags if f.control == control]
        keys = [
            k
            for k in result.gaps
            if control in GAP_CONTROLS.get(k, set())
            or (control == "stop_take" and k in extra)
            or (control == "sector_concentration" and k.startswith(("sw_l1.", "concept.")))
            or (
                control == "loss_streak_drawdown"
                and k
                in {"closed_loss_streak", "drawdown_from_peak_pct", "strategy_sim_fail_streak"}
            )
            or (control == "plan_violation" and k.startswith("plan"))
        ]
        if enabled and (
            control == "loss_streak_drawdown"
            or (control == "plan_violation" and source.rc6 is None)
        ):
            keys.append("business_facts_not_connected")
        state = (
            "disabled" if not enabled else "triggered" if selected else "unknown" if keys else "ok"
        )
        controls.append(
            {
                "control": control,
                "enabled": enabled,
                "state": state,
                "flags": [f.model_dump(mode="json") for f in selected],
                "gaps": [gap(k).model_dump(mode="json") for k in sorted(set(keys))]
                if enabled
                else [],
            }
        )
    return result, controls


def current(
    conn: Connection,
    owner: uuid.UUID,
    code: str,
    account_id: uuid.UUID | None,
    settings: Settings,
    at: dt.datetime,
) -> dict[str, Any]:
    config = effective_config(conn, owner, settings.business.risk_controls)
    suggestion = conn.execute(
        select(suggestions)
        .join(data_snapshots, suggestions.c.snapshot_id == data_snapshots.c.id)
        .where(
            suggestions.c.user_id == owner,
            suggestions.c.security_code == code,
            suggestions.c.status == "active",
            suggestions.c.created_at <= at,
            data_snapshots.c.user_id == owner,
            data_snapshots.c.created_at <= at,
        )
        .order_by(suggestions.c.created_at.desc(), suggestions.c.id.desc())
        .limit(1)
    ).first()
    source = inputs(
        conn,
        owner,
        code,
        account_id,
        settings,
        at,
        feature_set_version=suggestion.feature_set_version if suggestion is not None else None,
    )
    from app.risk.rc1 import load as load_rc1

    source.rc1 = load_rc1(
        conn,
        owner,
        source.account_id,
        code,
        settings,
        at,
        stops_at=suggestion.created_at if suggestion is not None else at,
        position_known=source.position_known,
    )
    name = conn.execute(select(securities.c.name).where(securities.c.code == code)).scalar_one()
    strategies: list[dict[str, Any]] = []
    if suggestion is not None:
        owned = (
            {
                str(r.id)
                for r in conn.execute(
                    select(strategy_instances.c.id).where(
                        strategy_instances.c.user_id == owner,
                        strategy_instances.c.account_id == source.account_id,
                        strategy_instances.c.status == "active",
                    )
                )
            }
            if source.account_id is not None
            else set()
        )
        strategies = [r for r in suggestion.strategies if str(r.get("instance_id")) in owned]
    snapshot_id = suggestion.snapshot_id if strategies and suggestion is not None else None
    results = [
        assessed(
            config,
            source,
            action=Action(r["action"]),
            horizon=Horizon(r["horizon"]),
            stops=Stops.model_validate(r["stops"]),
            at=at,
        )
        for r in strategies
    ]
    if not results:
        results = [
            assessed(
                config, source, action=Action.HOLD, horizon=Horizon.SHORT, stops=EMPTY_STOPS, at=at
            )
        ]
    evidence = {e.id: e for result, _ in results for e in result.evidence}
    controls = []
    for i, _control in enumerate(CONTROL_FIELDS):
        rows = [cs[i] for _, cs in results]
        row = rows[0].copy()
        row["flags"] = list(
            {json.dumps(f, sort_keys=True): f for c in rows for f in c["flags"]}.values()
        )
        row["gaps"] = list({g["key"]: g for c in rows for g in c["gaps"]}.values())
        if row["enabled"]:
            row["state"] = (
                "triggered"
                if any(c["state"] == "triggered" for c in rows)
                else "unknown"
                if any(c["state"] == "unknown" for c in rows)
                else "ok"
            )
        controls.append(row)
    all_gaps = {g["key"]: g for c in controls for g in c["gaps"]}
    all_gaps.update({k: gap(k).model_dump(mode="json") for k in source.gaps})
    if not strategies:
        all_gaps["strategy_context"] = gap("strategy_context").model_dump(mode="json")
    observations = list(
        {
            e.id: e
            for e in [*source.context.observations.values(), *evidence.values()]
            if e.key != "settings"
        }.values()
    )
    data_as_of = earliest_as_of(observations)
    if observations and data_as_of is None:
        all_gaps["risk_evidence_time_unknown"] = gap("risk_evidence_time_unknown").model_dump(
            mode="json"
        )
    return {
        "account_id": str(source.account_id) if source.account_id else None,
        "security_code": code,
        "name": name or code,
        "snapshot_id": str(snapshot_id) if snapshot_id else None,
        "evaluated_at": at.isoformat(),
        "controls": controls,
        "evidence": [e.model_dump(mode="json") for e in evidence.values()],
        "data_status": "unavailable" if not observations else "partial" if all_gaps else "fresh",
        "data_as_of": data_as_of,
        "gaps": list(all_gaps.values()),
    }


def earliest_as_of(observations: list[Evidence]) -> dt.datetime | None:
    """Oldest data operand, never the evaluation/settings time or newest input."""
    data = [e for e in observations if e.key != "settings"]
    if not data or any(e.data_as_of is None for e in data):
        return None
    return min(e.data_as_of for e in data if e.data_as_of is not None)
