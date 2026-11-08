"""600s owned SSE buffer and disposable cadence queue; no external channels."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any

import redis
from sqlalchemy import Engine, select

from app.db.tables.notify import notifications
from app.db.tables.realtime import user_realtime_prefs
from app.notify.service import TZ, project

PUBLISH = """
if ARGV[5] ~= '' and redis.call('SET', KEYS[4], '1', 'NX', 'EX', 600) == false then return '' end
local id=tostring(redis.call('INCR',KEYS[1]))
redis.call('ZADD',KEYS[2],ARGV[1],id)
redis.call('HSET',KEYS[3],id,ARGV[2])
local old=redis.call('ZRANGEBYSCORE',KEYS[2],'-inf','('..ARGV[3])
for _,k in ipairs(old) do redis.call('HDEL',KEYS[3],k) end
redis.call('ZREMRANGEBYSCORE',KEYS[2],'-inf','('..ARGV[3])
redis.call('EXPIRE',KEYS[2],600);redis.call('EXPIRE',KEYS[3],600)
return id
"""
CLAIM = """
local v=redis.call('ZRANGEBYSCORE',KEYS[1],'-inf',ARGV[1],'LIMIT',0,100)
for _,id in ipairs(v) do redis.call('ZREM',KEYS[1],id) end
return v
"""


def publish(
    r: redis.Redis,
    owner: uuid.UUID,
    kind: str,
    data: dict[str, Any],
    at: dt.datetime,
    token: str = "",
) -> str:
    prefix = "p2n06:sse:" + str(owner)
    body = json.dumps({"event": kind, "data": data}, ensure_ascii=False, separators=(",", ":"))
    identifier = r.eval(
        PUBLISH,
        4,
        prefix + ":seq",
        prefix + ":order",
        prefix + ":body",
        prefix + ":dedup:" + token,
        at.timestamp(),
        body,
        at.timestamp() - 600,
        600,
        token,
    )
    return identifier.decode() if isinstance(identifier, bytes) else str(identifier)


def replay(
    r: redis.Redis,
    owner: uuid.UUID,
    last: str | None,
    at: dt.datetime,
    *,
    require_anchor: bool = True,
) -> list[dict[str, Any]]:
    if last is None or not last.isdecimal():
        return []
    p = "p2n06:sse:" + str(owner)
    score = r.zscore(p + ":order", last)
    if require_anchor and (score is None or score < at.timestamp() - 600):
        return []
    result = []
    for raw in r.zrangebyscore(p + ":order", at.timestamp() - 600, at.timestamp()):
        identifier = raw.decode() if isinstance(raw, bytes) else str(raw)
        if int(identifier) <= int(last):
            continue
        body = r.hget(p + ":body", identifier)
        if body:
            result.append({"id": identifier, **json.loads(body)})
    return sorted(result, key=lambda x: int(x["id"]))


def enqueue(
    engine: Engine, r: redis.Redis, owner: uuid.UUID, identifier: uuid.UUID, at: dt.datetime
) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            select(notifications).where(
                notifications.c.id == identifier, notifications.c.user_id == owner
            )
        ).one_or_none()
        if row is None:
            return
        cadence = (
            conn.execute(
                select(user_realtime_prefs.c.notify_cadence).where(
                    user_realtime_prefs.c.user_id == owner
                )
            ).scalar_one_or_none()
            or "1m"
        )
        data = project(conn, row)
    token = f"{identifier}:v{data['version']}"
    if cadence == "realtime" or row.severity == "important" or row.security_code is None:
        publish(r, owner, "notification", data, at, token)
        return
    minutes = int(cadence[:-1])
    local = at.astimezone(TZ)
    start = local.replace(minute=local.minute // minutes * minutes, second=0, microsecond=0)
    end = start + dt.timedelta(minutes=minutes)
    member = f"{owner}|{identifier}|{end.isoformat()}"
    r.zadd("p2n06:notify:pending", {member: end.timestamp()}, nx=True)


def flush(engine: Engine, r: redis.Redis, at: dt.datetime) -> int:
    members = r.eval(CLAIM, 1, "p2n06:notify:pending", at.timestamp())
    for raw in members:
        owner, identifier, bucket = raw.decode().split("|")
        with engine.connect() as conn:
            row = conn.execute(
                select(notifications).where(
                    notifications.c.id == uuid.UUID(identifier),
                    notifications.c.user_id == uuid.UUID(owner),
                )
            ).one_or_none()
            if row is None:
                continue
            data = project(conn, row)
        publish(r, uuid.UUID(owner), "notification", data, at, f"{identifier}:{bucket}")
    return len(members)


def reset_reason(
    r: redis.Redis, owner: uuid.UUID, last: str | None, at: dt.datetime, latest: str
) -> str | None:
    if last is None:
        return None
    if not last.isascii() or not last.isdecimal() or len(last) > 20:
        return "unknown"
    if str(int(last)) != last or int(last) <= 0 or int(last) > int(latest):
        return "unknown"
    score = r.zscore("p2n06:sse:" + str(owner) + ":order", last)
    return "expired" if score is None or score < at.timestamp() - 600 else None
