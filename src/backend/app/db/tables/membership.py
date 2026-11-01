"""会员预留（不含支付）（plan §3.3「会员预留」）。"""

from __future__ import annotations

from sqlalchemy import PrimaryKeyConstraint, Table, text

from app.db.base import (
    APP,
    integer,
    jsonb,
    metadata,
    one_of,
    pk_uuid,
    ts,
    txt,
    user_fk,
    uuid_col,
)

plans = Table(
    "plans",
    metadata,
    pk_uuid(),
    txt("code", nullable=False, unique=True),
    txt("name", nullable=False),
    txt("status", nullable=False, server_default=text("'active'")),
    txt("display_price_note"),
    integer("sort", nullable=False, server_default=text("0")),
    one_of("status", ["active", "hidden", "retired"]),
    schema=APP,
    comment="会员档位（不是行动计划；行动计划见 action_plans）",
)

plan_entitlements = Table(
    "plan_entitlements",
    metadata,
    uuid_col("plan_id", nullable=False, fk="app.plans.id"),
    txt("key", nullable=False),
    jsonb("value", nullable=False),
    PrimaryKeyConstraint("plan_id", "key"),
    schema=APP,
)

user_subscriptions = Table(
    "user_subscriptions",
    metadata,
    pk_uuid(),
    user_fk(),
    uuid_col("plan_id", nullable=False, fk="app.plans.id"),
    txt("status", nullable=False, server_default=text("'active'")),
    ts("starts_at", nullable=False, default_now=True),
    ts("ends_at"),
    txt("source", nullable=False, server_default=text("'manual_admin'")),
    txt("note"),
    uuid_col("created_by", fk="app.users.id"),
    one_of("status", ["active", "expired", "cancelled"]),
    one_of("source", ["manual_admin", "payment_reserved"]),
    schema=APP,
)

entitlement_overrides = Table(
    "entitlement_overrides",
    metadata,
    user_fk(),
    txt("key", nullable=False),
    jsonb("value", nullable=False),
    txt("reason"),
    ts("expires_at"),
    uuid_col("created_by", fk="app.users.id"),
    PrimaryKeyConstraint("user_id", "key"),
    schema=APP,
)
