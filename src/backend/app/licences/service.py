"""每用户数据证书的读写（契约 v0.2.6 §7.1 / §7.9，plan §2.1B；T-B45）。

- 证书明文只在 :func:`set_licence` 里短暂存在：先算去重 HMAC，再用 ingest 公钥 HPKE 封装，
  **不写日志、不进 Redis、不返回**；
  ``ingest:requests`` 的 ``verify_licence`` 意图只带 ``licence_id``。
- 读状态只走视图 ``app.user_data_licence_status``（无密文、无 HMAC）。
- 每次状态或绑定变化写 ``ops.data_licence_events``（只追加，不含证书值）。
- 替换（PUT 已有证书）：旧行软删除（密文、HMAC 置 NULL），插入新行（新 ``id`` 进 AAD）。
  旧行为 ``paused_by_admin`` 时新行**沿用暂停**、不投递验证（防止用户靠换证书绕开管理员暂停；
  契约未写，已在 T-B45 报告提请架构确认）。
"""

from __future__ import annotations

import datetime as dt
import functools
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import redis
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from sqlalchemy import Connection, Row, and_, func, insert, select, update

from app.auth.service import BEIJING, bj, now_utc
from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.licences import data_licence_events, user_data_licence_status
from app.db.tables.licences import user_data_licences as udl
from app.db.tables.ops import ingest_request_log
from app.licences.keys import parse_public_keys
from app.licences.seal import licence_hmac, seal_licence
from app.schemas.enums import DataLicenceStatus

logger = logging.getLogger(__name__)

#: plan §2.1A / §2.1B：其他服务向 ingest 投递意图的 Stream
INGEST_REQUESTS_STREAM: Final = "ingest:requests"
#: ingest 维护的每证书队列深度（hash：p0/p1/p2）；api 只读，缺失按 0
QUEUE_DEPTH_KEY: Final = "ingest:licence:{licence_id}:queue_depth"
VERIFY_INTENT: Final = "verify_licence"
#: ``ingest_request_log`` 里算“已发出调用”的状态（queued 未外呼、dropped 被丢弃）
_CALLED_STATUSES: Final = ("done", "failed")

S = DataLicenceStatus


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


def status_view(row: Row[Any] | None) -> dict[str, Any]:
    """``DataLicenceStatus``（契约 §5）。**不含证书值或其任何片段**。"""
    if row is None:
        return not_set_view()
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
    return S.NOT_SET.value if row is None else str(row.status)


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
    carry_pause = old is not None and old.status == S.PAUSED_BY_ADMIN
    if old is not None:
        conn.execute(
            update(udl)
            .where(udl.c.id == old.id)
            .values(deleted_at=now, ciphertext=None, licence_hmac=None, updated_at=now)
        )
    row_id = uuid.uuid4()
    sealed = seal_licence(public_key, licence, user_id=user_id, row_id=row_id, key_version=version)
    status = S.PAUSED_BY_ADMIN if carry_pause else S.PENDING_VERIFICATION
    conn.execute(
        insert(udl).values(
            id=row_id,
            user_id=user_id,
            provider="mairui",
            ciphertext=sealed,
            seal_key_version=version,
            licence_hmac=digest,
            tier=tier,
            has_quant_pro=has_quant_pro,
            expires_on=expires_on,
            status=status.value,
            status_changed_at=now,
            created_at=now,
            updated_at=now,
        )
    )
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
        to_status=status.value,
    )
    row = live_row(conn, user_id)
    assert row is not None  # noqa: S101 - 刚插入
    return SetResult(row=row, verification_id=None if carry_pause else uuid.uuid4())


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


def delete_licence(conn: Connection, *, user_id: uuid.UUID, actor: str = "user") -> bool:
    """软删除并清除密文；未设置时返回 ``False``（路由仍 204，幂等）。"""
    old = live_row(conn, user_id, lock=True)
    if old is None:
        return False
    now = now_utc()
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
