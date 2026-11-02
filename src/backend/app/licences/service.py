"""每用户数据证书的读写（契约 v0.2.6/v0.2.8 §7.1 / §7.9，plan §2.1B；T-B45、T-B03d）。

- 证书明文只在 :func:`set_licence` 里短暂存在：先算去重 HMAC，再用 ingest 公钥 HPKE 封装，
  **不写日志、不进 Redis、不返回**；
  ``ingest:requests`` 的 ``verify_licence`` 意图只带 ``licence_id``。
- 读状态只走视图 ``app.user_data_licence_status``（无密文、无 HMAC）。
- 每次状态或绑定变化写 ``ops.data_licence_events``（只追加，不含证书值）。
- 替换（PUT 已有证书）：旧行软删除（密文、HMAC 置 NULL），插入新行（新 ``id`` 进 AAD）。
- 管理员暂停按**用户**记录（``app.user_data_licence_holds``，契约 v0.2.8 #12、T-B03d /
  review M1）：暂停中的用户 PUT（含 DELETE 后再 PUT）→ 202、``paused_by_admin``、不投递验证；
  DELETE 后 GET 仍为 ``paused_by_admin``；只有管理员 resume 解除。
- 重复 PUT **同一证书**（HMAC 相同，契约 v0.2.8 #13 / review M2）：``paused_until`` 未到期或
  状态为 ``quota_exceeded`` / ``ip_limited`` → 原行原状态（``licence_id`` 不变），只更新
  ``tier``/``has_quant_pro``/``expires_on``，不投递验证。其余情况换新行进入
  ``pending_verification``。
"""

from __future__ import annotations

