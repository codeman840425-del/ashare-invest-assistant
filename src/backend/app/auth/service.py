"""认证与画像的数据库操作（T-B03）。路由层只做 HTTP 适配，这里不依赖 FastAPI。"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, Row, func, insert, select, update

from app.db.tables.users import account_reviews, audit_logs, user_profiles, users

BEIJING = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")


def bj(value: dt.datetime | None) -> str | None:
    """契约约定时间以 +08:00 输出（秒精度）。"""
    if value is None:
        return None
    return value.astimezone(BEIJING).replace(microsecond=0).isoformat()


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def find_user_by_username(conn: Connection, username: str) -> Row[Any] | None:
    return conn.execute(
        select(users).where(users.c.username == username, users.c.deleted_at.is_(None))
    ).first()


def username_taken(conn: Connection, username: str) -> bool:
    """含已注销用户：``username`` 全表唯一（DB 约束），注销后的名字不复用。"""
    return conn.execute(select(users.c.id).where(users.c.username == username)).first() is not None


def latest_reject_reason(conn: Connection, user_id: uuid.UUID) -> str | None:
    row = conn.execute(
        select(account_reviews.c.reason)
        .where(account_reviews.c.user_id == user_id, account_reviews.c.action == "reject")
        .order_by(account_reviews.c.created_at.desc())
        .limit(1)
    ).first()
    return None if row is None else row.reason


def audit(
    conn: Connection,
    *,
    action: str,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: Mapping[str, Any] | None = None,
    ip_hash: str | None = None,
) -> None:
    conn.execute(
        insert(audit_logs).values(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=dict(detail) if detail is not None else None,
            ip_hash=ip_hash,
        )
    )


def latest_profile(conn: Connection, user_id: uuid.UUID) -> Row[Any] | None:
    return conn.execute(
        select(user_profiles)
        .where(user_profiles.c.user_id == user_id)
        .order_by(user_profiles.c.version_no.desc())
        .limit(1)
    ).first()


_PROFILE_FIELDS = (
    "horizon_pref",
    "effort",
    "risk_tolerance",
    "experience",
    "max_single_position_pct",
    "capital_range",
    "max_drawdown_pct",
    "focus_areas",
    "confirmed_at",
)


def insert_profile_version(
    conn: Connection, user_id: uuid.UUID, changes: Mapping[str, Any]
) -> Row[Any]:
    """追加一版画像：未给出的字段沿用上一版（含 plan 里契约未暴露的列）。

    ``version_no`` 在同一事务内按 ``max + 1`` 取；并发写同一用户由 ``(user_id, version_no)``
    唯一约束兜底，调用方把 ``IntegrityError`` 映射为 ``409 VERSION_CONFLICT``。
    """
    prev = latest_profile(conn, user_id)
    values: dict[str, Any] = {
        f: (getattr(prev, f) if prev is not None else None) for f in _PROFILE_FIELDS
    }
    values.update(changes)
    values["user_id"] = user_id
    values["version_no"] = 1 if prev is None else int(prev.version_no) + 1
    row = conn.execute(insert(user_profiles).values(**values).returning(user_profiles)).one()
    return row


def profile_view(row: Row[Any]) -> dict[str, Any]:
    pct = row.max_single_position_pct
    return {
        "version_no": int(row.version_no),
        "horizon_pref": list(row.horizon_pref or []),
        "effort": row.effort,
        "risk_tolerance": row.risk_tolerance,
        "experience": row.experience,
        "max_single_position_pct": None if pct is None else f"{Decimal(pct):.2f}",
    }


def set_password_hash(
    conn: Connection, user_id: uuid.UUID, password_hash: str, *, changed: bool
) -> None:
    values: dict[str, Any] = {"password_hash": password_hash}
    if changed:
        values["password_changed_at"] = func.now()
    conn.execute(update(users).where(users.c.id == user_id).values(**values))
