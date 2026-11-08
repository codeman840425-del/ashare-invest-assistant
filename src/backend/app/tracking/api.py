from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Response
from sqlalchemy import or_, select

from app.auth.deps import AuthDep, EngineDep
from app.common.errors import AppError, ErrorCode
from app.db.tables.realtime import suggestion_tracking, suggestions
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import strategies, strategy_versions
from app.tracking.models import Result, SuggestionTracking
from app.tracking.service import SCHEMA, digest, profit_loss, stat, view

router = APIRouter(tags=["tracking"])


@router.get("/suggestions/{identifier}/tracking", response_model=SuggestionTracking)
def suggestion_tracking_view(
    identifier: uuid.UUID, auth: AuthDep, engine: EngineDep, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    with engine.connect() as conn:
        return view(conn, auth.user_id, identifier)


@router.get("/strategies/{strategy_id}/versions/{version_id}/tracking")
def strategy_tracking_view(
    strategy_id: uuid.UUID,
    version_id: uuid.UUID,
    auth: AuthDep,
    engine: EngineDep,
    response: Response,
    scope: Literal["mine", "site"] = "mine",
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    with engine.connect() as conn:
        version = conn.execute(
            select(strategy_versions.c.id)
            .join(strategies, strategies.c.id == strategy_versions.c.strategy_id)
            .where(
                strategy_versions.c.id == version_id,
                strategy_versions.c.strategy_id == strategy_id,
                or_(
                    strategies.c.owner_user_id.is_(None), strategies.c.owner_user_id == auth.user_id
                ),
            )
        ).first()
        if version is None:
            raise AppError(ErrorCode.NOT_FOUND)
        query = (
            select(
                data_snapshots, suggestion_tracking.c.suggestion_id.label("tracking_suggestion_id")
            )
            .join(suggestion_tracking, suggestion_tracking.c.snapshot_id == data_snapshots.c.id)
            .join(suggestions, suggestions.c.id == suggestion_tracking.c.suggestion_id)
            .where(data_snapshots.c.user_id == suggestions.c.user_id)
        )
        if scope == "mine":
            query = query.where(suggestions.c.user_id == auth.user_id)
        rows = conn.execute(
            query.order_by(
                suggestions.c.created_at, suggestions.c.id, suggestion_tracking.c.horizon_days
            )
        ).all()
        results: list[Result] = []
        stamps = []
        seen: set[tuple[uuid.UUID, uuid.UUID, int]] = set()
        for row in rows:
            body = row._mapping["items"]
            if body.get("schema_version") != SCHEMA:
                continue
            if digest(body) != row.hash:
                raise ValueError("tracking_aggregate_snapshot_hash_conflict")
            selected = [
                Result.model_validate(v)
                for v in body["results"]
                if v["strategy_version_id"] == str(version_id)
            ]
            if selected:
                for result in selected:
                    key = (
                        row.tracking_suggestion_id,
                        result.strategy_version_id,
                        result.horizon_days,
                    )
                    if key not in seen:
                        seen.add(key)
                        results.append(result)
                stamps.append(dt.datetime.fromisoformat(body["as_of"]))
    by_horizon = []
    gaps = {}
    for period in [1, 5, 20]:
        subset = [r for r in results if r.horizon_days == period]
        complete = [r for r in subset if r.state == "complete"]
        window = str(period) + " trading days"
        # No action-dependent inversion of observed interval returns.
        returns = [r.return_pct for r in complete if r.return_pct is not None]
        decisions = [
            Decimal(int(r.direction_correct)) for r in complete if r.direction_correct is not None
        ]
        excess = [r.excess_pct for r in complete if r.excess_pct is not None]
        ratio, ratio_gaps = profit_loss(subset, window)
        for missing in ratio_gaps:
            gaps[missing.key] = missing
        streak = longest = 0
        for result in complete:
            if result.return_pct is not None:
                streak = streak + 1 if result.return_pct < 0 else 0
                longest = max(longest, streak)
        by_horizon.append(
            {
                "horizon_days": period,
                "win_rate": stat(decisions, window).model_dump(mode="json"),
                "avg_return_pct": stat(returns, window).model_dump(mode="json"),
                "avg_excess_pct": stat(excess, window).model_dump(mode="json"),
                "profit_loss_ratio": ratio.model_dump(mode="json"),
                "max_loss_streak": longest,
                "pending_count": sum(r.state == "pending" for r in subset),
                "untradable_count": sum(r.state == "untradable" for r in subset),
                "excluded_count": sum(r.state == "excluded" for r in subset),
            }
        )
    # Only anonymous aggregate numbers, never results/identities/security codes.
    return {
        "scope": scope,
        "by_horizon": by_horizon,
        "data_status": "partial" if results else "unavailable",
        "data_as_of": max(stamps, default=None),
        "gaps": [g.model_dump(mode="json") for g in gaps.values()],
    }
