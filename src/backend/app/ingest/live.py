"""T-B99 live control helpers: sanitized transport, owned status and durable notices."""

from __future__ import annotations

import datetime as dt
import http.client
import ipaddress
import json
import os
import re
import uuid
from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import Any

import redis
from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.config import Settings
from app.db.tables.licences import data_licence_events, user_data_licence_status
from app.db.tables.licences import user_data_licences as licences
from app.db.tables.notify import notifications
from app.db.tables.users import users
from app.ingest.certificate_bindings import cleanup
from app.ingest.shared_gate import (
    GateClosedError,
    _read,
    bound_halt,
    related_licences,
    stop_present,
)
from app.ingest.state import LicenceState
from app.ingest.upstream import Signal
from app.licences import service
from app.notify.transport import publish
from app.schemas.enums import DataLicenceStatus, DataLicenceTier


def check_egress() -> str:
    conn = http.client.HTTPSConnection("myip.ipip.net", timeout=10)
    try:
        conn.request("GET", "/", headers={"Connection": "close"})
        response = conn.getresponse()
        if response.status != 200:
            raise GateClosedError("egress_check_failed")
        text = response.read(4096).decode("utf-8", errors="replace")
        for candidate in re.findall(r"[0-9A-Fa-f:.]{7,45}", text):
            try:
                return str(ipaddress.ip_address(candidate.strip(".:")))
            except ValueError:
                continue
        raise GateClosedError("egress_check_failed")
    except Exception:  # noqa: BLE001 - fixed egress diagnostic, never expose transport text
        raise GateClosedError("egress_check_failed") from None
    finally:
        conn.close()


def send_paused(settings: Settings) -> bool:
    """Every send re-reads the existing Redis pause key; unavailable Redis stays closed."""
    if not settings.redis_url:
        return True
    client = None
    try:
        client = redis.Redis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        return bool(client.exists(settings.ingest_paused_key))
    except (redis.RedisError, ValueError):
        return True
    finally:
        if client is not None:
            with suppress(redis.RedisError, OSError):
                client.close()


def set_global_pause(
    settings: Settings, paused: bool, *, client: redis.Redis | None = None
) -> None:
    """Supported operator writer: same non-expiring mutex as every real send.

    A durable mirror also stops standalone probes. Pause writes the mirror first;
    resume removes it only after Redis succeeds. Failure always leaves a stop.
    """
    from app.ingest.send_control import critical, root_from_environment
    from app.ingest.shared_gate import _sync_directory, _write_stop_unlocked

    root = root_from_environment()
    own = client is None
    try:
        if not settings.redis_url and client is None:
            raise GateClosedError("global_pause_redis_required")
        client = client or redis.Redis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        with critical(root):
            marker = root / "PAUSED"
            if paused:
                _write_stop_unlocked(marker)
                client.set(
                    settings.ingest_paused_key,
                    json.dumps(
                        {
                            "by": "operator",
                            "at": dt.datetime.now(dt.UTC).isoformat(),
                            "reason": "operator_review_required",
                        }
                    ),
                )
            else:
                client.delete(settings.ingest_paused_key)
                if stop_present(marker):
                    marker.unlink()
                    _sync_directory(root)
    except (redis.RedisError, OSError, ValueError):
        raise GateClosedError("global_pause_write_failed_closed") from None
    finally:
        if own and client is not None:
            with suppress(redis.RedisError, OSError):
                client.close()


