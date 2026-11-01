"""T-B03c：邀请码表 app.invite_codes（plan §3.3 / §6.1 invite.*，契约 v0.2.3 #27、§7.9）

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-02 06:10:00+08:00

- ``code_hash``：``HMAC-SHA256(APP_MASTER_KEY, 归一化邀请码)``（十六进制），唯一；明文不入库。
- 状态由字段推导（active / used / expired / revoked），不物理删除。
- V1 只支持单次使用：``max_uses`` 恒为 1（CHECK）；核验与建用户同事务，用条件 UPDATE
  ``used_count`` 防并发重复使用。
- 0001–0007 不改。downgrade 删表（已发放的邀请码随之丢失）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "app"


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    tstz = sa.DateTime(timezone=True)
    op.create_table(
        "invite_codes",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("created_by", uuid, nullable=False),
        sa.Column("created_at", tstz, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", tstz, nullable=False),
        sa.Column("max_uses", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("used_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("used_by", uuid, nullable=True),
        sa.Column("used_at", tstz, nullable=True),
        sa.Column("revoked_at", tstz, nullable=True),
        sa.Column("revoked_by", uuid, nullable=True),
        sa.Column("bound_username", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("max_uses = 1", name=op.f("ck_invite_codes_max_uses_v1")),
        sa.CheckConstraint(
            "used_count >= 0 AND used_count <= max_uses",
            name=op.f("ck_invite_codes_used_count_range"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_invite_codes_expires_after_created")
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)",
            name=op.f("ck_invite_codes_revoked_pair"),
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 200", name=op.f("ck_invite_codes_note_len")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], [f"{S}.users.id"], name=op.f("fk_invite_codes_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["used_by"], [f"{S}.users.id"], name=op.f("fk_invite_codes_used_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"], [f"{S}.users.id"], name=op.f("fk_invite_codes_revoked_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invite_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_invite_codes_code_hash")),
        schema=S,
        comment=(
            "邀请码：HMAC-SHA256(APP_MASTER_KEY, 归一化码)，明文不入库；"
            "状态 active/used/expired/revoked 由字段推导"
        ),
    )


def downgrade() -> None:
    op.drop_table("invite_codes", schema=S)
