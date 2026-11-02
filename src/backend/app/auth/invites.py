"""邀请码（T-B03c；plan §3.6 / §6.1 ``invite.*``，契约 v0.2.3 #27、§7.9）。

- 明文：``invite.code_bytes`` 个随机字节（``secrets``）的 Crockford Base32（无填充）；
  16 字节 → 26 字符，显示时每 4 位加连字符。
- 归一化：去掉连字符与首尾空白、转大写；之后必须是 26 位合法 Crockford 字符，否则直接判无效
  （不查库）。
- 入库：``HMAC-SHA256(APP_MASTER_KEY, 归一化码)`` 十六进制；明文只在创建响应里出现一次。
- 核验：与建用户同一事务，条件 UPDATE ``used_count``（未吊销、未过期、未用完、绑定用户名相符）；
  任何失败统一为 ``400 VALIDATION_ERROR {fields:[{field:"invite_code", issue:"invalid"}]}``。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
import uuid
from typing import Any, Final, Literal

from sqlalchemy import Connection, Row, and_, insert, or_, update

from app.common.errors import AppError, ErrorCode
from app.config import Settings, master_key_bytes
from app.db.tables.users import invite_codes

CROCKFORD: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_SET: Final = frozenset(CROCKFORD)
GROUP: Final = 4

InviteStatus = Literal["active", "used", "expired", "revoked"]

#: 未设置 APP_MASTER_KEY（只有 local/test 允许）时的进程内临时密钥：重启后旧码失效
_EPHEMERAL_KEY: Final = secrets.token_bytes(32)


def b32_len(code_bytes: int) -> int:
    return -(-code_bytes * 8 // 5)


def encode_crockford(raw: bytes) -> str:
    n, bits = int.from_bytes(raw, "big"), len(raw) * 8
    length = b32_len(len(raw))
    n <<= length * 5 - bits  # 末尾补零位到 5 的倍数
    return "".join(CROCKFORD[(n >> (5 * i)) & 31] for i in reversed(range(length)))


def display(code: str) -> str:
    return "-".join(code[i : i + GROUP] for i in range(0, len(code), GROUP))


def normalize(text: str, code_bytes: int) -> str | None:
    """去连字符与首尾空白、转大写；格式不对返回 ``None``。"""
    code = text.strip().replace("-", "").upper()
    if len(code) != b32_len(code_bytes) or not set(code) <= _CROCKFORD_SET:
        return None
    return code


def _key(settings: Settings) -> bytes:
    # T-B49：非 local/test 无主密钥 → MasterKeyMissingError（不回退到临时密钥）
    master = master_key_bytes(settings)
    return _EPHEMERAL_KEY if master is None else master


def code_hash(settings: Settings, normalized: str) -> str:
    return hmac.new(_key(settings), normalized.encode("ascii"), hashlib.sha256).hexdigest()


def new_code(code_bytes: int) -> str:
    return encode_crockford(secrets.token_bytes(code_bytes))


def status_of(row: Row[Any], now: dt.datetime) -> InviteStatus:
    """优先级：revoked > used > expired > active。"""
    if row.revoked_at is not None:
        return "revoked"
    if row.used_count >= row.max_uses:
        return "used"
    if row.expires_at <= now:
        return "expired"
    return "active"


def invalid_invite() -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        details={"fields": [{"field": "invite_code", "issue": "invalid"}]},
    )


def create(
    conn: Connection,
    settings: Settings,
    *,
    created_by: uuid.UUID,
    now: dt.datetime,
    ttl_h: int,
    bound_username: str | None,
    note: str | None,
) -> tuple[Row[Any], str]:
    """插入一条邀请码，返回 ``(行, 显示用明文)``；明文不落库、不记日志。"""
    code_bytes = settings.business.auth.invite.code_bytes
    code = new_code(code_bytes)
    row = conn.execute(
        insert(invite_codes)
        .values(
            code_hash=code_hash(settings, code),
            created_by=created_by,
            created_at=now,
            expires_at=now + dt.timedelta(hours=ttl_h),
            max_uses=settings.business.auth.invite.max_uses,
            bound_username=bound_username,
            note=note,
        )
        .returning(invite_codes)
    ).one()
    return row, display(code)


def redeem(
    conn: Connection,
    settings: Settings,
    *,
    raw_code: str | None,
    username: str,
    now: dt.datetime,
) -> uuid.UUID:
    """条件 UPDATE 占用一次；失败一律 :func:`invalid_invite`。调用方须在同一事务里建用户，
    之后用 :func:`mark_used_by` 回填 ``used_by``；事务回滚则占用一并回滚。"""
    normalized = (
        None if raw_code is None else normalize(raw_code, settings.business.auth.invite.code_bytes)
    )
    if normalized is None:
        raise invalid_invite()
    c = invite_codes.c
    invite_id = conn.execute(
        update(invite_codes)
        .where(
            c.code_hash == code_hash(settings, normalized),
            c.revoked_at.is_(None),
            c.used_count < c.max_uses,
            c.expires_at > now,
            or_(c.bound_username.is_(None), c.bound_username == username),
        )
        .values(used_count=c.used_count + 1, used_at=now)
        .returning(c.id)
    ).scalar_one_or_none()
    if invite_id is None:
        raise invalid_invite()
    return uuid.UUID(str(invite_id))


def mark_used_by(conn: Connection, invite_id: uuid.UUID, user_id: uuid.UUID) -> None:
    conn.execute(update(invite_codes).where(invite_codes.c.id == invite_id).values(used_by=user_id))


def revoke(
    conn: Connection, *, invite_id: uuid.UUID, admin_id: uuid.UUID, now: dt.datetime
) -> bool:
    """吊销未用且未吊销的码（过期的码也可吊销）；返回是否改动。"""
    c = invite_codes.c
    hit = conn.execute(
        update(invite_codes)
        .where(and_(c.id == invite_id, c.revoked_at.is_(None), c.used_count < c.max_uses))
        .values(revoked_at=now, revoked_by=admin_id)
        .returning(c.id)
    ).first()
    return hit is not None
