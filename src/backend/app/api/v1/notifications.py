"""Owned notification facts, preferences and SSE transport (§7.11.4)."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.auth.deps import AuthDep, EngineDep, RedisDep, SettingsDep, StoreDep, load_user
from app.auth.sessions import SESSION_COOKIE
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page
from app.db.tables.notify import notifications
from app.db.tables.realtime import user_realtime_prefs
from app.notify.models import Notification
from app.notify.service import project
from app.notify.transport import flush, replay, reset_reason
from app.plans.api import Paging, page

router = APIRouter(tags=["notifications"])


class UnreadCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(strict=True, ge=0)


# Register static routes before any future /notifications/{id} route.
@router.get("/notifications/unread-count")
def unread_count(auth: AuthDep, engine: EngineDep, response: Response) -> UnreadCount:
    response.headers["Cache-Control"] = "private, no-store"
    with engine.connect() as conn:
        count = conn.execute(
            select(func.count())
            .select_from(notifications)
            .where(
                notifications.c.user_id == auth.user_id,
                notifications.c.read_at.is_(None),
            )
        ).scalar_one()
    return UnreadCount(count=int(count))


# P2N-06: all projections use persisted owned facts, never caller-supplied owners.


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    intraday_cadence: Literal["realtime", "1min", "3min", "5min"]


@router.get("/notification-preferences", response_model=Preferences)
def preferences(auth: AuthDep, engine: EngineDep) -> Preferences:
    with engine.connect() as conn:
        value = (
            conn.execute(
                select(user_realtime_prefs.c.notify_cadence).where(
                    user_realtime_prefs.c.user_id == auth.user_id
                )
            ).scalar_one_or_none()
            or "1m"
        )
    return Preferences.model_validate(
        {"intraday_cadence": value.replace("m", "min") if value != "realtime" else value}
    )


@router.put("/notification-preferences", response_model=Preferences)
def set_preferences(body: Preferences, auth: AuthDep, engine: EngineDep) -> Preferences:
    value = body.intraday_cadence.replace("min", "m")
    with engine.begin() as conn:
        statement = insert(user_realtime_prefs).values(user_id=auth.user_id, notify_cadence=value)
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id"],
                set_={"notify_cadence": value, "updated_at": dt.datetime.now(dt.UTC)},
            )
        )
    return body


@router.get("/notifications", response_model=Page[Notification])
def listing(
    auth: AuthDep,
    engine: EngineDep,
    cfg: SettingsDep,
    pp: Paging,
    unread: bool | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    from app.schemas.enums import NotificationKind

    if kind is not None and kind not in {x.value for x in NotificationKind}:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, details={"fields": [{"field": "kind", "issue": "invalid"}]}
        )
    query = select(notifications).where(notifications.c.user_id == auth.user_id)
    if unread is not None:
        query = query.where(
            notifications.c.read_at.is_(None) if unread else notifications.c.read_at.is_not(None)
        )
    if kind is not None:
        query = query.where(notifications.c.kind == kind)
    with engine.connect() as conn:
        result = page(
            conn,
            notifications,
            query,
            pp,
            cfg,
            f"notifications:{auth.user_id}:{unread}:{kind}",
            notifications.c.created_at,
        )
        return {
            "items": [project(conn, row) for row in result.items],
            "next_cursor": result.next_cursor,
        }


@router.post("/notifications/read-all", status_code=204)
def read_all(auth: AuthDep, engine: EngineDep) -> Response:
    with engine.begin() as conn:
        conn.execute(
            update(notifications)
            .where(notifications.c.user_id == auth.user_id, notifications.c.read_at.is_(None))
            .values(read_at=dt.datetime.now(dt.UTC), version=notifications.c.version + 1)
        )
    return Response(status_code=204)


@router.post("/notifications/{identifier}/read", status_code=204)
def read_one(identifier: uuid.UUID, auth: AuthDep, engine: EngineDep) -> Response:
    with engine.begin() as conn:
        row = conn.execute(
            select(notifications.c.id).where(
                notifications.c.id == identifier, notifications.c.user_id == auth.user_id
            )
        ).first()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        conn.execute(
            update(notifications)
            .where(
                notifications.c.id == identifier,
                notifications.c.user_id == auth.user_id,
                notifications.c.read_at.is_(None),
            )
            .values(read_at=dt.datetime.now(dt.UTC), version=notifications.c.version + 1)
        )
    return Response(status_code=204)


def sse_message(identifier: str, kind: str, data: dict[str, Any]) -> str:
    return (
        f"id: {identifier}\nevent: {kind}\ndata: "
        + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        + "\n\n"
    )


@router.get("/stream")
async def stream(
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    rds: RedisDep,
    store: StoreDep,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    def live() -> bool:
        session = store.get(request.cookies.get(SESSION_COOKIE))
        user = load_user(engine, str(auth.user_id))
        return bool(
            session is not None
            and session.user_id == str(auth.user_id)
            and user is not None
            and user.status == "approved"
        )

    async def generate() -> AsyncIterator[str]:
        if not live():
            return
        now = dt.datetime.now(dt.UTC)
        raw_cursor = rds.get("p2n06:sse:" + str(auth.user_id) + ":seq") or b"0"
        cursor = raw_cursor.decode() if isinstance(raw_cursor, bytes) else str(raw_cursor)
        if not live():
            return
        yield "retry: 3000\n\n"
        reason = reset_reason(rds, auth.user_id, last_event_id, now, cursor)
        if reason:
            if not live():
                return
            yield (
                "event: reset\ndata: "
                + json.dumps(
                    {"reason": reason, "latest_event_id": cursor if cursor != "0" else None}
                )
                + "\n\n"
            )
        initial = [] if reason else replay(rds, auth.user_id, last_event_id, now)
        for event in initial:
            if not live():
                return
            cursor = str(max(int(cursor), int(event["id"])))
            yield sse_message(event["id"], event["event"], event["data"])
        last_heartbeat = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=15)
        while not await request.is_disconnected():
            if not live():
                return
            now = dt.datetime.now(dt.UTC)
            flush(engine, rds, now)
            for event in replay(rds, auth.user_id, cursor, now, require_anchor=False):
                if not live():
                    return
                cursor = event["id"]
                yield sse_message(cursor, event["event"], event["data"])
            if (now - last_heartbeat).total_seconds() >= 15:
                if not live():
                    return
                yield "event: heartbeat\ndata: " + json.dumps({"at": now.isoformat()}) + "\n\n"
                last_heartbeat = now
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
