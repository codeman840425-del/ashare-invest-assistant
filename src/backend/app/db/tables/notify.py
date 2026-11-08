"""站内通知与外部渠道（plan §3.3「通知」、§2.9；契约 Notification、channel 枚举）。

契约 ``Notification.target{type,id,route}`` 取代 plan 的 ``link/ref_type/ref_id``；
渠道按契约 ``channel``（in_app/email/wecom_app）；plan 列的
wecom_bot/mp_template/serverchan 契约未收录，不建。
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Index,
    PrimaryKeyConstraint,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA

from app.db.base import (
    APP,
    array_subset,
    created_at,
    integer,
    jsonb,
    metadata,
    one_of,
    pk_uuid,
    text_array,
    ts,
    txt,
    user_fk,
    uuid_col,
)
from app.schemas.enums import Channel, NotificationKind, NotificationTargetType, Severity

notifications = Table(
    "notifications",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("kind", nullable=False),
    txt("severity", nullable=False),
    txt("title", nullable=False),
    txt("body"),
    txt("security_code"),
    txt("target_type", nullable=False, server_default=text("'none'")),
    txt("target_id"),
    txt("target_route"),
    txt("dedup_key"),
    ts("read_at"),
    created_at(),
    integer("version", nullable=False, server_default=text("1")),
    CheckConstraint("version >= 1", name="version_positive"),
    integer("merged_count", nullable=False, server_default=text("1")),
    ts("updated_at"),
    jsonb("refs", nullable=False, server_default=text("'[]'::jsonb")),
    one_of("kind", NotificationKind),
    one_of("severity", Severity),
    one_of("target_type", NotificationTargetType),
    UniqueConstraint("user_id", "dedup_key"),
    schema=APP,
)
Index(
    "ix_notifications_user_read_created",
    notifications.c.user_id,
    notifications.c.read_at.asc().nulls_first(),
    notifications.c.created_at.desc(),
)

notification_channel_bindings = Table(
    "notification_channel_bindings",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("channel", nullable=False),
    Column("target_ciphertext", BYTEA),
    txt("target_masked"),
    txt("status", nullable=False, server_default=text("'pending_verify'")),
    ts("verified_at"),
    created_at(),
    one_of("channel", Channel),
    one_of("status", ["pending_verify", "active", "disabled", "failed"]),
    schema=APP,
)

notification_preferences = Table(
    "notification_preferences",
    metadata,
    user_fk(),
    txt("channel", nullable=False),
    text_array("kinds"),
    txt("min_severity", nullable=False, server_default=text("'info'")),
    txt("detail_level", nullable=False, server_default=text("'summary'")),
    jsonb("quiet_hours"),
    integer("rate_per_min"),
    integer("rate_per_hour"),
    txt("digest_time"),
    PrimaryKeyConstraint("user_id", "channel"),
    one_of("channel", Channel),
    one_of("min_severity", Severity),
    one_of("detail_level", ["full", "summary", "ping"]),
    array_subset("kinds", NotificationKind),
    schema=APP,
)

notification_deliveries = Table(
    "notification_deliveries",
    metadata,
    pk_uuid(),
    uuid_col("notification_id", nullable=False, fk="app.notifications.id"),
    uuid_col("binding_id", fk="app.notification_channel_bindings.id"),
    txt("channel", nullable=False),
    txt("status", nullable=False, server_default=text("'queued'")),
    integer("attempts", nullable=False, server_default=text("0")),
    ts("next_retry_at"),
    txt("provider_msg_id"),
    txt("error_code"),
    txt("error"),
    ts("sent_at"),
    one_of("channel", Channel),
    one_of("status", ["queued", "sent", "failed", "retrying", "dropped"]),
    schema=APP,
)

notification_refs = Table(
    "notification_refs",
    metadata,
    uuid_col("notification_id", nullable=False, fk="app.notifications.id"),
    txt("ref_type", nullable=False),
    CheckConstraint("ref_type IN ('signal', 'plan_condition')", name="ref_type_enum"),
    txt("ref_id", nullable=False),
    ts("at", nullable=False),
    PrimaryKeyConstraint("notification_id", "ref_type", "ref_id"),
    schema=APP,
)
