"""权益取值：未过期覆盖 → 有效订阅套餐值。供多个接口复用，避免复制查询。"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Connection, or_, select

from app.db.tables.membership import entitlement_overrides, plan_entitlements, user_subscriptions


def entitlement_value(
    conn: Connection, user_id: uuid.UUID, key: str, now: dt.datetime
) -> object | None:
    """返回覆盖或唯一套餐值；缺值、多值或不唯一时返回 ``None``（不抛 503）。"""
    override = conn.execute(
        select(entitlement_overrides.c.value).where(
            entitlement_overrides.c.user_id == user_id,
            entitlement_overrides.c.key == key,
            or_(
                entitlement_overrides.c.expires_at.is_(None),
                entitlement_overrides.c.expires_at > now,
            ),
        )
    ).first()
    values = (
        [override.value]
        if override
        else conn.execute(
            select(plan_entitlements.c.value)
            .select_from(
                plan_entitlements.join(
                    user_subscriptions, plan_entitlements.c.plan_id == user_subscriptions.c.plan_id
                )
            )
            .where(
                user_subscriptions.c.user_id == user_id,
                user_subscriptions.c.status == "active",
                user_subscriptions.c.starts_at <= now,
                or_(user_subscriptions.c.ends_at.is_(None), user_subscriptions.c.ends_at > now),
                plan_entitlements.c.key == key,
            )
        )
        .scalars()
        .all()
    )
    if len(values) != 1:
        return None
    return values[0]


def positive_int_entitlement(
    conn: Connection, user_id: uuid.UUID, key: str, now: dt.datetime, fallback: int
) -> int:
    """正整数权益，否则回落 ``fallback``（来自配置，不报 503）。"""
    value = entitlement_value(conn, user_id, key, now)
    if type(value) is not int or value <= 0:
        return fallback
    return value