import datetime as dt
import functools
import hmac
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import redis
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from sqlalchemy import (
    ColumnElement,
    Connection,
    Row,
    and_,
    case,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.auth.service import BEIJING, bj, now_utc
from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.licences import (
    data_licence_events,
    user_data_licence_cooldowns,
    user_data_licence_holds,
    user_data_licence_status,
)
from app.db.tables.licences import user_data_licences as udl
from app.db.tables.ops import ingest_request_log
from app.db.tables.users import users
from app.licences.keys import parse_public_keys
from app.licences.seal import cooldown_fingerprint, licence_hmac, seal_licence
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

logger = logging.getLogger(__name__)

#: plan §2.1A / §2.1B：其他服务向 ingest 投递意图的 Stream
INGEST_REQUESTS_STREAM: Final = "ingest:requests"
#: ingest 维护的每证书队列深度（hash：p0/p1/p2）；api 只读，缺失按 0
QUEUE_DEPTH_KEY: Final = "ingest:licence:{licence_id}:queue_depth"
VERIFY_INTENT: Final = "verify_licence"
#: ``ingest_request_log`` 里算“已发出调用”的状态（queued 未外呼、dropped 被丢弃）
_CALLED_STATUSES: Final = ("done", "failed")

S = DataLicenceStatus
#: 上游降级冷却（plan 降级表）：同一证书重新 PUT 不能清除
COOLDOWN_STATUSES: Final = frozenset({S.QUOTA_EXCEEDED.value, S.IP_LIMITED.value})


@dataclass(frozen=True)
class SetResult:
    row: Row[Any]
    verification_id: uuid.UUID | None


def _today_bj() -> dt.date:
    return now_utc().astimezone(BEIJING).date()


def not_set_view() -> dict[str, Any]:
    return {
        "status": S.NOT_SET.value,
        "tier": None,
        "has_quant_pro": None,
        "expires_on": None,
        "days_to_expiry": None,
        "set_at": None,
        "last_verified_at": None,
        "last_error_code": None,
        "last_error_at": None,
        "paused_until": None,
    }


def status_view(row: Row[Any] | None, *, held: bool = False) -> dict[str, Any]:
    """``DataLicenceStatus``（契约 §5）。**不含证书值或其任何片段**。

    契约 v0.2.8 §7.1 DELETE：管理员暂停期间删除证书后 ``GET`` 仍返回
    ``status: "paused_by_admin"``、证书相关字段为 null（``row is None and held``）。"""
    if row is None:
        view = not_set_view()
        if held:
            view["status"] = S.PAUSED_BY_ADMIN.value
        return view
    expires_on: dt.date | None = row.expires_on
    return {
        "status": row.status,
        "tier": row.tier,
        "has_quant_pro": bool(row.has_quant_pro),
        "expires_on": None if expires_on is None else expires_on.isoformat(),
        "days_to_expiry": None if expires_on is None else (expires_on - _today_bj()).days,
        "set_at": bj(row.created_at),
        "last_verified_at": bj(row.last_verified_at),
        "last_error_code": row.last_error_code,
        "last_error_at": bj(row.last_error_at),
        "paused_until": bj(row.paused_until),
    }


def live_row(conn: Connection, user_id: uuid.UUID, *, lock: bool = False) -> Row[Any] | None:
    """本人未删除的证书行（视图列；``lock`` 时直接锁表行，仍不取密文列）。"""
    if lock:
        cols = [udl.c[name] for name in user_data_licence_status.c.keys()]  # noqa: SIM118
        stmt = (
            select(*cols)
            .where(udl.c.user_id == user_id, udl.c.deleted_at.is_(None))
            .with_for_update()
        )
    else:
        v = user_data_licence_status.c
        stmt = select(user_data_licence_status).where(v.user_id == user_id, v.deleted_at.is_(None))
    return conn.execute(stmt).first()


def live_status(conn: Connection, user_id: uuid.UUID) -> str:
    row = live_row(conn, user_id)
    if row is not None:
        return str(row.status)
    return S.PAUSED_BY_ADMIN.value if is_held(conn, user_id) else S.NOT_SET.value


def user_view(conn: Connection, user_id: uuid.UUID) -> dict[str, Any]:
    """``GET /me/data-licence``：证书行 + 用户级暂停记录。"""
    row = live_row(conn, user_id)
    return status_view(row, held=row is None and is_held(conn, user_id))


def record_event(
    conn: Connection,
    *,
    licence_id: uuid.UUID,
    user_id: uuid.UUID,
    event: str,
    actor: str,
    from_status: str | None,
    to_status: str | None,
    upstream_code: str | None = None,
) -> None:
    conn.execute(
        insert(data_licence_events).values(
            licence_id=licence_id,
            user_id=user_id,
            event=event,
            actor=actor,
            from_status=from_status,
            to_status=to_status,
            upstream_code=upstream_code,
        )
    )


@functools.lru_cache(maxsize=4)
def _parsed_public_keys(text: str) -> dict[int, X25519PublicKey]:
    return parse_public_keys(text)


def current_public_key(settings: Settings) -> tuple[int, X25519PublicKey]:
    """当前封装公钥；未配置（运维 T-O09 未完成）→ ``503 MAINTENANCE``
    （不接收证书，绝不明文存库）。"""
    text, version = settings.data_licence_seal_public_keys, settings.data_licence_seal_key_version
    if not text or version is None:
        logger.error("data-licence: seal public key not configured; refusing PUT")
        raise AppError(ErrorCode.MAINTENANCE)
    keys = _parsed_public_keys(text)
    return version, keys[version]


def _is_unique_violation_on(exc: Exception, index_name: str) -> bool:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None) == index_name


def is_held(conn: Connection, user_id: uuid.UUID) -> bool:
    """该用户是否处于管理员暂停中（用户级，不随证书行删除而解除）。"""
    h = user_data_licence_holds.c
    return conn.execute(select(h.user_id).where(h.user_id == user_id)).first() is not None


def hold(conn: Connection, user_id: uuid.UUID) -> None:
    conn.execute(
        pg_insert(user_data_licence_holds)
        .values(user_id=user_id)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )


