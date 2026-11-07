"""I1–I7 local instantiation boundary. No strategy content or external data acquisition."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, Row, insert, select, update

from app.common.errors import AppError, ErrorCode
from app.config_files import RiskControlsConfig
from app.db.tables.accounts import accounts, holdings
from app.db.tables.market import securities
from app.db.tables.strategy import (
    risk_control_settings,
    strategies,
    strategy_card_versions,
    symbol_horizon_assessments,
)
from app.db.tables.strategy import strategy_instances as instances
from app.db.tables.strategy import strategy_versions as versions
from app.db.tables.users import user_profiles
from app.schemas.enums import RiskControl
from app.strategy.eligibility import ensure_strategy_eligible
from app.strategy.instances.service import event, owned


def version_owned(conn: Connection, user_id: uuid.UUID, version_id: uuid.UUID) -> Row[Any]:
    row = conn.execute(
        select(versions)
        .join(strategies, strategies.c.id == versions.c.strategy_id)
        .where(
            versions.c.id == version_id,
            (strategies.c.owner_user_id.is_(None)) | (strategies.c.owner_user_id == user_id),
        )
    ).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def derive(
    conn: Connection, user_id: uuid.UUID, version: Row[Any], overrides: dict[str, Any]
) -> uuid.UUID | None:
    if not overrides:
        return None
    schema = (
        version.params_schema
        or version.config.get("params_schema")
        or version.config.get("params")
        or {}
    )
    if isinstance(schema, list):
        schema = {item["name"]: item for item in schema}
    for key, value in overrides.items():
        definition = schema.get(key) or {}
        typ = definition.get("type")
        valid = definition.get("user_editable", True) is True
        if typ == "int":
            valid &= type(value) is int
        elif typ == "float":
            valid &= type(value) in {int, float} and math.isfinite(value)
        elif typ == "bool":
            valid &= type(value) is bool
        elif typ == "enum":
            valid &= value in definition.get("choices", []) and type(value) in {
                str,
                int,
                float,
                bool,
            }
        else:
            valid = False
        if valid and typ in {"int", "float"}:
            lo, hi, step = definition.get("min"), definition.get("max"), definition.get("step")
            if type(lo) not in {int, float} or type(hi) not in {int, float}:
                valid = False
            else:
                number = Decimal(str(value))
                valid = Decimal(str(lo)) <= number <= Decimal(str(hi))
                if valid and step is not None:
                    interval = Decimal(str(step))
                    valid = interval > 0 and (number - Decimal(str(lo))) % interval == 0
        if not valid:
            raise AppError(
                ErrorCode.STRATEGY_PARAM_OUT_OF_RANGE,
                details={
                    "param": key,
                    "min": definition.get("min"),
                    "max": definition.get("max"),
                },
            )
    configuration = copy.deepcopy(version.config)
    configuration["param_overrides"] = overrides
    digest = hashlib.sha256(
        json.dumps(configuration, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    strategy_id, identifier = uuid.uuid4(), uuid.uuid4()
    parent = conn.execute(select(strategies).where(strategies.c.id == version.strategy_id)).one()
    conn.execute(
        insert(strategies).values(
            id=strategy_id,
            key="private_" + strategy_id.hex,
            owner_user_id=user_id,
            name=parent.name,
            horizons=parent.horizons,
            copied_from_version_id=version.id,
        )
    )
    conn.execute(
        insert(versions).values(
            id=identifier,
            strategy_id=strategy_id,
            version_no=1,
            config=configuration,
            config_hash=digest,
            parent_version_id=version.id,
            card_version_id=version.card_version_id,
            kind=version.kind,
            lifecycle=version.lifecycle,
            params_schema=schema,
            param_hash=hashlib.sha256(
                json.dumps(overrides, sort_keys=True, allow_nan=False).encode()
            ).hexdigest(),
        )
    )
    conn.execute(
        update(strategies)
        .where(strategies.c.id == strategy_id)
        .values(current_version_id=identifier)
    )
    return identifier


def risk_snapshot(
    conn: Connection, user_id: uuid.UUID, config: RiskControlsConfig
) -> dict[str, Any]:
    sections = (
        config.rc1_stop_take,
        config.rc2_position_cap,
        config.rc3_total_exposure,
        config.rc4_sector_concentration,
        config.rc5_loss_streak_drawdown,
        config.rc6_plan_violation,
    )
    result: dict[str, Any] = {}
    for control, section in zip(RiskControl, sections, strict=True):
        effective = section
        for scope in ("system", "user"):
            row = conn.execute(
                select(risk_control_settings).where(
                    risk_control_settings.c.control == control.value,
                    risk_control_settings.c.scope == scope,
                    risk_control_settings.c.user_id.is_(None)
                    if scope == "system"
                    else risk_control_settings.c.user_id == user_id,
                )
            ).first()
            if row is not None:
                effective = type(section).model_validate(
                    effective.model_dump() | (row.params or {}) | {"enabled": row.enabled}
                )
        data = effective.model_dump(mode="json")
        enabled = data.pop("enabled")
        result[control.value] = {"enabled": enabled, "params": data}
    return result


def create(
    conn: Connection,
    user_id: uuid.UUID,
    *,
    is_admin: bool,
    version_id: uuid.UUID,
    account_id: uuid.UUID,
    security_code: str | None,
    scope: str,
    horizon: str,
    overrides: dict[str, Any] | None,
    budget: Decimal | None,
    risk_config: RiskControlsConfig,
) -> dict[str, Any]:
    # Lock account before constructing any derived version or writing an instance.
    account = conn.execute(
        select(accounts.c.id)
        .where(
            accounts.c.id == account_id,
            accounts.c.user_id == user_id,
            accounts.c.archived_at.is_(None),
        )
        .with_for_update()
    ).first()
    if account is None:
        raise AppError(ErrorCode.NOT_FOUND)
    version = version_owned(conn, user_id, version_id)
    if version.config.get("mount_policy") == "system_only":
        raise AppError(ErrorCode.STRATEGY_SYSTEM_ONLY)
    if version.lifecycle not in {"published", "observing"} and not (
        is_admin and version.lifecycle == "simulating"
    ):
        raise AppError(
            ErrorCode.STRATEGY_VERSION_NOT_RUNNABLE, details={"lifecycle": version.lifecycle}
        )
    if version.config.get("origin") == "system":
        raise AppError(ErrorCode.INSTANCE_SCOPE_INVALID, details={"issue": "system_component"})
    if horizon not in version.config.get("horizons", []):
        raise AppError(ErrorCode.STRATEGY_HORIZON_MISMATCH)
    if scope == "watch_group":
        raise AppError(
            ErrorCode.INSTANCE_SCOPE_INVALID,
            details={
                "scope": scope,
                "issue": "scope_deferred",
            },
        )
    if (scope == "security") != (security_code is not None):
        raise AppError(ErrorCode.INSTANCE_SCOPE_INVALID)
    if security_code:
        typ = conn.execute(
            select(securities.c.type).where(securities.c.code == security_code)
        ).scalar_one_or_none()
        ensure_strategy_eligible(security_code, typ)
    if horizon == "intraday_t":
        query = (
            select(holdings.c.quantity)
            .join(
                securities,
                securities.c.code == holdings.c.security_code,
            )
            .where(
                securities.c.type.in_(["stock", "cdr"]),
                holdings.c.account_id == account_id,
                holdings.c.quantity > 0,
            )
        )
        if security_code:
            query = query.where(holdings.c.security_code == security_code)
        if conn.execute(query).first() is None:
            raise AppError(ErrorCode.INSTANCE_SCOPE_INVALID, details={"issue": "no_base_position"})
    snapshot = risk_snapshot(conn, user_id, risk_config)
    warnings = ["必需数据覆盖尚未全部核实，实例范围标为 partial；缺失数据不得产生确定结论。"]
    if not snapshot["stop_take"]["enabled"]:
        warnings.append("RC1已关闭：此实例仍须持续展示止损/止盈缺失警示。")
    if security_code:
        assessment = conn.execute(
            select(symbol_horizon_assessments.c.suitable_horizons)
            .where(
                symbol_horizon_assessments.c.user_id == user_id,
                symbol_horizon_assessments.c.security_code == security_code,
            )
            .order_by(symbol_horizon_assessments.c.created_at.desc())
            .limit(1)
        ).first()
        if assessment is not None and horizon not in (assessment[0] or []):
            warnings.append("周期分类未推荐此周期，仍可自由启用。")
    card = None
    if version.card_version_id:
        card = conn.execute(
            select(strategy_card_versions.c.fields).where(
                strategy_card_versions.c.id == version.card_version_id,
            )
        ).scalar_one_or_none()
    profile = conn.execute(
        select(user_profiles)
        .where(user_profiles.c.user_id == user_id)
        .order_by(user_profiles.c.version_no.desc())
        .limit(1)
    ).first()
    fit = (card or {}).get("fit") or {}
    if profile is not None:
        if (
            profile.risk_tolerance is not None
            and fit.get("risk_tolerance_min") is not None
            and profile.risk_tolerance < fit["risk_tolerance_min"]
        ):
            warnings.append("自报风险承受能力低于策略适配下限；不阻止启用。")
        experience = {"novice": 0, "intermediate": 1, "advanced": 2}
        if (
            profile.experience in experience
            and fit.get("experience_min") in experience
            and experience[profile.experience] < experience[fit["experience_min"]]
        ):
            warnings.append("自报经验低于策略适配下限；不阻止启用。")
        effort = {"low": 0, "medium": 1, "high": 2}
        if (
            profile.effort in effort
            and fit.get("effort") in effort
            and effort[profile.effort] < effort[fit["effort"]]
        ):
            warnings.append("自报投入精力低于策略适配要求；不阻止启用。")
    derived = derive(conn, user_id, version, overrides or {})
    identifier = uuid.uuid4()
    conn.execute(
        insert(instances).values(
            id=identifier,
            user_id=user_id,
            strategy_version_id=version_id,
            derived_strategy_version_id=derived,
            account_id=account_id,
            scope=scope,
            security_code=security_code,
            horizon=horizon,
            origin="user",
            status="active",
            param_overrides=overrides,
            budget_amount=budget,
            risk_settings_snapshot={"controls": snapshot, "data_coverage": "partial"},
            confirmed_at=dt.datetime.now(dt.UTC),
        )
    )
    event(conn, identifier, kind="created", actor_id=user_id, before=None, after="active")
    return {
        "id": identifier,
        "status": "active",
        "derived_strategy_version_id": derived,
        "warnings": warnings,
    }


def patch(
    conn: Connection, user_id: uuid.UUID, instance_id: uuid.UUID, changes: dict[str, Any]
) -> Row[Any]:
    row = owned(conn, user_id, instance_id, lock=True)
    if row.status == "archived":
        raise AppError(ErrorCode.IMMUTABLE_RESOURCE)
    if not changes:
        return row
    values: dict[str, Any] = {"updated_at": dt.datetime.now(dt.UTC)}
    if "param_overrides" in changes:
        version = version_owned(conn, user_id, row.strategy_version_id)
        derived = derive(conn, user_id, version, changes["param_overrides"] or {})
        values.update(
            param_overrides=changes["param_overrides"], derived_strategy_version_id=derived
        )
        event(
            conn,
            instance_id,
            kind="params_changed",
            actor_id=user_id,
            before=None,
            after=None,
            detail={"derived_strategy_version_id": str(derived) if derived else None},
        )
    if "budget_amount" in changes:
        values["budget_amount"] = changes["budget_amount"]
    conn.execute(update(instances).where(instances.c.id == instance_id).values(**values))
    return owned(conn, user_id, instance_id)
