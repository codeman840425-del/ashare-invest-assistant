"""T-B45 / 契约 v0.2.6（T-A07）：每用户数据证书

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-02 09:00:00+08:00

plan §2.1B / §3.3、契约 v0.2.6 §7.1 / §7.9：

- 新表 ``app.user_data_licences``（HPKE 密文 + 去重 HMAC；每用户、每 HMAC 在未删除行里
  唯一）。
- 视图 ``app.user_data_licence_status``：去掉 ``ciphertext``、``licence_hmac`` 的全部列
  （api 只读它）。
- 新表 ``ops.data_licence_events``：只追加（``app.reject_mutation`` 触发器）。
- ``ops.ingest_request_log`` 加 ``licence_id``（可空，无外键：hypertable）及索引。
- ``notification_kind`` 加 ``data_licence``：``notifications.kind``、
  ``notification_preferences.kinds`` 两个 CHECK 换新取值集合（只是放宽，旧行不受影响）；
  downgrade 时已有 ``data_licence`` 行则明确失败。
- 0001–0006 不改。
- 数据库角色/列级授权（api 角色不得 SELECT ``ciphertext``）：目前全站只有一个角色，留给运维，
  见 T-B45 报告。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS_OLD = (
    "'suggestion_change', 'invalidation', 'daily_report', 'alert', 'import', 'system', "
    "'reason_released', 'plan_draft_ready', 'plan_triggered', 'strategy_health'"
)
_KINDS_NEW = _KINDS_OLD + ", 'data_licence'"

_STATUSES = (
    "'pending_verification', 'active', 'invalid', 'expired', 'quota_exceeded', "
    "'ip_limited', 'paused_by_admin'"
)
_ALL_STATUSES = "'not_set', " + _STATUSES
_EVENTS = (
    "'set', 'replaced', 'deleted', 'verified', 'invalid', 'expired', 'quota_exceeded', "
    "'ip_limited', 'paused', 'resumed', 'expiry_reminder'"
)

_VIEW_SQL = """
CREATE OR REPLACE VIEW app.user_data_licence_status AS
SELECT id, user_id, provider, seal_key_version, tier, has_quant_pro, expires_on, status,
       status_changed_at, last_verified_at, last_error_code, last_error_at,
       consecutive_failures, paused_until, per_minute_limit_override,
       created_at, updated_at, deleted_at
FROM app.user_data_licences
"""

_EVENTS_TRIGGER_SQL = """
CREATE TRIGGER trg_data_licence_events_immutable BEFORE UPDATE OR DELETE
ON ops.data_licence_events FOR EACH ROW EXECUTE FUNCTION app.reject_mutation()
"""

_FAIL_IF_DATA_LICENCE_KIND_SQL = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM app.notifications WHERE kind = 'data_licence')
     OR EXISTS (SELECT 1 FROM app.notification_preferences
                WHERE 'data_licence' = ANY (kinds)) THEN
    RAISE EXCEPTION '0007 downgrade：仍有 notification kind=data_licence 的行，需人工处理'
      USING ERRCODE = 'check_violation';
  END IF;
END $$;
"""


def _set_kind_checks(values: str) -> None:
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check", schema="app")
    op.create_check_constraint(
        op.f("ck_notifications_kind"), "notifications", f"kind IN ({values})", schema="app"
    )
    op.drop_constraint(
        op.f("ck_notification_preferences_kinds"),
        "notification_preferences",
        type_="check",
        schema="app",
    )
    op.create_check_constraint(
        op.f("ck_notification_preferences_kinds"),
        "notification_preferences",
        f"kinds <@ ARRAY[{values}]::text[]",
        schema="app",
    )