def release_hold(conn: Connection, user_id: uuid.UUID) -> bool:
    """删除暂停记录；返回之前是否处于暂停。"""
    h = user_data_licence_holds.c
    res = conn.execute(delete(user_data_licence_holds).where(h.user_id == user_id))
    return bool(res.rowcount)


def _same_licence(conn: Connection, row_id: uuid.UUID, digest: bytes) -> bool:
    stmt = select(udl.c.id).where(udl.c.id == row_id, udl.c.licence_hmac == digest)
    return conn.execute(stmt).first() is not None


def keeps_state(row: Row[Any], now: dt.datetime) -> bool:
    """契约 v0.2.8 §7.1 重复 PUT 同一证书：``paused_until`` 未到期，或状态为
    ``quota_exceeded``/``ip_limited`` → 保留当前状态，不验证。"""
    until: dt.datetime | None = row.paused_until
    return row.status in COOLDOWN_STATUSES or (until is not None and until > now)


def hmac_in_use_by_other(conn: Connection, user_id: uuid.UUID, digest: bytes) -> bool:
    return (
        conn.execute(
            select(udl.c.id).where(
                udl.c.licence_hmac == digest,
                udl.c.deleted_at.is_(None),
                udl.c.user_id != user_id,
            )
        ).first()
        is not None
    )


#: 删除时可保留的冷却状态（``paused_by_admin`` 由用户级暂停记录负责，不在此列）
_COOLDOWN_KEEP: Final = frozenset({S.ACTIVE.value, *COOLDOWN_STATUSES})


#: T-B03f（review-be607b3 M1）：``paused_until`` 为空的冷却记录（quota_exceeded/ip_limited
#: 不按时间到期）最多保留 24 小时（自 deleted_at 起）。上限口径待架构师在契约第 776 行确认。
COOLDOWN_NULL_UNTIL_TTL: Final = dt.timedelta(hours=24)


def _cooldown_expired(now: dt.datetime) -> ColumnElement[bool]:
    """到期条件（SQL 表达式）：``paused_until <= now``，或 ``paused_until`` 为空且
    ``deleted_at <= now - 24h``。"""
    cd = user_data_licence_cooldowns
    return or_(
        cd.c.paused_until <= now,
        and_(cd.c.paused_until.is_(None), cd.c.deleted_at <= now - COOLDOWN_NULL_UNTIL_TTL),
    )


def purge_expired_cooldowns(conn: Connection, now: dt.datetime | None = None) -> int:
    """T-B03f（review-be607b3 M1，契约第 776 行“指纹只保留到 paused_until 为止”）：删除全部
    已到期的冷却记录，返回删除行数。cleanup-on-access：每次证书 PUT/DELETE 先调用；另由 beat
    按 ``COOLDOWN_PURGE_INTERVAL_S`` 排程、worker 定时执行（T-B49，:mod:`app.workers.jobs`）。"""
    cd = user_data_licence_cooldowns
    res = conn.execute(delete(cd).where(_cooldown_expired(now or now_utc())))
    return int(res.rowcount or 0)


def _remember_cooldown(
    conn: Connection, settings: Settings, row: Row[Any], digest: bytes, now: dt.datetime
) -> bool:
    """T-B03e（契约 v0.2.8 #13 补充）：冷却中 DELETE → 记下指纹与删除前状态（覆盖旧记录）；
    否则清除该用户的旧记录。返回是否记下。"""
    cd = user_data_licence_cooldowns
    purge_expired_cooldowns(conn, now)
    conn.execute(delete(cd).where(cd.c.user_id == row.user_id))
    if row.status not in _COOLDOWN_KEEP or not keeps_state(row, now):
        return False
    conn.execute(
        insert(cd).values(
            user_id=row.user_id,
            fingerprint=cooldown_fingerprint(settings, row.user_id, digest),
            status=row.status,
            paused_until=row.paused_until,
            last_error_code=row.last_error_code,
            last_error_at=row.last_error_at,
            consecutive_failures=row.consecutive_failures,
            deleted_at=now,
        )
    )
    return True


