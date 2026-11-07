"""T-B77 contract routes; the reviewed market-clock adapter is intentionally not faked."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Header, Request, Response

from app.aggregates import models, service
from app.auth.deps import AuthDep, EngineDep

router = APIRouter(tags=["aggregates"])


def clock(request: Request) -> models.MarketClock:
    provider = getattr(request.app.state, "aggregate_clock", None)
    if provider is None:
        raise service.unavailable("reviewed_market_clock_adapter_pending")
    value = provider()
    if not isinstance(value, models.MarketClock):
        raise service.unavailable("invalid_market_clock_adapter")
    return value


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
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    scope: Literal["all", "watchlist", "holdings"] = "all",
    account_id: uuid.UUID | None = None,
    if_none_match: str | None = Header(default=None),
) -> Response:
    with engine.connect() as conn:
        identifier = service.select_account(conn, auth.user_id, account_id)
        value = service.terminal(
            conn, auth.user_id, identifier, clock(request), dt.datetime.now(dt.UTC), scope
        )
    return response(value, if_none_match)


@router.get("/today", response_model=models.Today)
def today(
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    with engine.connect() as conn:
        identifier = service.select_account(conn, auth.user_id, None)
        value = service.today(
            conn, auth.user_id, identifier, clock(request), dt.datetime.now(dt.UTC)
        )
    return response(value, if_none_match)


@router.get("/market/overview", response_model=models.MarketOverview)
def overview(
    request: Request, auth: AuthDep, if_none_match: str | None = Header(default=None)
) -> Response:
    return response(service.market(clock(request)), if_none_match)