def upgrade() -> None:
    op.create_table(
        "user_data_licences",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), server_default=sa.text("'mairui'"), nullable=False),
        sa.Column(
            "ciphertext",
            postgresql.BYTEA(),
            nullable=True,
            comment="HPKE 密文（enc||ct）；删除时置 NULL",
        ),
        sa.Column("seal_key_version", sa.Integer(), nullable=False),
        sa.Column(
            "licence_hmac",
            postgresql.BYTEA(),
            nullable=True,
            comment="去重 HMAC；删除时置 NULL；不对外",
        ),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("has_quant_pro", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("per_minute_limit_override", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider IN ('mairui')", name=op.f("ck_user_data_licences_provider")),
        sa.CheckConstraint(
            "tier IN ('free', 'trial', 'monthly', 'annual', 'diamond', 'other')",
            name=op.f("ck_user_data_licences_tier"),
        ),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name=op.f("ck_user_data_licences_status")),
        sa.CheckConstraint(
            "last_error_code IN ('101', '102', '103', '429', '503', 'network', 'http_5xx')",
            name=op.f("ck_user_data_licences_last_error_code"),
        ),
        sa.CheckConstraint(
            "seal_key_version >= 1", name=op.f("ck_user_data_licences_seal_key_version_positive")
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name=op.f("ck_user_data_licences_consecutive_failures_nonneg"),
        ),
        sa.CheckConstraint(
            "per_minute_limit_override IS NULL OR per_minute_limit_override > 0",
            name=op.f("ck_user_data_licences_per_minute_limit_override_positive"),
        ),
        sa.CheckConstraint(
            "deleted_at IS NOT NULL OR (ciphertext IS NOT NULL AND licence_hmac IS NOT NULL)",
            name=op.f("ck_user_data_licences_live_has_secret"),
        ),
        sa.CheckConstraint(
            "deleted_at IS NULL OR (ciphertext IS NULL AND licence_hmac IS NULL)",
            name=op.f("ck_user_data_licences_deleted_wiped"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app.users.id"], name=op.f("fk_user_data_licences_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_data_licences")),
        schema="app",
    )
    op.create_index(
        "uq_user_data_licences_user_live",
        "user_data_licences",
        ["user_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_user_data_licences_hmac_live",
        "user_data_licences",
        ["licence_hmac"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(_VIEW_SQL)

    op.create_table(
        "data_licence_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("licence_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=True),
        sa.Column("upstream_code", sa.Text(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(f"event IN ({_EVENTS})", name=op.f("ck_data_licence_events_event")),
        sa.CheckConstraint(
            "actor IN ('user', 'admin', 'ingest')", name=op.f("ck_data_licence_events_actor")
        ),
        sa.CheckConstraint(
            f"from_status IN ({_ALL_STATUSES})", name=op.f("ck_data_licence_events_from_status")
        ),
        sa.CheckConstraint(
            f"to_status IN ({_ALL_STATUSES})", name=op.f("ck_data_licence_events_to_status")
        ),
        sa.ForeignKeyConstraint(
            ["licence_id"],
            ["app.user_data_licences.id"],
            name=op.f("fk_data_licence_events_licence_id_user_data_licences"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app.users.id"], name=op.f("fk_data_licence_events_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_licence_events")),
        schema="ops",
        comment="只追加（触发器拒绝 UPDATE/DELETE）；不含证书值",
    )
    op.create_index(
        "ix_data_licence_events_licence_at",
        "data_licence_events",
        ["licence_id", sa.literal_column("at DESC")],
        unique=False,
        schema="ops",
    )
    op.execute(_EVENTS_TRIGGER_SQL)

    op.add_column("ingest_request_log", sa.Column("licence_id", sa.UUID()), schema="ops")
    op.create_index(
        "ix_ingest_request_log_licence_requested",
        "ingest_request_log",
        ["licence_id", sa.literal_column("requested_at DESC")],
        unique=False,
        schema="ops",
    )

    _set_kind_checks(_KINDS_NEW)


def downgrade() -> None:
    op.execute(_FAIL_IF_DATA_LICENCE_KIND_SQL)
    _set_kind_checks(_KINDS_OLD)
    op.drop_index("ix_ingest_request_log_licence_requested", "ingest_request_log", schema="ops")
    op.drop_column("ingest_request_log", "licence_id", schema="ops")
    op.drop_table("data_licence_events", schema="ops")
    op.execute("DROP VIEW IF EXISTS app.user_data_licence_status")
    op.drop_index("uq_user_data_licences_hmac_live", "user_data_licences", schema="app")
    op.drop_index("uq_user_data_licences_user_live", "user_data_licences", schema="app")
    op.drop_table("user_data_licences", schema="app")