def _take_cooldown(
    conn: Connection, settings: Settings, user_id: uuid.UUID, digest: bytes, now: dt.datetime
) -> Row[Any] | None:
    """取出并删除该用户的冷却记录；指纹相同且未到期时返回它（``paused_until`` 为空的
    quota_exceeded/ip_limited 不按 paused_until 到期，但记录本身最多保留
    :data:`COOLDOWN_NULL_UNTIL_TTL`）。先清理全部已到期记录（T-B03f）。"""
    cd = user_data_licence_cooldowns
    purge_expired_cooldowns(conn, now)
    rec = conn.execute(delete(cd).where(cd.c.user_id == user_id).returning(*cd.c)).first()
    if rec is None:
        return None
    fp = cooldown_fingerprint(settings, user_id, digest)
    if not hmac.compare_digest(bytes(rec.fingerprint), fp):
        return None
    until: dt.datetime | None = rec.paused_until
    if until is not None and until <= now:
        return None
    if until is None and rec.status not in COOLDOWN_STATUSES:
        return None
    if until is None and rec.deleted_at <= now - COOLDOWN_NULL_UNTIL_TTL:
        return None
    return rec


def set_licence(
    conn: Connection,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    licence: str,
    tier: str,
    has_quant_pro: bool,
    expires_on: dt.date | None,
) -> SetResult:
    """设置或替换。调用方在事务里调用；``IntegrityError`` 由调用方映射
    （见 :func:`map_integrity`）。"""
    version, public_key = current_public_key(settings)
    digest = licence_hmac(settings, licence)
    if hmac_in_use_by_other(conn, user_id, digest):
        raise AppError(ErrorCode.DATA_LICENCE_IN_USE)
    old = live_row(conn, user_id, lock=True)
    now = now_utc()
    held = is_held(conn, user_id) or (old is not None and old.status == S.PAUSED_BY_ADMIN)
    same = old is not None and _same_licence(conn, old.id, digest)
    if old is not None and same and (held or keeps_state(old, now)):
        # 契约 v0.2.8 #12/#13：同一证书（HMAC 相同）且处于管理员暂停、上游冷却或
        # paused_until 未到期 → 原行原状态，只更新 tier/has_quant_pro/expires_on，不验证；
        # licence_id 不变（ingest 令牌桶、队列、调用计数都按它记）
        values: dict[str, Any] = {
            "tier": tier,
            "has_quant_pro": has_quant_pro,
            "expires_on": expires_on,
            "updated_at": now,
        }
        if held and old.status != S.PAUSED_BY_ADMIN:  # 暂停记录在而行状态不一致：以暂停为准
            values.update(status=S.PAUSED_BY_ADMIN.value, status_changed_at=now)
        conn.execute(update(udl).where(udl.c.id == old.id).values(**values))
        kept = live_row(conn, user_id)
        assert kept is not None  # noqa: S101
        return SetResult(row=kept, verification_id=None)
    # 冷却中 DELETE 后、到期前 PUT 同一证书（T-B03e，#13 补充）→ 恢复删除前的状态与 paused_until，
    # 不验证。记录总是取出删除：换证、到期或不匹配都作废（与证书行“换证即清除”一致）
    restored = _take_cooldown(conn, settings, user_id, digest, now) if old is None else None
    if old is not None:
        conn.execute(
            delete(user_data_licence_cooldowns).where(
                user_data_licence_cooldowns.c.user_id == user_id
            )
        )
    # 新证书（或同一证书但无须保留状态）：换新行。暂停按用户记录（#12），新行仍为
    # paused_by_admin、不验证；DELETE 后再 PUT 同样如此
    status_value = S.PAUSED_BY_ADMIN.value if held else S.PENDING_VERIFICATION.value
    if restored is not None and not held:
        status_value = str(restored.status)
    verify = status_value == S.PENDING_VERIFICATION.value
    if old is not None:
        conn.execute(
            update(udl)
            .where(udl.c.id == old.id)
            .values(deleted_at=now, ciphertext=None, licence_hmac=None, updated_at=now)
        )
    row_id = uuid.uuid4()
    sealed = seal_licence(public_key, licence, user_id=user_id, row_id=row_id, key_version=version)
    values = {
        "id": row_id,
        "user_id": user_id,
        "provider": "mairui",
        "ciphertext": sealed,
        "seal_key_version": version,
        "licence_hmac": digest,
        "tier": tier,
        "has_quant_pro": has_quant_pro,
        "expires_on": expires_on,
        "status": status_value,
        "status_changed_at": now,
        "created_at": now,
        "updated_at": now,
    }
    if restored is not None:
        values.update(
            paused_until=restored.paused_until,
            last_error_code=restored.last_error_code,
            last_error_at=restored.last_error_at,
            consecutive_failures=restored.consecutive_failures,
        )
    conn.execute(insert(udl).values(**values))
    if old is not None:
        record_event(
            conn,
            licence_id=old.id,
            user_id=user_id,
            event="replaced",
            actor="user",
            from_status=old.status,
            to_status=None,
        )
    record_event(
        conn,
        licence_id=row_id,
        user_id=user_id,
        event="set",
        actor="user",
        from_status=S.NOT_SET.value,
        to_status=status_value,
    )
    row = live_row(conn, user_id)
    assert row is not None  # noqa: S101 - 刚插入
    return SetResult(row=row, verification_id=uuid.uuid4() if verify else None)


