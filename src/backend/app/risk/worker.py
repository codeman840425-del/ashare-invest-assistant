"""Recurring owned RC1 warnings, raw PIT evidence, no orders or notification IO."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text

from app.config import Settings
from app.db.tables.accounts import accounts
from app.db.tables.market import securities, trading_calendar
from app.db.tables.realtime import suggestions
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import strategy_instances
from app.db.tables.users import users
from app.risk.evaluation import assessed, inputs
from app.risk.events import record
from app.risk.rc1 import SH, load
from app.schemas.enums import Action, Horizon
from app.signals.models import Stops
from app.suggestions.risk import effective_config

TASK = "risk.rc1_checks"


def task(settings: Settings) -> int:
    from app.workers.jobs import _engine, _now

    at = _now()
    local = at.astimezone(SH)
    clock = local.time().replace(tzinfo=None)
    if not (
        dt.time(9, 30) <= clock < dt.time(11, 30)
        or dt.time(13) <= clock < dt.time(15)
        or clock >= dt.time(15)
    ):
        return 0
    count = 0
    with _engine(settings).begin() as conn:
        if (
            conn.execute(
                select(trading_calendar.c.is_open).where(trading_calendar.c.date == local.date())
            ).scalar_one_or_none()
            is not True
        ):
            return 0
        instances = conn.execute(
            select(strategy_instances)
            .join(users, users.c.id == strategy_instances.c.user_id)
            .join(accounts, accounts.c.id == strategy_instances.c.account_id)
            .where(
                strategy_instances.c.status == "active",
                strategy_instances.c.created_at <= at,
                users.c.status == "approved",
                accounts.c.user_id == users.c.id,
                accounts.c.archived_at.is_(None),
                accounts.c.created_at <= at,
            )
            .order_by(strategy_instances.c.user_id, strategy_instances.c.id)
        ).all()
        for instance in instances:
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"),
                {"owner": str(instance.user_id)},
            )
            rows = conn.execute(
                select(suggestions)
                .join(data_snapshots, suggestions.c.snapshot_id == data_snapshots.c.id)
                .where(
                    suggestions.c.user_id == instance.user_id,
                    suggestions.c.status == "active",
                    suggestions.c.created_at <= at,
                    data_snapshots.c.user_id == instance.user_id,
                    data_snapshots.c.created_at <= at,
                    suggestions.c.strategies.contains(
                        [
                            {
                                "instance_id": str(instance.id),
                                "strategy_version_id": str(
                                    instance.derived_strategy_version_id
                                    or instance.strategy_version_id
                                ),
                            }
                        ]
                    ),
                )
                .order_by(suggestions.c.created_at.desc(), suggestions.c.id.desc())
            ).all()
            seen: set[str] = set()
            for suggestion in rows:
                code = suggestion.security_code
                if code in seen:
                    continue
                seen.add(code)
                # Use this instance's latest immutable stops, never another account's
                # or another strategy's merged flag/price threshold.
                strategy = next(
                    r for r in suggestion.strategies if r.get("instance_id") == str(instance.id)
                )
                source = inputs(
                    conn,
                    instance.user_id,
                    code,
                    instance.account_id,
                    settings,
                    at,
                    feature_set_version=suggestion.feature_set_version,
                )
                source.rc1 = load(
                    conn,
                    instance.user_id,
                    instance.account_id,
                    code,
                    settings,
                    at,
                    stops_at=suggestion.created_at,
                    position_known=source.position_known,
                )
                if source.rc1.held is not True:
                    continue
                result, controls = assessed(
                    effective_config(conn, instance.user_id, settings.business.risk_controls),
                    source,
                    action=Action(strategy["action"]),
                    horizon=Horizon(strategy["horizon"]),
                    stops=Stops.model_validate(strategy["stops"]),
                    at=at,
                )
                name = (
                    conn.execute(
                        select(securities.c.name).where(securities.c.code == code)
                    ).scalar_one_or_none()
                    or code
                )
                record(
                    conn,
                    owner=instance.user_id,
                    account_id=instance.account_id,
                    instance_id=instance.id,
                    code=code,
                    name=name,
                    controls=[c for c in controls if c["control"] == "stop_take"],
                    evidence=[e.model_dump(mode="json") for e in result.evidence],
                    at=at,
                    suggestion_id=suggestion.id,
                )
                count += 1
    return count
