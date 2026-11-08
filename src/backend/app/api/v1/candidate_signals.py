# ruff: noqa: ANN401
"""Owned immutable candidate bodies, event history and explicit user state actions."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Connection, and_, insert, or_, select, text, update

from app.api.v1.trades import normalize_code
from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.common.errors import AppError, ErrorCode
from app.common.pagination import PageParams, build_page, decode_cursor, page_params
from app.db.tables.market import securities
from app.db.tables.realtime import suggestions
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
    plan_drafts,
    reason_status_events,
)
from app.db.tables.strategy import strategies, strategy_versions
from app.schemas.enums import CandidateSignalState, Horizon, ReasonCode
from app.signals.models import SignalInput
from app.signals.service import TERMINAL, owned_signal, transition

router = APIRouter(tags=["candidate-signals"])


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    note: str | None = Field(max_length=200)


class Release(Note):
    confirm: Literal[True]


def scoped_page(
    query: Any,
    *,
    table: Any,
    time: Any,
    params: PageParams,
    scope: str,
    settings: Any,
    conn: Connection,
) -> tuple[list[Any], Any]:
    if params.cursor:
        keys = decode_cursor(params.cursor, scope=scope, settings=settings)
        try:
            stamp = dt.datetime.fromisoformat(str(keys[0]))
            identifier = uuid.UUID(str(keys[1]))
            if len(keys) != 2 or stamp.tzinfo is None:
                raise ValueError
        except (ValueError, IndexError):
            raise AppError(ErrorCode.INVALID_CURSOR) from None
        query = query.where(or_(time < stamp, and_(time == stamp, table.c.id < identifier)))
    rows = conn.execute(
        query.order_by(time.desc(), table.c.id.desc()).limit(params.limit + 1)
    ).all()
    page = build_page(
        rows,
        limit=params.limit,
        scope=scope,
        settings=settings,
        key=lambda row: [getattr(row, time.name).isoformat(), str(row.id)],
    )
    return list(rows[: params.limit]), page.next_cursor


def signal_out(conn: Connection, row: Any) -> dict[str, Any]:
    version = conn.execute(
        select(strategy_versions).where(strategy_versions.c.id == row.strategy_version_id)
    ).one()
    strategy = conn.execute(select(strategies).where(strategies.c.id == version.strategy_id)).one()
    name = conn.execute(
        select(securities.c.name).where(securities.c.code == row.security_code)
    ).scalar_one_or_none()
    snapshot = conn.execute(
        select(data_snapshots.c["items"]).where(
            data_snapshots.c.id == row.snapshot_id, data_snapshots.c.user_id == row.user_id
        )
    ).scalar_one_or_none()
    block = snapshot.get("data_status_block") if snapshot else None
    if not isinstance(block, dict) or set(block) != {"data_status", "data_as_of", "gaps"}:
        raise AppError(ErrorCode.MAINTENANCE, details={"issue": "signal_snapshot_status_missing"})
    fields = [
        "id",
        "instance_id",
        "strategy_version_id",
        "security_code",
        "horizon",
        "state",
        "proposed_action",
        "t_leg",
        "score",
        "stops",
        "rule_refs",
        "evidence",
        "counter_evidence",
        "invalidation",
        "model_refs",
        "risk_flags",
        "gate_results",
        "valid_until",
        "snapshot_id",
        "feature_set_version",
        "created_at",
    ]
    body = {key: getattr(row, key) for key in fields}
    if any(not body[key] for key in ["rule_refs", "evidence", "counter_evidence", "invalidation"]):
        raise AppError(ErrorCode.SIGNAL_NOT_EXPLAINABLE)
    # RiskGateDetail is deliberately not a candidate table column. Recover it
    # from the same immutable, owner-bound evaluation snapshot used on write.
    # Legacy snapshots may omit this optional list; malformed supplied details
    # still fail the normal P1/evidence-reference validation below.
    saved_input = snapshot.get("signal_input", {}) if snapshot else {}
    if not isinstance(saved_input, dict):
        raise AppError(ErrorCode.SIGNAL_NOT_EXPLAINABLE)
    risk_details = saved_input.get("risk_details", [])
    try:
        SignalInput.model_validate(
            {
                key: (
                    {
                        **body,
                        **block,
                        "risk_details": risk_details,
                        "confidence": {"level": row.confidence_level, "value": row.confidence},
                    }
                )[key]
                for key in SignalInput.model_fields
            }
        )
    except (ValidationError, KeyError):
        raise AppError(ErrorCode.SIGNAL_NOT_EXPLAINABLE) from None
    if row.instance_id is None:
        raise AppError(ErrorCode.MAINTENANCE, details={"issue": "legacy_signal_instance_missing"})
    return {
        **body,
        "strategy_key": strategy.key,
        "strategy_name": strategy.name,
        "lifecycle": version.lifecycle,
        "name": name or row.security_code,
        "confidence": {
            "level": row.confidence_level,
            "value": float(
                Decimal(row.confidence).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            ),
        },
        "reason_ids": conn.execute(
            select(reasons.c.id)
            .where(reasons.c.signal_id == row.id, reasons.c.user_id == row.user_id)
            .order_by(reasons.c.id)
        )
        .scalars()
        .all(),
        "plan_draft_ids": conn.execute(
            select(plan_drafts.c.id)
            .where(plan_drafts.c.user_id == row.user_id, plan_drafts.c.signal_ids.any(row.id))
            .order_by(plan_drafts.c.id)
        )
        .scalars()
        .all(),
        **block,
    }


def reason_out(row: Any) -> dict[str, Any]:
    keys = [
        "id",
        "signal_id",
        "code",
        "description",
        "evidence",
        "release_condition",
        "status",
        "detected_at",
        "released_at",
        "release_evidence",
    ]
    return {
        **{key: getattr(row, key) for key in keys},
        "security_code": row.security_code,
        "name": row.name or row.security_code,
        "released_by": "system" if row.released_by in {None, "system"} else "user",
    }


def reason_query(user_id: uuid.UUID) -> Any:
    return (
        select(reasons, securities.c.name, signals.c.security_code)
        .select_from(
            reasons.join(
                signals,
                and_(signals.c.id == reasons.c.signal_id, signals.c.user_id == reasons.c.user_id),
            ).outerjoin(securities, securities.c.code == signals.c.security_code)
        )
        .where(reasons.c.user_id == user_id, signals.c.user_id == user_id)
    )


@router.get("/candidate-signals")
def list_signals(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    state: CandidateSignalState | None = None,
    security_code: str | None = None,
    instance_id: uuid.UUID | None = None,
    horizon: Horizon | None = None,
) -> dict[str, Any]:
    with engine.connect() as conn:
        normalized = normalize_code(conn, security_code) if security_code else None
    filters = {
        "state": state,
        "security_code": normalized,
        "instance_id": str(instance_id) if instance_id else None,
        "horizon": horizon,
    }
    scope = (
        "candidate-signals:"
        + str(auth.user_id)
        + ":"
        + hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()
    )
    query = select(signals).where(signals.c.user_id == auth.user_id)
    for key, value in filters.items():
        if value is not None:
            query = query.where(signals.c[key] == value)
    with engine.connect() as conn:
        rows, cursor = scoped_page(
            query,
            table=signals,
            time=signals.c.created_at,
            params=page,
            scope=scope,
            settings=settings,
            conn=conn,
        )
        return {"items": [signal_out(conn, row) for row in rows], "next_cursor": cursor}


@router.get("/candidate-signals/{signal_id}")
def get_signal(signal_id: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return signal_out(conn, owned_signal(conn, auth.user_id, signal_id))


@router.get("/candidate-signals/{signal_id}/events")
def signal_events(
    signal_id: uuid.UUID,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
) -> dict[str, Any]:
    with engine.connect() as conn:
        owned_signal(conn, auth.user_id, signal_id)
        rows, cursor = scoped_page(
            select(events).where(events.c.signal_id == signal_id),
            table=events,
            time=events.c.at,
            params=page,
            scope=f"candidate-events:{auth.user_id}:{signal_id}",
            settings=settings,
            conn=conn,
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "from": row.from_state,
                    "to": row.to_state,
                    "cause": row.cause,
                    "at": row.at,
                }
                for row in rows
            ],
            "next_cursor": cursor,
        }


@router.post("/candidate-signals/{signal_id}/dismiss")
def dismiss(signal_id: uuid.UUID, body: Note, auth: AuthDep, engine: EngineDep) -> dict[str, str]:
    with engine.begin() as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"),
            {"owner": str(auth.user_id)},
        )
        row = owned_signal(conn, auth.user_id, signal_id, lock=True)
        if row.state in TERMINAL and row.state != "dismissed":
            raise AppError(
                ErrorCode.INVALID_STATE_TRANSITION,
                details={"from": row.state, "to": "dismissed", "allowed": []},
            )
        transition(conn, row, "dismissed", "user", dt.datetime.now(dt.UTC), {"note": body.note})
    return {"state": "dismissed"}


@router.get("/non-executable-reasons")
def list_reasons(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    status: Literal["active", "released", "all"] = "active",
    signal_id: uuid.UUID | None = None,
    code: ReasonCode | None = None,
    released_since: dt.datetime | None = None,
    signal_ids: Annotated[str | None, Query(max_length=4000)] = None,
    suggestion_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    if released_since is not None and released_since.tzinfo is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, details={"field": "released_since"})
    ids = None
    if signal_ids is not None:
        try:
            values = signal_ids.split(",")
            if not 1 <= len(values) <= 100:
                raise ValueError
            ids = [uuid.UUID(value) for value in values]
        except ValueError:
            raise AppError(ErrorCode.VALIDATION_ERROR, details={"field": "signal_ids"}) from None
    with engine.connect() as conn:
        if suggestion_id is not None:
            suggestion = conn.execute(
                select(suggestions.c.candidate_signal_ids).where(
                    suggestions.c.id == suggestion_id, suggestions.c.user_id == auth.user_id
                )
            ).one_or_none()
            if suggestion is None:
                raise AppError(ErrorCode.NOT_FOUND)
            ids = (
                list(suggestion.candidate_signal_ids or [])
                if ids is None
                else list(set(ids) & set(suggestion.candidate_signal_ids or []))
            )
        query = reason_query(auth.user_id)
        if status != "all":
            query = query.where(reasons.c.status == status)
        if signal_id:
            query = query.where(reasons.c.signal_id == signal_id)
        if code:
            query = query.where(reasons.c.code == code)
        if ids is not None:
            query = query.where(reasons.c.signal_id.in_(ids))
        if released_since:
            query = query.where(reasons.c.released_at >= released_since)
        if signal_ids is not None or suggestion_id is not None:
            return {
                "items": [
                    reason_out(row)
                    for row in conn.execute(
                        query.order_by(reasons.c.detected_at.desc(), reasons.c.id.desc())
                    ).all()
                ]
            }
        scope = (
            "reasons:"
            + str(auth.user_id)
            + ":"
            + hashlib.sha256(
                json.dumps([status, str(signal_id), code, str(released_since)]).encode()
            ).hexdigest()
        )
        time = reasons.c.released_at if released_since else reasons.c.detected_at
        rows, cursor = scoped_page(
            query, table=reasons, time=time, params=page, scope=scope, settings=settings, conn=conn
        )
        return {"items": [reason_out(row) for row in rows], "next_cursor": cursor}


@router.get("/non-executable-reasons/{reason_id}")
def get_reason(reason_id: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            reason_query(auth.user_id).where(reasons.c.id == reason_id)
        ).one_or_none()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return reason_out(row)


@router.post("/non-executable-reasons/{reason_id}/release")
def release_reason(
    reason_id: uuid.UUID, body: Release, auth: AuthDep, engine: EngineDep
) -> dict[str, Any]:
    with engine.begin() as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"),
            {"owner": str(auth.user_id)},
        )
        row = conn.execute(
            select(reasons)
            .where(reasons.c.id == reason_id, reasons.c.user_id == auth.user_id)
            .with_for_update()
        ).one_or_none()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        signal = owned_signal(conn, auth.user_id, row.signal_id, lock=True)
        if row.machine_checkable:
            raise AppError(ErrorCode.REASON_NOT_MANUALLY_RELEASABLE)
        if signal.state in TERMINAL:
            raise AppError(
                ErrorCode.INVALID_STATE_TRANSITION,
                details={"from": signal.state, "to": "released", "allowed": []},
            )
        if row.status == "active":
            now = dt.datetime.now(dt.UTC)
            conn.execute(
                update(reasons)
                .where(reasons.c.id == reason_id)
                .values(
                    status="released",
                    released_at=now,
                    released_by=str(auth.user_id),
                    release_evidence={"confirm": body.confirm, "note": body.note},
                )
            )
            conn.execute(
                insert(reason_status_events).values(
                    id=uuid.uuid4(),
                    reason_id=reason_id,
                    from_status="active",
                    to_status="released",
                    at=now,
                    evaluated_value={"actor_id": str(auth.user_id)},
                )
            )
            if not conn.execute(
                select(reasons.c.id).where(
                    reasons.c.signal_id == signal.id,
                    reasons.c.user_id == auth.user_id,
                    reasons.c.status == "active",
                )
            ).first():
                transition(conn, signal, "released", "reason_released", now)
        result = conn.execute(reason_query(auth.user_id).where(reasons.c.id == reason_id)).one()
        return reason_out(result)