def map_integrity(exc: Exception) -> AppError:
    """并发 PUT 的唯一索引冲突：HMAC 冲突 → IN_USE；同一用户两行 → CONFLICT。"""
    if _is_unique_violation_on(exc, "uq_user_data_licences_hmac_live"):
        return AppError(ErrorCode.DATA_LICENCE_IN_USE)
    return AppError(ErrorCode.CONFLICT)


def patch_licence(conn: Connection, *, user_id: uuid.UUID, changes: Mapping[str, Any]) -> Row[Any]:
    old = live_row(conn, user_id, lock=True)
    if old is None:
        raise AppError(ErrorCode.DATA_LICENCE_NOT_SET)
    if changes:
        conn.execute(update(udl).where(udl.c.id == old.id).values(**changes, updated_at=now_utc()))
    row = live_row(conn, user_id)
    assert row is not None  # noqa: S101
    return row


def delete_licence(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    actor: str = "user",
    settings: Settings | None = None,
) -> bool:
    """软删除并清除密文；未设置时返回 ``False``（路由仍 204，幂等）。

    给了 ``settings`` 时（用户 DELETE），冷却中删除会记下指纹与删除前状态（T-B03e）。"""
    old = live_row(conn, user_id, lock=True)
    if old is None:
        return False
    now = now_utc()
    if settings is not None:
        digest = conn.execute(select(udl.c.licence_hmac).where(udl.c.id == old.id)).scalar_one()
        _remember_cooldown(conn, settings, old, bytes(digest), now)
    conn.execute(
        update(udl)
        .where(udl.c.id == old.id)
        .values(deleted_at=now, ciphertext=None, licence_hmac=None, updated_at=now)
    )
    record_event(
        conn,
        licence_id=old.id,
        user_id=user_id,
        event="deleted",
        actor=actor,
        from_status=old.status,
        to_status=S.NOT_SET.value,
    )
    return True