def feedback(
    engine: Engine,
    settings: Settings,
    lid: uuid.UUID,
    signal: Signal,
    *,
    token: uuid.UUID,
    at: dt.datetime,
    code: str | None = None,
    verification_id: uuid.UUID | None = None,
    verify: bool = False,
) -> dict[str, Any] | None:
    """One event/notice per transition token. No credential columns selected."""
    with engine.begin() as conn:
        row = conn.execute(
            select(user_data_licence_status)
            .where(
                user_data_licence_status.c.id == lid,
                user_data_licence_status.c.deleted_at.is_(None),
            )
            .with_for_update()
        ).first()
        if row is None or service.is_held(conn, row.user_id):
            return None
        eid = uuid.uuid5(token, "licence-transition")
        prior = conn.execute(
            select(data_licence_events.c.id, data_licence_events.c.licence_id).where(
                data_licence_events.c.id == eid
            )
        ).first()
        if prior:
            if prior.licence_id != lid and signal == Signal.IP_LIMITED:
                previous_pause = conn.execute(
                    select(user_data_licence_status.c.paused_until).where(
                        user_data_licence_status.c.id == prior.licence_id
                    )
                ).scalar_one_or_none()
                conn.execute(
                    update(licences)
                    .where(licences.c.id == lid)
                    .values(
                        status="ip_limited",
                        paused_until=previous_pause
                        or at
                        + dt.timedelta(
                            seconds=settings.business.ingest.licences.ip_limited_pause_s
                        ),
                        last_error_code=code,
                        last_error_at=at,
                        status_changed_at=dt.datetime.now(dt.UTC),
                        updated_at=dt.datetime.now(dt.UTC),
                    )
                )
            return None
        state = LicenceState(
            settings.business.ingest.licences,
            DataLicenceTier(row.tier),
            status=DataLicenceStatus(row.status),
            expires_on=row.expires_on,
            paused_until=row.paused_until,
            consecutive_failures=row.consecutive_failures,
        )
        root = os.environ.get("MAIRUI_SHARED_STATE_DIR")
        identities = related_licences(Path(root), lid) if root else [lid]
        state.ip_limited_hits = deque(
            conn.execute(
                select(data_licence_events.c.at)
                .where(
                    data_licence_events.c.licence_id.in_(identities),
                    data_licence_events.c.event == "ip_limited",
                    data_licence_events.c.at >= at - dt.timedelta(hours=1),
                )
                .order_by(data_licence_events.c.at)
            ).scalars()
        )
        state.tick(at)
        transitions = state.on_result(signal, at, verify=verify)
        values: dict[str, Any] = {
            "status": state.status.value,
            "updated_at": at,
            "paused_until": state.paused_until or state.backoff_until,
            "consecutive_failures": state.consecutive_failures,
        }
        if signal == Signal.OK and verify:
            values.update(last_verified_at=at, last_error_code=None, last_error_at=None)
        elif code is not None:
            values.update(last_error_code=code, last_error_at=at)
        if transitions:
            values["status_changed_at"] = at
        conn.execute(update(licences).where(licences.c.id == lid).values(**values))
        event = {
            Signal.OK: "verified",
            Signal.IP_LIMITED: "ip_limited",
            Signal.INVALID: "invalid",
            Signal.QUOTA: "quota_exceeded",
        }.get(signal)
        if event is not None:
            conn.execute(
                insert(data_licence_events)
                .values(
                    id=eid,
                    licence_id=lid,
                    user_id=row.user_id,
                    event=event,
                    actor="ingest",
                    from_status=row.status,
                    to_status=state.status.value,
                    upstream_code=code,
                    at=at,
                )
                .on_conflict_do_nothing()
            )
        if transitions or verify:
            recipients = {row.user_id}
            if signal in {Signal.IP_LIMITED, Signal.INVALID}:
                recipients.update(
                    conn.execute(
                        select(users.c.id).where(
                            users.c.role == "admin", users.c.status == "approved"
                        )
                    ).scalars()
                )
            for recipient in recipients:
                conn.execute(
                    insert(notifications)
                    .values(
                        user_id=recipient,
                        kind="data_licence",
                        severity="important" if code else "info",
                        title="数据证书状态更新",
                        body="证书验证或采集状态已更新，请在设置页查看。",
                        target_type="none",
                        dedup_key=f"data-licence:{token}:{recipient}",
                        created_at=at,
                    )
                    .on_conflict_do_nothing(index_elements=["user_id", "dedup_key"])
                )
        return {
            "owner": row.user_id,
            "status": state.status.value,
            "verification_id": str(verification_id) if verification_id else None,
            "last_error_code": code,
            "at": at.isoformat(),
        }


def publish_feedback(rds: redis.Redis, payload: dict[str, Any] | None, token: uuid.UUID) -> None:
    if payload is None:
        return
    owner = payload["owner"]
    body = {key: value for key, value in payload.items() if key != "owner"}
    # Durable state/notification is retained if the disposable SSE buffer is unavailable.
    with suppress(redis.RedisError):
        publish(rds, owner, "data_licence", body, dt.datetime.fromisoformat(body["at"]), str(token))


def sync_halts(engine: Engine, settings: Settings, rds: redis.Redis, root: Path) -> None:
    """Reflect a probe's shared latch without using its samples or reading a licence."""
    with engine.connect() as conn:
        now = conn.execute(select(func.now())).scalar_one().astimezone(dt.UTC)
        states = conn.execute(select(user_data_licence_status)).all()
    cleanup(root, engine=engine)
    lids = [row.id for row in states if row.deleted_at is None]
    for lid in lids:
        path = bound_halt(root, lid)
        if not path.exists():
            continue
        obj = _read(path)
        if obj.get("code") not in {"103", "429"}:
            continue
        token = uuid.UUID(obj["id"])
        at = dt.datetime.fromtimestamp(obj["at"], dt.UTC)
        payload = feedback(
            engine, settings, lid, Signal.IP_LIMITED, token=token, at=at, code=obj["code"]
        )
        publish_feedback(rds, payload, token)
    stop = root / "STOP"
    if stop_present(stop):
        info = stop.stat()
        key = "global-stop:" + str(info.st_ino) + ":" + str(info.st_mtime_ns)
        with engine.begin() as conn:
            admins = conn.execute(
                select(users.c.id).where(users.c.role == "admin", users.c.status == "approved")
            ).scalars()
            for owner in admins:
                conn.execute(
                    insert(notifications)
                    .values(
                        user_id=owner,
                        kind="data_licence",
                        severity="important",
                        title="麦蕊采集已全局停止",
                        body="公共STOP存在，请按授权检查两侧采集状态。",
                        target_type="none",
                        dedup_key=key,
                        created_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["user_id", "dedup_key"])
                )
