"""RC5 transaction hooks. No scheduler, collector, HTTP, or transport activation.

Only hash-verified, owned assessment receipts can move the edge cursor. The
append-only risk_events journal is internal, not a second public event machine.
The caller owns the transaction, including instance/event/notification writes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Row, insert, select, text, update

from app.common.errors import AppError, ErrorCode
from app.config_files import RiskControlsConfig
from app.db.tables.accounts import accounts
from app.db.tables.market import trading_calendar
from app.db.tables.notify import notifications
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import risk_events, strategies, strategy_instances, strategy_versions
from app.db.tables.users import users
from app.feedback.core import timestamp
from app.schemas.enums import (
    InstanceOrigin,
    InstancePausedBy,
    InstanceStatus,
    Lifecycle,
    ReasonCode,
)
from app.signals.models import Evidence
from app.strategy.instances.service import event, owned
from app.strategy.instances.state import InstanceOp, InstanceState, apply_user_op, system_pause
from app.suggestions.risk import effective_config

TZ = ZoneInfo("Asia/Shanghai")
SCHEMA = "p2n08-rc5-cursor/v1"
INPUT = "p2n08-rc5-assessment/v1"


def canonical(value: Any) -> str:  # noqa: ANN401 - immutable JSON envelope
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def digest(value: Any) -> str:  # noqa: ANN401
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    value: Decimal | None = Field(ge=0)
    evidence_ids: list[str]
    gaps: list[str]


class Values(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    closed_loss_streak: Value
    drawdown_from_peak_pct: Value
    strategy_sim_fail_streak: Value

    @model_validator(mode="after")
    def counts(self) -> Values:
        for item in [self.closed_loss_streak, self.strategy_sim_fail_streak]:
            if item.value is not None and item.value != item.value.to_integral_value():
                raise ValueError("rc5_streak_requires_integer")
        return self


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    schema_version: Literal["p2n08-rc5-assessment/v1"] = Field(alias="schema")
    user_id: uuid.UUID
    instance_id: uuid.UUID
    account_id: uuid.UUID
    strategy_version_id: uuid.UUID
    as_of: dt.datetime
    policy_hash: str
    metrics: Values
    evidence: list[Evidence]


@dataclass(frozen=True)
class Outcome:
    changed: bool = False
    edge: bool = False
    resumed: bool = False
    blocked: bool = False
    gaps: tuple[str, ...] = ()


def pause_until(
    trigger: dt.datetime, count: int, calendar: dict[dt.date, bool]
) -> dt.datetime | None:
    point = timestamp(trigger).astimezone(TZ)
    if type(count) is not int or count < 1:
        raise ValueError("rc5_pause_days_positive")
    date = point.date()
    if date not in calendar:
        return None
    if not calendar[date] or point.timetz().replace(tzinfo=None) > dt.time(15):
        date += dt.timedelta(days=1)
        while date in calendar and not calendar[date]:
            date += dt.timedelta(days=1)
    if date not in calendar:
        return None
    remaining = count
    while remaining:
        date += dt.timedelta(days=1)
        if date not in calendar:
            return None
        remaining -= int(calendar[date])
    return dt.datetime.combine(date, dt.time(15), TZ)


def _calendar(conn: Connection) -> dict[dt.date, bool]:
    return {r.date: r.is_open for r in conn.execute(select(trading_calendar))}


def _locked(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID) -> tuple[Row[Any], Row[Any]]:
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:o,74))"), {"o": str(owner)})
    status = conn.execute(
        select(users.c.status).where(users.c.id == owner).with_for_update()
    ).scalar_one_or_none()
    if status != "approved":
        raise AppError(ErrorCode.ACCOUNT_NOT_APPROVED)
    instance = owned(conn, owner, identifier, lock=True)
    actual = instance.derived_strategy_version_id or instance.strategy_version_id
    version = conn.execute(
        select(strategy_versions).where(strategy_versions.c.id == actual).with_for_update(read=True)
    ).one()
    template_owner = conn.execute(
        select(strategies.c.owner_user_id)
        .where(strategies.c.id == version.strategy_id)
        .with_for_update(read=True)
    ).scalar_one()
    if template_owner is not None and template_owner != owner:
        raise AppError(ErrorCode.NOT_FOUND)
    return instance, version


def _state(row: Row[Any]) -> InstanceState:
    return InstanceState(
        status=InstanceStatus(row.status),
        origin=InstanceOrigin(row.origin),
        paused_by=InstancePausedBy(row.paused_by) if row.paused_by else None,
        pause_reason_code=ReasonCode(row.pause_reason_code) if row.pause_reason_code else None,
        paused_until=row.paused_until,
        archived_at=row.archived_at,
        updated_at=row.updated_at,
    )


def _write(
    conn: Connection, row: Row[Any], state: InstanceState, kind: str, detail: dict[str, Any]
) -> None:
    conn.execute(
        update(strategy_instances)
        .where(strategy_instances.c.id == row.id, strategy_instances.c.user_id == row.user_id)
        .values(
            status=state.status.value,
            paused_by=state.paused_by.value if state.paused_by else None,
            pause_reason_code=state.pause_reason_code.value if state.pause_reason_code else None,
            paused_until=state.paused_until,
            updated_at=state.updated_at,
        )
    )
    event(
        conn,
        row.id,
        kind=kind,
        actor_id=None,
        before=row.status,
        after=state.status.value,
        detail=detail,
        at=state.updated_at,
    )


def _account_valid(conn: Connection, row: Row[Any]) -> bool:
    return (
        conn.execute(
            select(accounts.c.id)
            .where(
                accounts.c.id == row.account_id,
                accounts.c.user_id == row.user_id,
                accounts.c.archived_at.is_(None),
            )
            .with_for_update(read=True)
        ).first()
        is not None
    )


def apply_receipt(
    conn: Connection,
    owner: uuid.UUID,
    identifier: uuid.UUID,
    snapshot_id: uuid.UUID,
    config: RiskControlsConfig,
    *,
    now: dt.datetime,
) -> Outcome:
    timestamp(now)
    row, version = _locked(conn, owner, identifier)
    if not _account_valid(conn, row):
        return Outcome(gaps=("rc5_account_unavailable",))
    cfg = effective_config(conn, owner, config).rc5_loss_streak_drawdown
    if cfg.sim_fail_horizon_by_horizon is None:
        return Outcome(gaps=("sim_fail_horizon_config_missing",))
    source = conn.execute(
        select(data_snapshots).where(
            data_snapshots.c.id == snapshot_id,
            data_snapshots.c.user_id == owner,
            data_snapshots.c.purpose == "signal",
        )
    ).first()
    if source is None:
        raise AppError(ErrorCode.NOT_FOUND)
    if source.hash != digest(source.items):
        raise ValueError("rc5_receipt_hash_invalid")
    receipt = Receipt.model_validate(source.items)
    if (receipt.user_id, receipt.instance_id, receipt.account_id, receipt.strategy_version_id) != (
        owner,
        identifier,
        row.account_id,
        version.id,
    ):
        raise ValueError("rc5_receipt_binding_invalid")
    timestamp(receipt.as_of)
    if (
        source.created_at > receipt.as_of
        or receipt.as_of > now
        or receipt.policy_hash != digest(cfg.model_dump(mode="json"))
    ):
        return Outcome(gaps=("rc5_receipt_pit_or_policy_stale",))
    evidence = {e.id: e for e in receipt.evidence}
    if len(evidence) != len(receipt.evidence) or any(
        e.data_as_of is None
        or e.data_as_of > receipt.as_of
        or e.fetched_at is None
        or e.fetched_at > receipt.as_of
        for e in receipt.evidence
    ):
        raise ValueError("rc5_evidence_pit_invalid")
    previous = conn.execute(
        select(risk_events)
        .where(
            risk_events.c.user_id == owner,
            risk_events.c.detail["schema"].astext == SCHEMA,
            risk_events.c.detail["instance_id"].astext == str(identifier),
            risk_events.c.detail["strategy_version_id"].astext == str(version.id),
        )
        .order_by(risk_events.c.created_at.desc(), risk_events.c.id.desc())
        .limit(1)
    ).first()
    prior = previous.detail if previous else None
    if prior and dt.datetime.fromisoformat(prior["as_of"]) >= receipt.as_of:
        if dt.datetime.fromisoformat(prior["as_of"]) == receipt.as_of and prior[
            "snapshot_id"
        ] != str(snapshot_id):
            raise ValueError("rc5_receipt_time_conflict")
        return Outcome()
    known = dict(prior["known"]) if prior else dict.fromkeys(Values.model_fields)
    edges = []
    gaps = set()
    for key in Values.model_fields:
        metric = getattr(receipt.metrics, key)
        if metric.value is None or metric.gaps:
            gaps.add("rc5_" + key + "_unknown")
            continue
        if not metric.evidence_ids or not set(metric.evidence_ids) <= set(evidence):
            raise ValueError("rc5_evidence_unresolved")
        before = Decimal(str(known[key])) if known[key] is not None else None
        threshold = Decimal(getattr(cfg, key))
        if metric.value >= threshold:
            if before is None:
                gaps.add("rc5_previous_value_missing")
            elif (
                (before < threshold) if key == "drawdown_from_peak_pct" else (metric.value > before)
            ):
                edges.append(key)
        known[key] = str(metric.value)
    eligible = row.status == "active" or (
        row.status == "paused"
        and row.paused_by == "system"
        and row.pause_reason_code == "LOSS_STREAK_PAUSE"
        and (row.paused_until is not None or version.lifecycle in {"published", "observing"})
    )
    needs_pause = bool(edges) and cfg.enabled and cfg.pause_on_trigger and eligible
    if needs_pause and receipt.as_of < row.updated_at:
        # A delayed receipt may not undo a more recent explicit user operation.
        needs_pause = False
        gaps.add("rc5_receipt_precedes_instance_change")
    end = pause_until(receipt.as_of, cfg.pause_days, _calendar(conn)) if needs_pause else None
    if needs_pause and end is None:
        # Do not consume an unprocessed edge; a later calendar repair may replay.
        return Outcome(edge=True, gaps=("calendar_not_covered",))
    stored = max(now, previous.created_at + dt.timedelta(microseconds=1)) if previous else now
    conn.execute(
        insert(risk_events).values(
            id=uuid.uuid4(),
            user_id=owner,
            control="loss_streak_drawdown",
            level="info",
            subject="strategy",
            security_code=row.security_code,
            created_at=stored,
            detail={
                "schema": SCHEMA,
                "instance_id": str(identifier),
                "account_id": str(row.account_id),
                "strategy_version_id": str(version.id),
                "snapshot_id": str(snapshot_id),
                "as_of": receipt.as_of.isoformat(),
                "known": known,
                "edges": edges,
                "gaps": sorted(gaps),
                "policy_hash": receipt.policy_hash,
            },
        )
    )
    if not needs_pause:
        return Outcome(edge=bool(edges), gaps=tuple(sorted(gaps)))
    from dataclasses import replace

    state = _state(row)
    if row.status == "active":
        state = system_pause(state, now=now, paused_until=end).state
    elif row.paused_until is None:
        # An expiry-blocked instance is not silently rearmed while non-runnable.
        if version.lifecycle not in {"published", "observing"}:
            return Outcome(edge=True, gaps=("strategy_version_not_runnable",))
        state = replace(state, paused_until=end, updated_at=now)
    elif end is not None and end > row.paused_until:
        state = replace(state, paused_until=end, updated_at=now)
    else:
        return Outcome(edge=True, gaps=tuple(sorted(gaps)))
    _write(
        conn,
        row,
        state,
        "paused",
        {
            "reason_code": "LOSS_STREAK_PAUSE",
            "triggered_at": receipt.as_of.isoformat(),
            "paused_until": state.paused_until.isoformat() if state.paused_until else None,
            "edge_metrics": edges,
            "snapshot_id": str(snapshot_id),
        },
    )
    return Outcome(changed=True, edge=True, gaps=tuple(sorted(gaps)))


def resume_due(
    conn: Connection,
    owner: uuid.UUID,
    identifier: uuid.UUID,
    config: RiskControlsConfig,
    *,
    now: dt.datetime,
) -> Outcome:
    timestamp(now)
    row, version = _locked(conn, owner, identifier)
    if (
        row.status != "paused"
        or row.paused_by != "system"
        or row.pause_reason_code != "LOSS_STREAK_PAUSE"
        or row.paused_until is None
        or row.paused_until > now
    ):
        return Outcome()
    if config.rc5_loss_streak_drawdown.sim_fail_horizon_by_horizon is None:
        return Outcome(gaps=("sim_fail_horizon_config_missing",))
    if not _account_valid(conn, row):
        return Outcome(gaps=("rc5_account_unavailable",))
    calendar = _calendar(conn)
    start, end = row.paused_until.astimezone(TZ).date(), now.astimezone(TZ).date()
    if not calendar.get(start, False) or any(
        start + dt.timedelta(days=i) not in calendar for i in range((end - start).days + 1)
    ):
        return Outcome(gaps=("calendar_not_covered",))
    state = _state(row)
    try:
        transition = apply_user_op(
            state, InstanceOp.RESUME, now=now, lifecycle=Lifecycle(version.lifecycle)
        )
    except AppError as exc:
        if exc.code != ErrorCode.STRATEGY_VERSION_NOT_RUNNABLE:
            raise
        from dataclasses import replace

        state = replace(state, paused_until=None, updated_at=now)
        _write(
            conn,
            row,
            state,
            "paused",
            {"expiry_blocked": "STRATEGY_VERSION_NOT_RUNNABLE", "lifecycle": version.lifecycle},
        )
        conn.execute(
            insert(notifications).values(
                user_id=owner,
                kind="system",
                severity="attention",
                title="策略实例到期恢复受阻",
                body="策略版本当前不可运行，实例保持暂停，可查看实例状态。",
                target_type="none",
                created_at=now,
                updated_at=now,
                merged_count=1,
                version=1,
            )
        )
        return Outcome(changed=True, blocked=True)
    if transition.changed:
        _write(conn, row, transition.state, "resumed", transition.event_detail or {})
        return Outcome(changed=True, resumed=True)
    return Outcome()
