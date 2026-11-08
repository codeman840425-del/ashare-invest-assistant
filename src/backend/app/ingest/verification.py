"""Owned verify_licence consumer, with a durable no-replay reservation and shared gate."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Callable

import redis
from sqlalchemy import Connection, Engine, insert, select, text, update

from app.config import Settings
from app.db.tables.licences import user_data_licence_status
from app.db.tables.ops import ingest_request_log
from app.db.tables.users import users
from app.ingest.daily_lists import credential, send, wire
from app.ingest.intents import VerifyIntent, parse_intent
from app.ingest.live import check_egress, feedback, publish_feedback, send_paused
from app.ingest.shared_gate import GateClosedError, SharedGate, limit_code
from app.ingest.state import LicenceState, Priority
from app.ingest.upstream import Signal, classify
from app.ingest.verification_grants import read_grant
from app.licences.service import is_held, per_minute_limit
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

STREAM = "ingest:requests"
GROUP = "licence-verification-v1"


def allowed_before_send(
    conn: Connection,
    settings: Settings,
    intent: VerifyIntent,
    owner: uuid.UUID,
    at: dt.datetime,
) -> bool:
    row = conn.execute(
        select(user_data_licence_status)
        .join(users, users.c.id == user_data_licence_status.c.user_id)
        .where(
            user_data_licence_status.c.id == intent.licence_id,
            user_data_licence_status.c.user_id == owner,
            user_data_licence_status.c.deleted_at.is_(None),
            users.c.status == "approved",
        )
    ).first()
    if row is None or is_held(conn, row.user_id):
        return False
    state = LicenceState(
        settings.business.ingest.licences,
        DataLicenceTier(row.tier),
        status=DataLicenceStatus(row.status),
        expires_on=row.expires_on,
        paused_until=row.paused_until,
    )
    if state.status == DataLicenceStatus.INVALID:
        state.user_reset()
    state.tick(at)
    return state.allows(Priority.P0, at, verify=True)


def process(
    engine: Engine,
    settings: Settings,
    intent: VerifyIntent,
    *,
    clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    upstream: Callable[[str, str], tuple[int, object]] = wire,
    egress: Callable[[], str] = check_egress,
    secret_loader: Callable[[Engine, uuid.UUID], str] = credential,
) -> str:
    if (
        os.environ.get("MAIRUI_MODE", "replay") != "live"
        or not settings.data_licence_settings_enabled
    ):
        return "closed"
    grant = read_grant()
    if grant is None or not grant.valid(intent.licence_id, clock()):
        return "authorization_unavailable"
    if send_paused(settings):
        return "busy_or_closed"
    try:
        gate = SharedGate.from_environment(intent.licence_id, "product_verify")
        gate.acquire()
    except GateClosedError:
        return "busy_or_closed"
    secret = None
    try:
        with engine.connect() as lock:
            if not lock.execute(
                text("SELECT pg_try_advisory_lock(hashtext('ingest:single-egress'))")
            ).scalar_one():
                return "busy_or_closed"
            lock.commit()
            try:
                with engine.begin() as conn:
                    row = conn.execute(
                        select(user_data_licence_status)
                        .join(users, users.c.id == user_data_licence_status.c.user_id)
                        .where(
                            user_data_licence_status.c.id == intent.licence_id,
                            user_data_licence_status.c.deleted_at.is_(None),
                            users.c.status == "approved",
                        )
                    ).first()
                    if row is None or row.user_id != grant.user_id or is_held(conn, row.user_id):
                        return "unavailable"
                    state = LicenceState(
                        settings.business.ingest.licences,
                        DataLicenceTier(row.tier),
                        status=DataLicenceStatus(row.status),
                        expires_on=row.expires_on,
                        paused_until=row.paused_until,
                    )
                    if state.status == DataLicenceStatus.INVALID:
                        state.user_reset()  # Only an explicit verify intent reaches an invalid row.
                    state.tick(clock())
                    if not state.allows(Priority.P0, clock(), verify=True):
                        return "unavailable"
                    dedup = "verify-grant:" + str(grant.receipt_id)
                    if conn.execute(
                        select(ingest_request_log.c.id).where(
                            (ingest_request_log.c.dedup_key == dedup)
                            | (ingest_request_log.c.id == intent.verification_id),
                        )
                    ).first():
                        return "already_attempted"
                    limit = per_minute_limit(settings, row)
                if gate.product_delay(clock().timestamp()) > 0:
                    return "busy_or_closed"
                gate.confirm_egress(egress())
                if read_grant() != grant or not grant.valid(intent.licence_id, clock()):
                    return "authorization_unavailable"
                if send_paused(settings):
                    return "busy_or_closed"
                started = clock()
                # Reserve before credential load/HTTP; uncertain attempts are never retried.
                with engine.begin() as conn:
                    conn.execute(
                        insert(ingest_request_log).values(
                            id=intent.verification_id,
                            requested_at=started,
                            requester="ingest",
                            priority="P0",
                            dataset="licence_verification",
                            endpoint_key="tcalendar_list",
                            dedup_key=dedup,
                            status="queued",
                            licence_id=intent.licence_id,
                        )
                    )
                gate.check()
                secret = secret_loader(engine, intent.licence_id)
                gate.bind_certificate(secret)
                if (
                    read_grant() != grant
                    or not grant.valid(intent.licence_id, clock())
                    or send_paused(settings)
                ):
                    return "failed_no_retry"
                if gate.product_delay(clock().timestamp()) > 0:
                    return "failed_no_retry"
                gate.reserve(now=clock().timestamp(), limit=limit)
                gate.check()
                if read_grant() != grant or not grant.valid(intent.licence_id, clock()):
                    return "failed_no_retry"
                if send_paused(settings):
                    return "failed_no_retry"
                with engine.connect() as conn:
                    if not allowed_before_send(conn, settings, intent, grant.user_id, clock()):
                        return "failed_no_retry"
                try:
                    status, body = send(gate, upstream, f"/tcalendar/list/{started.year}/", secret)
                except Exception:  # noqa: BLE001 - persist only the fixed network classification
                    feedback(
                        engine,
                        settings,
                        intent.licence_id,
                        Signal.NETWORK,
                        token=intent.verification_id,
                        at=clock(),
                        code="network",
                        verification_id=intent.verification_id,
                        verify=True,
                    )
                    return "failed_no_retry"
                code = limit_code(status, body)
                halt_token = gate.trip(code) if code else None
                signal = Signal.IP_LIMITED if code else classify(status, body)
                if signal == Signal.OK and (not isinstance(body, list) or not body):
                    signal = Signal.CLIENT_ERROR
                gate.complete(now=clock().timestamp())
                with engine.begin() as conn:
                    conn.execute(
                        update(ingest_request_log)
                        .where(
                            ingest_request_log.c.id == intent.verification_id,
                            ingest_request_log.c.requested_at == started,
                        )
                        .values(
                            status="done" if signal == Signal.OK else "failed",
                            http_status=status,
                            mairui_code=code,
                            finished_at=clock(),
                        )
                    )
                if code is None:
                    code = {
                        Signal.QUOTA: "101",
                        Signal.INVALID: "102",
                        Signal.RATE_LIMITED: "503",
                        Signal.SERVER_ERROR: "http_5xx",
                    }.get(signal)
                feedback(
                    engine,
                    settings,
                    intent.licence_id,
                    signal,
                    token=halt_token or intent.verification_id,
                    at=clock(),
                    code=code,
                    verification_id=intent.verification_id,
                    verify=True,
                )
                return "verified" if signal == Signal.OK else "failed"
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(hashtext('ingest:single-egress'))"))
                lock.commit()
    except Exception:  # noqa: BLE001 - sanitize transport/credential errors; never retry
        # Unknown transport/commit outcomes keep the gate reservation/lease until human review.
        return "failed_no_retry"
    finally:
        secret = None
        gate.release()


def tick(engine: Engine, rds: redis.Redis, settings: Settings) -> int:
    if (
        os.environ.get("MAIRUI_MODE", "replay") != "live"
        or not settings.data_licence_settings_enabled
    ):
        return 0
    authorization = read_grant()
    if authorization is None:
        return 0
    from redis.exceptions import ResponseError

    try:
        rds.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise RuntimeError("verification_stream_unavailable") from None
    pending = rds.xautoclaim(
        STREAM, GROUP, "ingest-verify", min_idle_time=60000, start_id="0-0", count=1
    )[1]
    messages = (
        pending
        or (rds.xreadgroup(GROUP, "ingest-verify", {STREAM: ">"}, count=1) or [(None, [])])[0][1]
    )
    for mid, fields in messages:
        try:
            intent = parse_intent(fields)
        except (ValueError, UnicodeError):
            rds.xack(STREAM, GROUP, mid)
            return 0
        result = process(engine, settings, intent) if isinstance(intent, VerifyIntent) else "skip"
        if result not in {"busy_or_closed", "authorization_unavailable"}:
            rds.xack(STREAM, GROUP, mid)
            if isinstance(intent, VerifyIntent):
                publish_status(engine, rds, intent)
        return int(result != "skip")
    # A recent pending stream message still owns verification; never invent a second intent.
    if rds.xpending(STREAM, GROUP)["pending"]:
        return 0
    # Recover an enqueue failure once per pending generation, excluding any logged attempt.
    with engine.connect() as conn:
        pending_rows = conn.execute(
            select(user_data_licence_status)
            .where(
                user_data_licence_status.c.status == "pending_verification",
                user_data_licence_status.c.id == authorization.licence_id,
                user_data_licence_status.c.deleted_at.is_(None),
                ~select(ingest_request_log.c.id)
                .where(
                    ingest_request_log.c.licence_id == user_data_licence_status.c.id,
                    ingest_request_log.c.dataset == "licence_verification",
                    ingest_request_log.c.requested_at
                    >= user_data_licence_status.c.status_changed_at,
                )
                .exists(),
            )
            .order_by(user_data_licence_status.c.created_at)
            .limit(32)
        ).all()
    for row in pending_rows:
        token = uuid.uuid5(row.id, "pending:" + row.status_changed_at.isoformat())
        intent = VerifyIntent(row.id, token)
        result = process(engine, settings, intent)
        if result not in {"busy_or_closed", "authorization_unavailable"}:
            publish_status(engine, rds, intent)
            return 1
    return 0


def publish_status(engine: Engine, rds: redis.Redis, intent: VerifyIntent) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            select(user_data_licence_status).where(
                user_data_licence_status.c.id == intent.licence_id,
                user_data_licence_status.c.deleted_at.is_(None),
            )
        ).first()
    if row is not None:
        publish_feedback(
            rds,
            {
                "owner": row.user_id,
                "status": row.status,
                "verification_id": str(intent.verification_id),
                "last_error_code": row.last_error_code,
                "at": dt.datetime.now(dt.UTC).isoformat(),
            },
            intent.verification_id,
        )
