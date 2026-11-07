# ruff: noqa: ANN401
"""Owner-transactional candidate admission. No shared signal-event dependency or IO."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, func, insert, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.common.errors import AppError, ErrorCode
from app.config_files import MarketRulesConfig
from app.db.tables.accounts import accounts
from app.db.tables.licences import user_data_licences
from app.db.tables.market import securities, trading_calendar
from app.db.tables.research import action_plans, plan_versions, watchlist_items
from app.db.tables.reviews import data_snapshots
from app.db.tables.signals import (
    candidate_signal_events as events,
)
from app.db.tables.signals import (
    candidate_signals as signals,
)
from app.db.tables.signals import (
    non_executable_reasons as reasons,
)
from app.db.tables.signals import (
    reason_status_events,
    user_restrictions,
)
from app.db.tables.strategy import (
    strategy_card_versions,
)
from app.db.tables.strategy import (
    strategy_instances as instances,
)
from app.db.tables.strategy import (
    strategy_versions as versions,
)
from app.db.tables.users import users
from app.importing.pipeline import live_snapshots
from app.market_rules.lots import lot_spec
from app.schemas.enums import Action
from app.signals.admission import run_with_master_guard
from app.signals.execution import assess, condition
from app.signals.models import MarketFacts, SignalInput
from app.strategy.instances.service import owned

BJT = dt.timezone(dt.timedelta(hours=8))
TERMINAL = {"confirmed", "dismissed", "expired", "invalidated", "superseded"}


def owned_signal(
    conn: Connection, user_id: uuid.UUID, signal_id: uuid.UUID, *, lock: bool = False
) -> Any:
    query = select(signals).where(signals.c.id == signal_id, signals.c.user_id == user_id)
    if lock:
        query = query.with_for_update()
    row = conn.execute(query).one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def transition(
    conn: Connection,
    row: Any,
    target: str,
    cause: str,
    at: dt.datetime,
    detail: dict[str, Any] | None = None,
) -> None:
    if row.state == target:
        return
    conn.execute(
        update(signals)
        .where(signals.c.id == row.id, signals.c.created_at == row.created_at)
        .values(state=target, state_changed_at=at)
    )
    conn.execute(
        insert(events).values(
            id=uuid.uuid4(),
            signal_id=row.id,
            from_state=row.state,
            to_state=target,
            cause=cause,
            at=at,
            detail=detail,
        )
    )


def calendar_state(
    conn: Connection, at: dt.datetime, rules: MarketRulesConfig
) -> tuple[bool, dt.datetime | None]:
    day = at.astimezone(BJT).date()
    current = conn.execute(
        select(trading_calendar).where(trading_calendar.c.date == day)
    ).one_or_none()
    if current is None:
        lo, hi = conn.execute(
            select(func.min(trading_calendar.c.date), func.max(trading_calendar.c.date))
        ).one()
        raise AppError(
            ErrorCode.CALENDAR_NOT_COVERED,
            details={
                "date": day.isoformat(),
                "coverage_start": lo.isoformat() if lo else None,
                "coverage_end": hi.isoformat() if hi else None,
            },
        )
    segment = rules.segment_for(day)
    if segment is None:
        raise ValueError("market_rule_segment_missing")
    periods = segment.sessions
    clock = at.astimezone(BJT).time().replace(tzinfo=None)
    trading = bool(
        current.is_open
        and (
            periods.morning[0] <= clock < periods.morning[1]
            or periods.afternoon[0] <= clock < periods.closing_auction[1]
        )
    )
    # Only exchange-seeded dates; no weekday/holiday inference.
    next_day = (
        day
        if current.is_open and clock < periods.morning[0]
        else conn.execute(
            select(trading_calendar.c.date)
            .where(trading_calendar.c.date > day, trading_calendar.c.is_open.is_(True))
            .order_by(trading_calendar.c.date)
            .limit(1)
        ).scalar_one_or_none()
    )
    next_open = dt.datetime.combine(next_day, periods.morning[0], BJT) if next_day else None
    if not trading and next_open is None:
        raise AppError(
            ErrorCode.CALENDAR_NOT_COVERED,
            details={"date": day.isoformat(), "issue": "next_session_missing"},
        )
    return trading, next_open


def add_reason(
    conn: Connection,
    *,
    signal_id: uuid.UUID,
    user_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    code: str,
    release: dict[str, Any],
    at: dt.datetime,
    evidence: list[dict[str, Any]],
    salt: str = "",
) -> uuid.UUID:
    identifier = uuid.uuid5(signal_id, code + salt)
    if conn.execute(select(reasons.c.id).where(reasons.c.id == identifier)).first():
        return identifier
    conn.execute(
        insert(reasons).values(
            id=identifier,
            signal_id=signal_id,
            user_id=user_id,
            code=code,
            description=release["human_text"],
            evidence=evidence,
            epistemic_type="hypothesis"
            if any(item["epistemic_type"] == "hypothesis" for item in evidence)
            else "fact",
            detected_at=at,
            snapshot_id=snapshot_id,
            release_condition=release,
            check_on=release["check_on"],
            machine_checkable=release["machine_checkable"],
            next_check_at=release["at"],
            status="active",
            released_by="system",
        )
    )
    conn.execute(
        insert(reason_status_events).values(
            id=uuid.uuid4(), reason_id=identifier, from_status=None, to_status="active", at=at
        )
    )
    return identifier


def snapshot_items(content: SignalInput, facts: MarketFacts) -> dict[str, Any]:
    """Opaque immutable input payload for the existing data_snapshots table.

    The trusted producer persists this under content.snapshot_id with the owner;
    values/evidence and execution facts remain traceable, not merely a status label.
    """
    return {
        "schema_version": "tb74-evaluated-v1",
        "signal_input": content.model_dump(mode="json"),
        "market_facts": facts.model_dump(mode="json"),
        "data_status_block": {
            "data_status": content.data_status.value,
            "data_as_of": content.data_as_of.isoformat(),
            "gaps": [gap.model_dump(mode="json") for gap in content.gaps],
        },
    }


def write_candidate(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    instance_id: uuid.UUID,
    content: SignalInput,
    facts: MarketFacts,
    market_rules: MarketRulesConfig,
) -> dict[str, Any]:
    """Trusted producer input, never a public user-authored signal. Caller owns transaction."""
    if (
        conn.execute(select(users.c.status).where(users.c.id == user_id)).scalar_one_or_none()
        != "approved"
    ):
        return {"id": None, "diagnostic": "user_not_approved"}
    if content.proposed_action in {"hold", "wait"}:
        return {"id": None, "diagnostic": "no_candidate_action"}
    # Shared owner lock serializes opposite strategies as well as snapshot replays.
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"), {"owner": str(user_id)}
    )
    instance = owned(conn, user_id, instance_id, lock=True)
    if instance.status != "active":
        return {"id": None, "diagnostic": "instance_not_active"}
    actual = instance.derived_strategy_version_id or instance.strategy_version_id
    version = conn.execute(select(versions).where(versions.c.id == actual)).one()
    from app.db.tables.strategy import strategies

    template_owner = conn.execute(
        select(strategies.c.owner_user_id).where(strategies.c.id == version.strategy_id)
    ).scalar_one()
    if template_owner is not None and template_owner != user_id:
        raise AppError(ErrorCode.NOT_FOUND)
    from app.strategy.runtime import runnable

    role = conn.execute(select(users.c.role).where(users.c.id == user_id)).scalar_one()
    if not runnable(version.lifecycle, role):
        return {"id": None, "diagnostic": "version_not_runnable"}
    declared_rules = {
        rule["id"]: rule for rule in version.config.get("spec", version.config).get("rules", [])
    }
    if not declared_rules:
        return {"id": None, "diagnostic": "version_rules_not_defined"}
    for reference in content.rule_refs:
        declared = declared_rules.get(reference.rule_id)
        if (
            declared is None
            or declared.get("role") != reference.role
            or declared.get("dimension") != reference.dimension
            or declared.get("expr") != reference.threshold
        ):
            raise AppError(ErrorCode.SIGNAL_NOT_EXPLAINABLE)
    if instance.scope == "watch_group":
        return {"id": None, "diagnostic": "scope_deferred"}
    if instance.scope == "security" and instance.security_code != content.security_code:
        return {"id": None, "diagnostic": "scope_mismatch"}
    account = conn.execute(
        select(accounts)
        .where(
            accounts.c.id == instance.account_id,
            accounts.c.user_id == user_id,
            accounts.c.archived_at.is_(None),
        )
        .with_for_update()
    ).one_or_none()
    if account is None:
        raise AppError(ErrorCode.NOT_FOUND)
    snapshot = conn.execute(
        select(data_snapshots).where(
            data_snapshots.c.id == content.snapshot_id, data_snapshots.c.user_id == user_id
        )
    ).one_or_none()
    if snapshot is None:
        raise AppError(ErrorCode.NOT_FOUND)
    if (
        snapshot.licence_id is not None
        and not conn.execute(
            select(user_data_licences.c.id).where(
                user_data_licences.c.id == snapshot.licence_id,
                user_data_licences.c.user_id == user_id,
            )
        ).first()
    ):
        raise AppError(ErrorCode.NOT_FOUND)
    if snapshot.created_at > content.created_at:
        raise ValueError("future_snapshot")
    day = content.created_at.astimezone(BJT).date()
    from app.api.v1.portfolio import _account

    portfolio = _account(conn, account.id, day)
    position = portfolio.positions.get(content.security_code)
    qty = position.qty if position else Decimal(0)
    sellable = position.sellable if position else Decimal(0)
    watched = bool(
        conn.execute(
            select(watchlist_items.c.id).where(
                watchlist_items.c.user_id == user_id,
                watchlist_items.c.security_code == content.security_code,
                watchlist_items.c.removed_at.is_(None),
            )
        ).first()
    )
    fields = (
        conn.execute(
            select(strategy_card_versions.c.fields).where(
                strategy_card_versions.c.id == version.card_version_id
            )
        ).scalar_one_or_none()
        if version.card_version_id
        else None
    )
    universe = (fields or {}).get("universe", version.config.get("universe"))
    if not universe or set(universe) - {"boards", "pool", "security_types"}:
        return {"id": None, "diagnostic": "universe_not_defined_or_supported"}
    pool = universe.get("pool")
    if pool not in {"持仓", "持仓 ∪ 自选"}:
        return {"id": None, "diagnostic": "universe_pool_not_supported"}
    if not qty and (pool == "持仓" or not watched):
        return {"id": None, "diagnostic": "outside_universe"}
    identity = f"{user_id}:{instance_id}:{actual}:{content.snapshot_id}:{content.security_code}"
    key = hashlib.sha256(identity.encode()).hexdigest()
    existing = conn.execute(
        select(signals.c.id).where(
            signals.c.user_id == user_id,
            signals.c.instance_id == instance_id,
            signals.c.cooldown_key == key,
        )
    ).scalar_one_or_none()
    if existing:
        return {"id": str(existing), "diagnostic": "snapshot_already_evaluated"}

    def persist(locked: Connection) -> dict[str, Any]:
        master = locked.execute(
            select(securities).where(securities.c.code == content.security_code)
        ).one()
        if master.type not in universe.get("security_types", []) or not universe.get(
            "boards", {}
        ).get(master.board, False):
            return {"id": None, "diagnostic": "outside_universe"}
        if (fields or {}).get(
            "mount_policy", version.config.get("mount_policy")
        ) == "system_only" and content.proposed_action not in {"reduce", "sell"}:
            return {"id": None, "diagnostic": "system_exit_only"}
        segment = market_rules.segment_for(day)
        if segment is None:
            raise ValueError("market_rule_segment_missing")
        lot = lot_spec(segment, board=master.board, security_type=master.type)
        snap = locked.execute(
            live_snapshots(account.id).order_by(text("version_no DESC")).limit(1)
        ).one_or_none()
        cash = snap.cash_available if snap and snap.cash_available is not None else portfolio.cash
        trading, next_open = calendar_state(locked, content.created_at, market_rules)
        blockers = assess(
            content,
            facts,
            qty=qty,
            sellable=sellable,
            cash=cash,
            min_buy=lot.min_buy,
            min_sell=lot.min_buy,
            risk_flag=master.risk_flag,
            trading=trading,
            next_open=next_open,
        )
        for flag in content.risk_flags:
            if content.proposed_action not in flag.gated_actions:
                continue
            code = {
                "position_cap": "POSITION_CAP_REACHED",
                "total_exposure": "REGIME_MISMATCH",
                "sector_concentration": "SECTOR_EXPOSURE_EXCEEDED",
                "loss_streak_drawdown": "LOSS_STREAK_PAUSE",
            }.get(flag.control)
            if code is None:
                return {"id": None, "diagnostic": "risk_hook_mapping_not_defined"}
            blockers.append({"code": code, "release_condition": condition(code)})
        for restriction in locked.execute(
            select(user_restrictions).where(
                user_restrictions.c.user_id == user_id,
                user_restrictions.c.target_id.in_(
                    [content.security_code, str(instance_id), str(version.strategy_id)]
                ),
            )
        ):
            if restriction.until is not None and restriction.until <= content.created_at:
                continue
            code = {"blocklist": "BLOCKLISTED", "mute": "USER_MUTED", "cooling_off": "COOLING_OFF"}[
                restriction.kind
            ]
            blockers.append(
                {"code": code, "release_condition": condition(code, at=restriction.until)}
            )
        plans = (
            locked.execute(
                select(plan_versions.c.action)
                .select_from(
                    action_plans.join(
                        plan_versions, action_plans.c.current_version_id == plan_versions.c.id
                    )
                )
                .where(
                    action_plans.c.user_id == user_id,
                    action_plans.c.security_code == content.security_code,
                    action_plans.c.status.in_(["active", "triggered"]),
                )
            )
            .scalars()
            .all()
        )
        buy = content.proposed_action in {"buy", "add"}
        for action in plans:
            same = (action in {"buy", "add"}) == buy
            code = "SAME_DIRECTION_PLAN_EXISTS" if same else "CONFLICTS_CONFIRMED_PLAN"
            blockers.append(
                {
                    "code": code,
                    "release_condition": {
                        "kind": "event" if same else "user_action",
                        "expr": None,
                        "at": None,
                        "event": "plan.closed" if same else None,
                        "action": None if same else "modify_or_close_plan",
                        "check_on": ["plan_change"] if same else ["user_action"],
                        "human_text": "该计划进入终止状态"
                        if same
                        else "用户修改或关闭相反方向计划",
                        "machine_checkable": same,
                    },
                }
            )
        identifier = uuid.uuid5(uuid.NAMESPACE_URL, "tb74:" + identity)
        body = content.model_dump(mode="json")
        for name in ["data_status", "data_as_of", "gaps", "snapshot_id", "created_at"]:
            body.pop(name)
        body["confidence_level"] = body["confidence"]["level"]
        body["confidence"] = body["confidence"]["value"]
        # DataStatusBlock stays with the immutable owned input snapshot; no schema invention.
        status_block = (
            snapshot.items.get("data_status_block") if isinstance(snapshot.items, dict) else None
        )
        expected = {
            "data_status": content.data_status.value,
            "data_as_of": content.data_as_of.isoformat(),
            "gaps": [gap.model_dump(mode="json") for gap in content.gaps],
        }
        if snapshot.items.get("signal_input") != content.model_dump(
            mode="json"
        ) or snapshot.items.get("market_facts") != facts.model_dump(mode="json"):
            raise ValueError("snapshot_evaluation_or_market_facts_mismatch")
        if status_block != expected:
            raise ValueError("snapshot_data_status_block_missing_or_mismatch")
        opposites = locked.execute(
            select(signals)
            .where(
                signals.c.user_id == user_id,
                signals.c.security_code == content.security_code,
                signals.c.instance_id != instance_id,
                signals.c.state.in_(["open", "blocked", "released", "drafted"]),
                signals.c.proposed_action.in_(["reduce", "sell"] if buy else ["buy", "add"]),
            )
            .with_for_update()
        ).all()
        conflict = {
            "kind": "user_action",
            "expr": None,
            "at": None,
            "event": None,
            "action": "choose_strategy",
            "check_on": ["user_action", "tick"],
            "human_text": "用户选择采用某一方或重评后冲突消失",
            "machine_checkable": False,
        }
        if opposites:
            blockers.append({"code": "STRATEGY_CONFLICT", "release_condition": conflict})
        state = "blocked" if blockers else "open"
        locked.execute(
            insert(signals).values(
                **body,
                id=identifier,
                user_id=user_id,
                instance_id=instance_id,
                strategy_version_id=actual,
                horizon=instance.horizon,
                snapshot_id=content.snapshot_id,
                created_at=content.created_at,
                state=state,
                state_changed_at=content.created_at,
                cooldown_key=key,
                gate_results=[
                    {
                        "gate": "gate_tradability",
                        "passed": not any(
                            b["code"]
                            in {"SUSPENDED", "ST_OR_DELISTING", "NEW_LISTING", "LIMIT_LOCKED"}
                            for b in blockers
                        ),
                    }
                ],
            )
        )
        locked.execute(
            insert(events).values(
                id=uuid.uuid4(),
                signal_id=identifier,
                from_state=None,
                to_state=state,
                cause="executability_check",
                at=content.created_at,
            )
        )

        def conflict_evidence(peer_id: uuid.UUID) -> list[dict[str, Any]]:
            return [
                {
                    "id": "conflict-" + str(peer_id),
                    "key": "signal.conflict_signal_id",
                    "value": str(peer_id),
                    "unit": None,
                    "provider": "system",
                    "endpoint": None,
                    "epistemic_type": "fact",
                    "data_as_of": content.created_at.isoformat(),
                    "fetched_at": content.created_at.isoformat(),
                }
            ]

        for peer in opposites:
            add_reason(
                locked,
                signal_id=peer.id,
                user_id=user_id,
                snapshot_id=peer.snapshot_id,
                code="STRATEGY_CONFLICT",
                release=conflict,
                at=content.created_at,
                evidence=conflict_evidence(identifier),
                salt=str(identifier),
            )
            transition(locked, peer, "blocked", "executability_check", content.created_at)
        for blocker in blockers:
            add_reason(
                locked,
                signal_id=identifier,
                user_id=user_id,
                snapshot_id=content.snapshot_id,
                code=blocker["code"],
                release=blocker["release_condition"],
                at=content.created_at,
                evidence=(
                    [item for peer in opposites for item in conflict_evidence(peer.id)]
                    if blocker["code"] == "STRATEGY_CONFLICT"
                    else content.model_dump(mode="json")["evidence"]
                ),
            )
        return {"id": str(identifier), "diagnostic": state}

    admission, result = run_with_master_guard(
        conn,
        security_code=content.security_code,
        action=Action(content.proposed_action),
        trade_date=day,
        operation=persist,
    )
    return result if result is not None else {"id": None, "diagnostic": admission.diagnostic}


def post_close_for_user(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    produce: Callable[[Any], list[tuple[SignalInput, MarketFacts]]],
    market_rules: MarketRulesConfig,
) -> list[dict[str, Any]]:
    """Direct owner branch. Supplied producer must be deterministic T-B72 + output assembler.

    This is not Celery/signal-rt registration and never consumes shared market events.
    Individual instances use savepoints; caller decides transaction/retry policy.
    """
    result = []
    for instance in conn.execute(
        select(instances)
        .where(instances.c.user_id == user_id, instances.c.status == "active")
        .order_by(instances.c.id)
    ).all():
        try:
            instance_result = []
            with conn.begin_nested():
                for content, facts in produce(instance):
                    instance_result.append(
                        write_candidate(
                            conn,
                            user_id=user_id,
                            instance_id=instance.id,
                            content=content,
                            facts=facts,
                            market_rules=market_rules,
                        )
                    )
            result.extend(instance_result)
        except (AppError, ValueError, SQLAlchemyError) as error:
            result.append(
                {
                    "id": None,
                    "instance_id": str(instance.id),
                    "diagnostic": "instance_failed",
                    "error_type": type(error).__name__,
                }
            )
    return result