def set_status(
    conn: Connection,
    row: Row[Any],
    *,
    to: DataLicenceStatus,
    event: str,
    actor: str,
    **values: Any,  # noqa: ANN401
) -> None:
    now = now_utc()
    conn.execute(
        update(udl)
        .where(udl.c.id == row.id)
        .values(status=to.value, status_changed_at=now, updated_at=now, **values)
    )
    record_event(
        conn,
        licence_id=row.id,
        user_id=row.user_id,
        event=event,
        actor=actor,
        from_status=row.status,
        to_status=to.value,
    )


def enqueue_verify(rds: redis.Redis, *, licence_id: uuid.UUID, verification_id: uuid.UUID) -> None:
    """``XADD ingest:requests``：只带 ``licence_id``（plan §2.1B：明文不经过 Redis）。"""
    rds.xadd(
        INGEST_REQUESTS_STREAM,
        {
            "kind": VERIFY_INTENT,
            "licence_id": str(licence_id),
            "verification_id": str(verification_id),
            "priority": "P0",
            "requested_at": now_utc().isoformat(),
        },
    )


def enqueue_verify_best_effort(
    rds: redis.Redis, *, licence_id: uuid.UUID, verification_id: uuid.UUID
) -> None:
    """已提交的 PUT/resume 之后投递；Redis 不可用时只记日志（行状态仍为
    ``pending_verification``，由 ingest 启动/周期扫描兜底，见 T-B45 报告）。"""
    try:
        enqueue_verify(rds, licence_id=licence_id, verification_id=verification_id)
    except redis.RedisError as exc:
        logger.warning(
            "data-licence: verify intent not queued licence_id=%s (%s)",
            licence_id,
            type(exc).__name__,
        )


# ---------------------------------------------------------------- 管理端


def per_minute_limit(settings: Settings, row: Row[Any] | None) -> int:
    if row is None:
        return 0
    if row.per_minute_limit_override is not None:
        return int(row.per_minute_limit_override)
    tiers = settings.business.ingest.licences.tier_per_minute
    return int(getattr(tiers, str(row.tier)))


