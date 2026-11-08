"""RC1–RC6 deterministic hooks. Inputs are explicit cached observations, never fetched."""

from __future__ import annotations

import json
import uuid
from decimal import ROUND_FLOOR, Decimal, InvalidOperation, localcontext

from pydantic import Field, model_validator
from sqlalchemy import Connection, or_, select

from app.config_files import RiskControlsConfig
from app.db.tables.strategy import risk_control_settings
from app.market_rules.lots import LotSpec
from app.schemas.enums import Action, Horizon, MarketRegime, RiskControl, RiskLevel, TLeg
from app.signals.models import Evidence, Gap, Model, RiskFlag, RiskGateDetail, SignalInput, Stops


class RiskContext(Model):
    observations: dict[str, Evidence]
    t_leg: TLeg | None = None
    sector_memberships: list[str] | None = None
    regime: MarketRegime | None
    # RC6 checks are derived here from explicit plan and trade facts, not LLM labels.
    trade_action: Action | None
    plan_action: Action | None
    invalidated: bool | None
    plan_stop_loss: Decimal | None

    @model_validator(mode="after")
    def provenance(self) -> RiskContext:
        ids = [e.id for e in self.observations.values()]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_risk_evidence_id")
        if self.sector_memberships is not None:
            membership = self.observations.get("sector_memberships")
            if any(not key.startswith(("sw_l1.", "concept.")) for key in self.sector_memberships):
                raise ValueError("invalid_sector_membership_key")
            if len(set(self.sector_memberships)) != len(self.sector_memberships):
                raise ValueError("duplicate_sector_membership")
            if membership is None or json.loads(str(membership.value)) != self.sector_memberships:
                raise ValueError("sector_membership_evidence_mismatch")
        regime = self.observations.get("market_regime")
        if regime is not None and regime.value != self.regime:
            raise ValueError("risk_regime_evidence_mismatch")
        plan = self.observations.get("plan_trade_context")
        if plan is not None:
            expected = self.model_dump(
                mode="json",
                include={"trade_action", "plan_action", "invalidated", "plan_stop_loss"},
            )
            try:
                actual = json.loads(str(plan.value))
            except (ValueError, TypeError):
                raise ValueError("risk_plan_evidence_invalid") from None
            if actual != expected:
                raise ValueError("risk_plan_evidence_mismatch")
        return self


class RiskResult(Model):
    stops: Stops
    flags: list[RiskFlag]
    evidence: list[Evidence]
    gaps: list[str]
    quantity_cap: Decimal | None
    gate_details: list[RiskGateDetail] = Field(default_factory=list)
    t_leg: TLeg | None = None
    pause_required: bool
    pause_days: int | None = Field(ge=0)


def evaluate_risk(
    config: RiskControlsConfig,
    context: RiskContext,
    *,
    action: Action,
    horizon: Horizon,
    stops: Stops,
    lot: LotSpec | None = None,
) -> RiskResult:
    # Preserve supplied Decimal precision; final share counts use exact positive
    # integer division, not a rounded quotient crossing an integer boundary.
    with localcontext() as ctx:
        ctx.prec = max(
            64,
            len(config.model_dump_json())
            + max((len(str(e.value)) for e in context.observations.values()), default=0)
            + 64,
        )
        return _evaluate_risk(config, context, action=action, horizon=horizon, stops=stops, lot=lot)


