"""Certificate/user-scoped intraday history; static research facts only."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page
from app.db.tables.realtime import signal_events
from app.intraday.events import owned, project
from app.notify.models import SignalEvent
from app.plans.api import Paging, page
from app.schemas.enums import SignalKind

router = APIRouter()


@router.get("/signals", response_model=Page[SignalEvent])
def listing(
    auth: AuthDep,
    engine: EngineDep,
    cfg: SettingsDep,
    pp: Paging,
    security_code: str = Query(min_length=9, max_length=9),
    kind: str | None = None,
    since: dt.datetime | None = None,
) -> dict:
    if since is not None and since.tzinfo is None:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, details={"field": "since", "issue": "timezone_required"}
        )
    if kind is not None and kind not in {k.value for k in SignalKind}:
        raise AppError(ErrorCode.VALIDATION_ERROR, details={"field": "kind", "issue": "invalid"})
    q = owned(auth.user_id).where(signal_events.c.security_code == security_code)
    if kind is not None:
        q = q.where(signal_events.c.detail["kind"].astext == kind)
    if since is not None:
        q = q.where(signal_events.c.created_at >= since)
    with engine.connect() as conn:
        result = page(
            conn,
            signal_events,
            q,
            pp,
            cfg,
            f"signals:{auth.user_id}:{security_code}:{kind}:{since}",
            signal_events.c.created_at,
        )
        return {
            "items": [project(conn, row) for row in result.items],
            "next_cursor": result.next_cursor,
        }
