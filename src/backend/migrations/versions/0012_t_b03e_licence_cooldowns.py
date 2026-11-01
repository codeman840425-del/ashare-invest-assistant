"""T-B03e：删除后重提不跳过冷却（契约 v0.2.8 #13 补充，T-B04a-x）

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-02 07:41:00+08:00

- 新表 ``app.user_data_licence_cooldowns``：冷却中（quota_exceeded / ip_limited / active 且
  paused_until 未到期）DELETE 证书时，记下带密钥的证书指纹（HMAC，见 app.licences.seal
  ``cooldown_fingerprint``；不是明文，也不等于去重 HMAC）与删除前的 status、paused_until、
  last_error_*、consecutive_failures；到期前 PUT 同一证书 → 恢复（202，不验证）。每用户最多一行。

downgrade：删表（删除后重提跳过冷却的旧行为随之恢复）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "app"
ERROR_CODES = ("101", "102", "103", "429", "503", "network", "http_5xx")


def upgrade() -> None:
    codes = ", ".join(f"'{c}'" for c in ERROR_CODES)
    op.create_table(
        "user_data_licence_cooldowns",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "fingerprint",
            postgresql.BYTEA(),
            nullable=False,
            comment="HMAC(K_cooldown, user_id||licence)",
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "deleted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'quota_exceeded', 'ip_limited')",
            name=op.f("ck_user_data_licence_cooldowns_status"),
        ),
        sa.CheckConstraint(
            f"last_error_code IN ({codes})",
            name=op.f("ck_user_data_licence_cooldowns_last_error_code"),
        ),
        sa.CheckConstraint(
            "octet_length(fingerprint) = 32",
            name=op.f("ck_user_data_licence_cooldowns_fingerprint_len"),
        ),
        sa.CheckConstraint(
            "status <> 'active' OR paused_until IS NOT NULL",
            name=op.f("ck_user_data_licence_cooldowns_active_needs_paused_until"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app.users.id"],
            name=op.f("fk_user_data_licence_cooldowns_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_data_licence_cooldowns")),
        schema=S,
    )


def downgrade() -> None:
    op.drop_table("user_data_licence_cooldowns", schema=S)