def _evaluate_risk(
    config: RiskControlsConfig,
    context: RiskContext,
    *,
    action: Action,
    horizon: Horizon,
    stops: Stops,
    lot: LotSpec | None = None,
) -> RiskResult:
    if lot is not None and (lot.min_buy <= 0 or lot.step <= 0 or lot.max_qty < lot.min_buy):
        raise ValueError("invalid_risk_lot_spec")
    gaps: set[str] = set()
    used: dict[str, Evidence] = {}
    flags: list[RiskFlag] = []
    quantity_cap = None
    gate_details: list[RiskGateDetail] = []
    pause = False

    def number(key: str) -> Decimal | None:
        item = context.observations.get(key)
        if item is None or item.value is None or isinstance(item.value, bool):
            gaps.add(key)
            return None
        try:
            value = Decimal(str(item.value))
        except InvalidOperation:
            raise ValueError("risk_observation_not_numeric") from None
        if (
            not value.is_finite()
            or value < 0
            or (key.endswith("_streak") and value != value.to_integral_value())
        ):
            raise ValueError("risk_observation_out_of_range")
        used[item.id] = item
        return value

    def flag(
        control: RiskControl,
        message: str,
        ids: list[str],
        *,
        cap: Decimal | None = None,
        gated: list[Action] | None = None,
    ) -> None:
        flags.append(
            RiskFlag(
                control=control,
                level=RiskLevel.WARNING,
                message=message,
                gated_actions=gated or [],
                quantity_cap=cap,
                evidence_ids=sorted(set(ids)),
            )
        )

    def ids(*keys: str) -> list[str]:
        return [
            context.observations[k].id
            for k in keys
            if k in context.observations and context.observations[k].id in used
        ]

    effective = stops.model_copy(deep=True)
    if config.rc1_stop_take.enabled:
        if effective.stop_loss is None and horizon == "long":
            price = number("price")
            if price is None or price <= 0:
                gaps.add("price")
            if price is not None and price > 0:
                effective.stop_loss = price * (
                    1 + config.rc1_stop_take.long_horizon_default_stop_pct / 100
                )
        if config.rc1_stop_take.clamp_to_price_limit and any(
            v is not None for v in [effective.stop_loss, effective.take_profit]
        ):
            low, high = number("limit_down_price"), number("limit_up_price")
            if low is not None and high is not None:
                if low > high:
                    raise ValueError("risk_price_limits_reversed")
                for field in ("stop_loss", "take_profit"):
                    value = getattr(effective, field)
                    if value is not None:
                        setattr(effective, field, min(high, max(low, value)))
    if config.rc2_position_cap.enabled:
        assets, position, price = [number(k) for k in ("total_assets", "security_value", "price")]
        qty = number("proposed_quantity") if action in {"buy", "add"} else Decimal(0)
        if assets is not None and assets <= 0:
            gaps.add("total_assets")
        elif assets is not None and position is not None and price is not None:
            if price <= 0:
                gaps.add("price")
            else:
                room = max(
                    Decimal(0),
                    assets * config.rc2_position_cap.single_position_max_pct / 100 - position,
                )
                quantity_cap = room // price
                if lot is not None:
                    quantity_cap = min(quantity_cap, Decimal(lot.max_qty))
                    quantity_cap = (
                        Decimal(0)
                        if quantity_cap < lot.min_buy
                        else Decimal(lot.min_buy)
                        + ((quantity_cap - lot.min_buy) // lot.step) * lot.step
                    )
                elif action in {"buy", "add"}:
                    quantity_cap = None
                    gaps.add("market_lot_rules")
                if (
                    position > assets * config.rc2_position_cap.single_position_max_pct / 100
                    or (
                        action in {Action.BUY, Action.ADD}
                        and position
                        >= assets * config.rc2_position_cap.single_position_max_pct / 100
                    )
                    or (
                        qty is not None
                        and position + price * qty
                        > assets * config.rc2_position_cap.single_position_max_pct / 100
                    )
                ):
                    flag(
                        RiskControl.POSITION_CAP,
                        "当前或拟买入后的单只仓位达到/超过本人上限；不改变候选动作",
                        ids("total_assets", "security_value", "price", "proposed_quantity"),
                        cap=quantity_cap,
                        gated=[Action.BUY, Action.ADD]
                        if action in {Action.BUY, Action.ADD}
                        else [],
                    )
    increasing = action in {Action.BUY, Action.ADD} and context.t_leg is None

    def exposure_limit(
        control: RiskControl,
        current: Decimal,
        upper: Decimal,
        keys: list[str],
        *,
        sector: str | None = None,
        relevant: bool = True,
    ) -> None:
        nonlocal quantity_cap
        code = (
            "REGIME_MISMATCH"
            if control == RiskControl.TOTAL_EXPOSURE
            else "SECTOR_EXPOSURE_EXCEEDED"
        )
        over = current >= upper
        cap: Decimal | None = None
        gated: list[Action] = []
        cause = (
            "total_exposure_at_cap"
            if control == RiskControl.TOTAL_EXPOSURE
            else "sector_exposure_at_cap"
        )
        if increasing and relevant:
            if over:
                cap = Decimal(0)
                gated = [Action.BUY, Action.ADD]
            else:
                price, proposed = number("price"), number("proposed_quantity")
                if price is not None and price <= 0:
                    gaps.add("price")
                elif (
                    price is not None
                    and proposed is not None
                    and current + price * proposed > upper
                ):
                    if lot is None:
                        gaps.add("market_lot_rules")
                    else:
                        raw = min((upper - current) // price, Decimal(lot.max_qty))
                        cap = (
                            Decimal(0)
                            if raw < lot.min_buy
                            else Decimal(lot.min_buy)
                            + ((raw - lot.min_buy) / lot.step).to_integral_value(
                                rounding=ROUND_FLOOR
                            )
                            * lot.step
                        )
                        if cap < lot.min_buy:
                            gated = [Action.BUY, Action.ADD]
                            cause = "quantity_cap_below_min_buy"
                if cap is not None:
                    keys = [*keys, "price", "proposed_quantity"]
            if cap is not None:
                quantity_cap = cap if quantity_cap is None else min(quantity_cap, cap)
        if over or cap is not None:
            refs = ids(*keys)
            flag(control, "总仓位/板块暴露上限检查；不改写候选动作", refs, cap=cap, gated=gated)
            if gated:
                detail = {"cause": cause, "current_value": str(current), "upper_value": str(upper)}
                if sector is not None:
                    detail.update(
                        sector=sector,
                        current_pct=str(current / assets * 100) if assets else "",
                        upper_pct=str(limit),
                    )
                gate_details.append(
                    RiskGateDetail.model_validate(
                        {"control": control, "code": code, "detail": detail, "evidence_ids": refs}
                    )
                )

    if config.rc3_total_exposure.enabled:
        assets, total = number("total_assets"), number("total_value")
        if context.regime is None or "market_regime" not in context.observations:
            gaps.add("market_regime")
        elif assets is not None and assets > 0 and total is not None:
            used[context.observations["market_regime"].id] = context.observations["market_regime"]
            lower, upper = getattr(config.rc3_total_exposure.regime_ranges, context.regime)
            exposure_limit(
                RiskControl.TOTAL_EXPOSURE,
                total,
                assets * upper / 100,
                ["total_assets", "total_value", "market_regime"],
            )
            if total / assets * 100 < lower:
                flag(
                    RiskControl.TOTAL_EXPOSURE,
                    "总仓位低于环境参考下限；仅提示，不产生买入",
                    ids("total_assets", "total_value", "market_regime"),
                )
        elif assets is not None and assets <= 0:
            gaps.add("total_assets")
    if config.rc4_sector_concentration.enabled:
        assets = number("total_assets")
        memberships = context.sector_memberships
        if memberships is None:
            gaps.add("sector_memberships")
        else:
            used[context.observations["sector_memberships"].id] = context.observations[
                "sector_memberships"
            ]
        for prefix, limit in [
            ("sw_l1.", config.rc4_sector_concentration.sw_l1_max_pct),
            ("concept.", config.rc4_sector_concentration.concept_max_pct),
        ]:
            if limit == 100:  # T-A25: enabled but no sector/concept alert at 100%.
                continue
            keys = sorted(
                {key for key in context.observations if key.startswith(prefix)}
                | {key for key in memberships or [] if key.startswith(prefix)}
            )
            if not keys and memberships is None:
                gaps.add(prefix + "exposure")
            for key in keys:
                if key == "sw_l1.未分类":
                    continue
                value = number(key)
                if assets is not None and assets <= 0:
                    gaps.add("total_assets")
                elif assets is not None and value is not None:
                    exposure_limit(
                        RiskControl.SECTOR_CONCENTRATION,
                        assets * value / 100,
                        assets * limit / 100,
                        ["total_assets", key, "sector_memberships"],
                        sector=key,
                        relevant=memberships is not None and key in memberships,
                    )
    if config.rc5_loss_streak_drawdown.enabled:
        cfg = config.rc5_loss_streak_drawdown
        keys = ["closed_loss_streak", "drawdown_from_peak_pct", "strategy_sim_fail_streak"]
        values = [number(k) for k in keys]
        limits = [
            Decimal(cfg.closed_loss_streak),
            cfg.drawdown_from_peak_pct,
            Decimal(cfg.strategy_sim_fail_streak),
        ]
        if any(v is not None and v >= limit for v, limit in zip(values, limits, strict=True)):
            flag(
                RiskControl.LOSS_STREAK_DRAWDOWN,
                "连续亏损或回撤达到本人阈值",
                ids(*keys),
                gated=[Action.BUY, Action.ADD, Action.REDUCE, Action.SELL]
                if cfg.pause_on_trigger
                else [],
            )
            pause = cfg.pause_on_trigger
    if config.rc6_plan_violation.enabled:
        buy = context.trade_action in {"buy", "add"}
        sell = context.trade_action in {"reduce", "sell"}
        for check in config.rc6_plan_violation.checks:
            hit = False
            keys = []
            if context.trade_action is None or context.plan_action is None:
                gaps.add("plan_trade_context")
                continue
            if check == "opposite_side":
                hit = (buy and context.plan_action in {"reduce", "sell"}) or (
                    sell and context.plan_action in {"buy", "add"}
                )
            elif check == "qty_over_plan":
                keys = ["traded_quantity", "planned_quantity"]
                actual, planned = [number(k) for k in keys]
                hit = actual is not None and planned is not None and actual > planned
            elif check == "held_after_invalidation":
                keys = ["holding_quantity"]
                holding = number(keys[0])
                if context.invalidated is None:
                    gaps.add("plan_invalidation")
                hit = context.invalidated is True and holding is not None and holding > 0
            elif check == "buy_without_stop":
                hit = buy and context.plan_stop_loss is None
            elif check == "buy_during_wait":
                hit = buy and context.plan_action == "wait"
            if hit:
                # Explicit provenance for discrete plan/trade facts is mandatory.
                if "plan_trade_context" not in context.observations:
                    gaps.add("plan_trade_context")
                    continue
                used[context.observations["plan_trade_context"].id] = context.observations[
                    "plan_trade_context"
                ]
                flag(
                    RiskControl.PLAN_VIOLATION,
                    "成交违反有效计划：" + check,
                    ids("plan_trade_context", *keys),
                )
    return RiskResult(
        stops=effective,
        flags=flags,
        evidence=list(used.values()),
        gaps=sorted(gaps),
        quantity_cap=quantity_cap,
        gate_details=gate_details,
        t_leg=context.t_leg,
        pause_required=pause,
        pause_days=config.rc5_loss_streak_drawdown.pause_days if pause else None,
    )


CONTROL_FIELDS = {
    "stop_take": "rc1_stop_take",
    "position_cap": "rc2_position_cap",
    "total_exposure": "rc3_total_exposure",
    "sector_concentration": "rc4_sector_concentration",
    "loss_streak_drawdown": "rc5_loss_streak_drawdown",
    "plan_violation": "rc6_plan_violation",
}


def effective_config(
    conn: Connection, user_id: uuid.UUID, defaults: RiskControlsConfig
) -> RiskControlsConfig:
    """Validated file defaults, then system settings, then this user's overrides."""
    values = defaults.model_dump()
    rows = conn.execute(
        select(risk_control_settings)
        .where(
            or_(
                (risk_control_settings.c.scope == "system")
                & risk_control_settings.c.user_id.is_(None),
                (risk_control_settings.c.scope == "user")
                & (risk_control_settings.c.user_id == user_id)
                & risk_control_settings.c.override_active,
            )
        )
        .order_by(risk_control_settings.c.scope)
    ).all()
    for row in rows:
        field = CONTROL_FIELDS[row.control]
        values[field] = {**values[field], **(row.params or {}), "enabled": row.enabled}
    own_position = any(r.scope == "user" and r.control == "position_cap" for r in rows)
    if not own_position:
        from app.auth.service import latest_profile

        profile = latest_profile(conn, user_id)
        if profile is not None and profile.max_single_position_pct is not None:
            values["rc2_position_cap"]["single_position_max_pct"] = profile.max_single_position_pct
    return RiskControlsConfig.model_validate(values)


def apply_risk(signal: SignalInput, result: RiskResult, *, gaps: list[Gap]) -> SignalInput:
    """Apply before candidate creation; caller must classify gaps from actual source metadata."""
    if signal.t_leg != result.t_leg:
        raise ValueError("risk_t_leg_context_mismatch")
    if {g.key for g in gaps} != set(result.gaps):
        raise ValueError("risk_gap_classification_incomplete")
    evidence = {e.id: e for e in signal.evidence}
    for item in result.evidence:
        if item.id in evidence and evidence[item.id] != item:
            raise ValueError("risk_evidence_id_collision")
        evidence[item.id] = item
    return SignalInput.model_validate(
        {
            **signal.model_dump(),
            "stops": result.stops,
            "risk_flags": [*signal.risk_flags, *result.flags],
            "risk_details": [*signal.risk_details, *result.gate_details],
            "evidence": list(evidence.values()),
            "gaps": [*signal.gaps, *gaps],
            "data_status": "partial"
            if gaps and signal.data_status == "fresh"
            else signal.data_status,
        }
    )