def call_counts(conn: Connection, licence_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    """``{licence_id: (calls_last_minute, calls_today)}``；今天从北京时间 00:00 起算。"""
    if not licence_ids:
        return {}
    now = now_utc()
    midnight = dt.datetime.combine(_today_bj(), dt.time(0), tzinfo=BEIJING)
    t = ingest_request_log
    last_minute = func.count().filter(t.c.requested_at >= now - dt.timedelta(minutes=1))
    stmt = (
        select(t.c.licence_id, last_minute, func.count())
        .where(
            and_(
                t.c.licence_id.in_(licence_ids),
                t.c.requested_at >= midnight,
                t.c.status.in_(_CALLED_STATUSES),
            )
        )
        .group_by(t.c.licence_id)
    )
    return {r[0]: (int(r[1]), int(r[2])) for r in conn.execute(stmt)}


def queue_depths(rds: redis.Redis, licence_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    zero = {"p0": 0, "p1": 0, "p2": 0}
    out = {lid: dict(zero) for lid in licence_ids}
    if not licence_ids:
        return out
    try:
        pipe = rds.pipeline(transaction=False)
        for lid in licence_ids:
            pipe.hgetall(QUEUE_DEPTH_KEY.format(licence_id=lid))
        results = pipe.execute()
    except redis.RedisError as exc:
        logger.warning("data-licence: queue depth unavailable (%s)", type(exc).__name__)
        return out
    for lid, raw in zip(licence_ids, results, strict=True):
        for k, v in (raw or {}).items():
            key = k.decode() if isinstance(k, bytes) else str(k)
            if key in zero:
                try:
                    out[lid][key] = max(0, int(v))
                except (TypeError, ValueError):
                    continue
    return out


# ------------------------------------------------- /admin/ingest/status licences[]（v0.2.8）

#: 契约 v0.2.8 §7.9：不分页，最多 500 行
INGEST_LICENCES_MAX: Final = 500
#: 契约 v0.2.8 §7.9 排序：状态严重度 → days_left 升序（null 在后）→ username
INGEST_STATUS_ORDER: Final = (
    S.INVALID.value,
    S.IP_LIMITED.value,
    S.QUOTA_EXCEEDED.value,
    S.EXPIRED.value,
    S.PAUSED_BY_ADMIN.value,
    S.PENDING_VERIFICATION.value,
    S.ACTIVE.value,
)


def daily_limit(settings: Settings, row: Row[Any]) -> int | None:
    """契约 v0.2.8 ``IngestLicenceStatus.daily_limit``：目前只有钻石版过期后有值
    （``ingest.yaml`` ``diamond_after_expiry_per_day``），其余 null【待 T003 补测】。"""
    expires_on: dt.date | None = row.expires_on
    if row.tier == DataLicenceTier.DIAMOND and expires_on is not None and expires_on < _today_bj():
        return int(settings.business.ingest.licences.diamond_after_expiry_per_day)
    return None


def ingest_licences(
    conn: Connection, rds: redis.Redis, settings: Settings
) -> tuple[list[dict[str, Any]], bool]:
    """``/admin/ingest/status`` 的 ``(licences, licences_truncated)``（契约 v0.2.8 §5.1
    ``IngestLicenceStatus``、§7.9）。每张已设置的证书一行（``not_set`` 不列出）；同名字段与
    ``/admin/data-licences`` 同源（:func:`call_counts`、:func:`queue_depths`、
    :func:`per_minute_limit`）。**不含证书值、密文、HMAC 或其任何片段，也不含证书长度**
    （只读视图 ``app.user_data_licence_status``，该视图本来就没有这些列）。"""
    vs = user_data_licence_status.c
    u = users.c
    rank = case(
        {status: i for i, status in enumerate(INGEST_STATUS_ORDER)},
        value=vs.status,
        else_=len(INGEST_STATUS_ORDER),
    )
    stmt = (
        select(
            vs.id,
            vs.user_id,
            vs.status,
            vs.tier,
            vs.has_quant_pro,
            vs.expires_on,
            vs.per_minute_limit_override,
            vs.paused_until,
            vs.last_error_code,
            vs.last_error_at,
            u.username,
            u.display_name,
        )
        .select_from(user_data_licence_status.join(users, u.id == vs.user_id))
        .where(vs.deleted_at.is_(None), u.deleted_at.is_(None))
        # days_left 升序 = expires_on 升序；null 在后
        .order_by(rank, vs.expires_on.asc().nulls_last(), u.username, vs.id)
        .limit(INGEST_LICENCES_MAX + 1)
    )
    rows: list[Row[Any]] = list(conn.execute(stmt))
    truncated = len(rows) > INGEST_LICENCES_MAX
    rows = rows[:INGEST_LICENCES_MAX]
    ids = [uuid.UUID(str(r.id)) for r in rows]
    counts = call_counts(conn, ids)
    depths = queue_depths(rds, ids)
    today = _today_bj()
    out: list[dict[str, Any]] = []
    for r, lid in zip(rows, ids, strict=True):
        last_minute, calls_today = counts.get(lid, (0, 0))
        expires_on: dt.date | None = r.expires_on
        out.append(
            {
                "licence_id": str(lid),
                "user_id": str(r.user_id),
                "username": r.username,
                "display_name": r.display_name,
                "status": r.status,
                "tier": r.tier,
                "has_quant_pro": None if r.has_quant_pro is None else bool(r.has_quant_pro),
                "expires_on": None if expires_on is None else expires_on.isoformat(),
                "days_left": None if expires_on is None else (expires_on - today).days,
                "calls_today": calls_today,
                "daily_limit": daily_limit(settings, r),
                "per_minute_limit": per_minute_limit(settings, r),
                "calls_last_minute": last_minute,
                "queue_depth": depths[lid],
                "paused_until": bj(r.paused_until),
                "last_error_code": r.last_error_code,
                "last_error_at": bj(r.last_error_at),
            }
        )
    return out, truncated
