"""T-B77 contract routes; T-A12 DB-only clock and earliest-owned-account selection."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Header, Response

from app.aggregates import models, service
from app.aggregates.calendar import market_clock
from app.auth.deps import AuthDep, EngineDep, SettingsDep

router = APIRouter(tags=["aggregates"])


def response(model: models.Model, match: str | None) -> Response:
    content = model.model_dump(mode="json")
    # server_time is volatile presentation metadata, not business-state identity.
    stable = {key: value for key, value in content.items() if key != "server_time"}
    tag = 'W/"' + hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest() + '"'
    headers = {"ETag": tag, "Cache-Control": "private, no-cache"}
    if match and any(candidate.strip() in {tag, tag[2:], "*"} for candidate in match.split(",")):
        return Response(status_code=304, headers=headers)
    return Response(
        json.dumps(content, ensure_ascii=False), media_type="application/json", headers=headers
    )


@router.get("/terminal", response_model=models.Terminal)
def terminal(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    scope: Literal["all", "watchlist", "holdings"] = "all",
    account_id: uuid.UUID | None = None,
    if_none_match: str | None = Header(default=None),
) -> Response:
    now = dt.datetime.now(dt.UTC)
    with engine.connect() as conn:
        identifier = service.select_account(conn, auth.user_id, account_id)
        value = service.terminal(
            conn,
            auth.user_id,
            identifier,
            market_clock(conn, now, settings.business.market_rules),
            now,
            scope,
        )
    return response(value, if_none_match)


@router.get("/today", response_model=models.Today)
def today(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    account_id: uuid.UUID | None = None,
    if_none_match: str | None = Header(default=None),
) -> Response:
    now = dt.datetime.now(dt.UTC)
    with engine.connect() as conn:
        identifier = service.select_account(conn, auth.user_id, account_id)
        value = service.today(
            conn,
            auth.user_id,
            identifier,
            market_clock(conn, now, settings.business.market_rules),
            now,
            # 持仓属 Tier-1，见 config/realtime.yaml tier1_priority；§3.7⑥ 过期阈值 = 采集间隔 × 2。
            interval_s=settings.business.realtime.intervals.pro_tier1_interval_s,
        )
    return response(value, if_none_match)


@router.get("/market/overview", response_model=models.MarketOverview)
def overview(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    with engine.connect() as conn:
        value = service.market(
            market_clock(conn, dt.datetime.now(dt.UTC), settings.business.market_rules)
        )
    return response(value, if_none_match)


@router.get("/reconciliation")
def reconciliation(
    auth: AuthDep, engine: EngineDep, account_id: uuid.UUID | None = None
) -> models.ReconciliationResult:
    from app.aggregates.reconciliation import read

    with engine.connect() as conn:
        identifier = service.select_account(conn, auth.user_id, account_id)
        result = read(conn, identifier, dt.datetime.now(dt.UTC))
    return models.ReconciliationResult.model_validate_json(
        json.dumps({key: result[key] for key in ["status", "as_of", "items"]}, default=str)
    )
