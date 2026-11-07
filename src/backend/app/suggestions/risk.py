"""RC1–RC6 deterministic hooks. Inputs are explicit cached observations, never fetched."""

from __future__ import annotations

import json
import uuid
from decimal import ROUND_FLOOR, Decimal, InvalidOperation

from pydantic import Field, model_validator
from sqlalchemy import Connection, or_, select

from app.config_files import RiskControlsConfig
from app.db.tables.strategy import risk_control_settings
from app.schemas.enums import Action, Horizon, MarketRegime, RiskControl, RiskLevel
from app.signals.models import Evidence, Gap, Model, RiskFlag, SignalInput, Stops


class RiskContext(Model):
    observations: dict[str, Evidence]
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
    pause_required: bool
    pause_days: int | None = Field(ge=0)


def evaluate_risk(
    config: RiskControlsConfig,
    context: RiskContext,
    *,
    action: Action,
    horizon: Horizon,
    stops: Stops,
) -> RiskResult:
    gaps: set[str] = set()
    used: dict[str, Evidence] = {}
    flags: list[RiskFlag] = []
    quantity_cap = None
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
        elif assets is not None and position is not None and price is not None and qty is not None:
            if price <= 0:
                gaps.add("price")
            else:
                room = max(
                    Decimal(0),
                    assets * config.rc2_position_cap.single_position_max_pct / 100 - position,
                )
                quantity_cap = (room / price).to_integral_value(rounding=ROUND_FLOOR)
                if (
                    position + price * qty
                    > assets * config.rc2_position_cap.single_position_max_pct / 100
                ):
                    flag(
                        RiskControl.POSITION_CAP,
                        "拟买入后单只仓位超过本人上限",
                        ids("total_assets", "security_value", "price", "proposed_quantity"),
                        cap=quantity_cap,
                        gated=[Action.BUY, Action.ADD],
                    )
    if config.rc3_total_exposure.enabled:
        assets, total = number("total_assets"), number("total_value")
        if context.regime is None or "market_regime" not in context.observations:
            gaps.add("market_regime")
        elif assets is not None and assets > 0 and total is not None:
            used[context.observations["market_regime"].id] = context.observations["market_regime"]
            lower, upper = getattr(config.rc3_total_exposure.regime_ranges, context.regime)
            pct = total / assets * 100
            if pct >= upper:
                # §2.5.6 says advisory, §2.5.9 lists a blocker without action scope.
                # Do not invent which strategy actions the missing policy blocks.
                gaps.add("risk_policy.rc3_gate_scope")
            if pct < lower or pct > upper:
                flag(
                    RiskControl.TOTAL_EXPOSURE,
                    "总仓位不在当前环境参考区间；不是交易指令",
                    ids("total_assets", "total_value", "market_regime"),
                )
        elif assets is not None and assets <= 0:
            gaps.add("total_assets")
    if config.rc4_sector_concentration.enabled:
        for prefix, limit in [
            ("sw_l1.", config.rc4_sector_concentration.sw_l1_max_pct),
            ("concept.", config.rc4_sector_concentration.concept_max_pct),
        ]:
            keys = [key for key in context.observations if key.startswith(prefix)]
            if not keys:
                gaps.add(prefix + "exposure")
            for key in keys:
                if key == "sw_l1.未分类":
                    continue  # Contract §9: unknown sector is never an RC4 trigger.
                value = number(key)
                if value is not None and value > limit:
                    gaps.add("risk_policy.rc4_gate_scope")
                    flag(RiskControl.SECTOR_CONCENTRATION, "板块集中度超过本人上限", ids(key))
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
                & (risk_control_settings.c.user_id == user_id),
            )
        )
        .order_by(risk_control_settings.c.scope)
    ).all()
    for row in rows:
        field = CONTROL_FIELDS[row.control]
        values[field] = {**values[field], **(row.params or {}), "enabled": row.enabled}
    return RiskControlsConfig.model_validate(values)


def apply_risk(signal: SignalInput, result: RiskResult, *, gaps: list[Gap]) -> SignalInput:
    """Apply before candidate creation; caller must classify gaps from actual source metadata."""
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
            "evidence": list(evidence.values()),
            "gaps": [*signal.gaps, *gaps],
            "data_status": "partial"
            if gaps and signal.data_status == "fresh"
            else signal.data_status,
        }
    )
