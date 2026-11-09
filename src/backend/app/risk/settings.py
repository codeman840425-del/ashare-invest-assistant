"""P2N-02 settings: file → DB system → profile → owner override; atomic history."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, insert, select, text, update

from app.auth.service import audit, latest_profile
from app.common.errors import AppError, ErrorCode
from app.config_files import RiskControlsConfig
from app.db.tables.strategy import risk_control_settings as settings
from app.db.tables.strategy import risk_control_settings_history as history
from app.suggestions.risk import CONTROL_FIELDS, effective_config

# Read-only reset values, pinned to §7.11.2 / its §6.1 RC6 reference.
# Never derived from a user's or the DB system's effective overrides.
DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "stop_take": {"long_horizon_default_stop_pct": "-20", "clamp_to_price_limit": True},
    "position_cap": {"single_position_max_pct": "20"},
    "total_exposure": {
        "regime_ranges": {"uptrend": ["60", "90"], "range": ["40", "60"], "downtrend": ["0", "30"]},
        "regime_confirm_days": 2,
    },
    "sector_concentration": {"sw_l1_max_pct": "40", "concept_max_pct": "50"},
    "loss_streak_drawdown": {
        "closed_loss_streak": 3,
        "drawdown_from_peak_pct": "10",
        "strategy_sim_fail_streak": 5,
        "pause_on_trigger": True,
        "pause_days": 5,
    },
    "plan_violation": {
        "checks": [
            "opposite_side",
            "qty_over_plan",
            "held_after_invalidation",
            "buy_without_stop",
            "buy_during_wait",
        ]
    },
}


def canonical(value: Any) -> Any:  # noqa: ANN401
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, (str, Decimal)) and re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", str(value)):
        result = format(Decimal(value), "f")
        if "." in result:
            result = result.rstrip("0").rstrip(".")
        return "0" if Decimal(result) == 0 else result
    return value


def entries(
    conn: Connection, owner: uuid.UUID, defaults: RiskControlsConfig
) -> list[dict[str, Any]]:
    cfg = effective_config(conn, owner, defaults)
    overrides = set(
        conn.execute(
            select(settings.c.control).where(
                settings.c.scope == "user",
                settings.c.user_id == owner,
                settings.c.override_active,
            )
        ).scalars()
    )
    profile = latest_profile(conn, owner)
    if profile is not None and profile.max_single_position_pct is not None:
        overrides.add("position_cap")
    return [
        {
            "control": control,
            "enabled": getattr(cfg, field).enabled,
            "params": canonical(getattr(cfg, field).model_dump(mode="json", exclude={"enabled"})),
            "source": "user" if control in overrides else "system",
            "default": canonical(DEFAULT_PARAMS[control]),
        }
        for control, field in CONTROL_FIELDS.items()
    ]


def save(
    conn: Connection,
    owner: uuid.UUID,
    role: str,
    defaults: RiskControlsConfig,
    patches: list[dict[str, Any]],
    now: dt.datetime,
) -> list[dict[str, Any]]:
    controls = [item["control"] for item in patches]
    if len(set(controls)) != len(controls):
        raise AppError(ErrorCode.VALIDATION_ERROR)
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,202602))"), {"owner": str(owner)}
    )

    def precision_fields(value: object, path: str) -> list[str]:
        if isinstance(value, dict):
            return [p for k, v in value.items() for p in precision_fields(v, path + "." + k)]
        if isinstance(value, (list, tuple)):
            return [
                p for i, v in enumerate(value) for p in precision_fields(v, path + "." + str(i))
            ]
        if isinstance(value, str):
            try:
                number = Decimal(value)
            except InvalidOperation:
                return []
            exponent = number.as_tuple().exponent
            if number.is_finite() and isinstance(exponent, int) and exponent < -2:
                return [path]
        return []

    precision = [
        key for patch in patches for key in precision_fields(patch["params"], patch["control"])
    ]
    if precision:
        raise AppError(
            ErrorCode.RISK_CONTROL_INVALID_PARAMS,
            details={
                "control": precision[0].split(".")[0],
                "fields": [{"field": k, "issue": "max_decimal_places_2"} for k in precision],
            },
        )
    values = effective_config(conn, owner, defaults).model_dump()
    for patch in patches:
        values[CONTROL_FIELDS[patch["control"]]] = {**patch["params"], "enabled": patch["enabled"]}
    try:
        RiskControlsConfig.model_validate(values)
    except ValidationError as error:
        reverse = {v: k for k, v in CONTROL_FIELDS.items()}
        fields = [
            ".".join(str(reverse.get(str(v), v)) for v in e["loc"])
            for e in error.errors(include_input=False)
        ]
        raise AppError(
            ErrorCode.RISK_CONTROL_INVALID_PARAMS,
            details={
                "control": fields[0].split(".")[0],
                "fields": [{"field": k, "issue": "out_of_range"} for k in fields],
            },
        ) from None
    # Validate the ENTIRE patch before the first write/history/audit.
    for patch in patches:
        params = canonical(patch["params"])
        previous = conn.execute(
            select(settings)
            .where(
                settings.c.scope == "user",
                settings.c.user_id == owner,
                settings.c.control == patch["control"],
            )
            .with_for_update()
        ).first()
        if (
            previous is not None
            and previous.override_active
            and previous.enabled == patch["enabled"]
            and canonical(previous.params) == params
        ):
            continue
        identifier = previous.id if previous is not None else uuid.uuid4()
        if previous is None:
            conn.execute(
                insert(settings).values(
                    id=identifier,
                    scope="user",
                    user_id=owner,
                    control=patch["control"],
                    enabled=patch["enabled"],
                    params=params,
                    updated_at=now,
                )
            )
        else:
            conn.execute(
                update(settings)
                .where(settings.c.id == identifier)
                .values(
                    enabled=patch["enabled"], params=params, updated_at=now, override_active=True
                )
            )
        hid = uuid.uuid4()
        conn.execute(
            insert(history).values(
                id=hid,
                setting_id=identifier,
                scope="user",
                user_id=owner,
                control=patch["control"],
                enabled=patch["enabled"],
                params=params,
                changed_by=owner,
                changed_at=now,
            )
        )
        audit(
            conn,
            action="risk_control.updated",
            actor_id=owner,
            actor_role=role,
            target_type="risk_control_setting",
            target_id=str(identifier),
            detail={"control": patch["control"], "history_id": str(hid)},
        )
    return entries(conn, owner, defaults)


def reset(
    conn: Connection,
    owner: uuid.UUID,
    role: str,
    defaults: RiskControlsConfig,
    control: str,
    now: dt.datetime,
) -> list[dict[str, Any]]:
    """T-A52: clear one owned override, preserving its identity and append-only history."""
    if control not in CONTROL_FIELDS:
        raise AppError(ErrorCode.NOT_FOUND)
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,202602))"), {"owner": str(owner)}
    )
    previous = conn.execute(
        select(settings)
        .where(
            settings.c.scope == "user",
            settings.c.user_id == owner,
            settings.c.control == control,
        )
        .with_for_update()
    ).first()
    if previous is None or not previous.override_active:
        return entries(conn, owner, defaults)
    conn.execute(
        update(settings)
        .where(settings.c.id == previous.id)
        .values(
            override_active=False,
            updated_at=now,
        )
    )
    hid = uuid.uuid4()
    conn.execute(
        insert(history).values(
            id=hid,
            setting_id=previous.id,
            scope="user",
            user_id=owner,
            control=control,
            enabled=None,
            params=None,
            changed_by=owner,
            changed_at=now,
        )
    )
    audit(
        conn,
        action="risk_control.reset",
        actor_id=owner,
        actor_role=role,
        target_type="risk_control_setting",
        target_id=str(previous.id),
        detail={"control": control, "history_id": str(hid), "had_override": True},
    )
    return entries(conn, owner, defaults)
