"""T-B03d：管理员暂停改为用户级 app.user_data_licence_holds（review M1）

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-02 07:30:00+08:00

- 一行 = 该用户的数据证书被管理员暂停；只有管理员 resume 删除。用户 DELETE 证书后再 PUT，
  新行仍为 ``paused_by_admin``（不投递验证）。
- 回填：现有未删除且 ``status='paused_by_admin'`` 的证书行对应的用户。
- downgrade 删表（暂停仍保留在当前证书行的 status 上，DELETE 后再 PUT 的绕过随之恢复）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "app"


def upgrade() -> None:
    op.create_table(
        "user_data_licence_holds",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "paused_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app.users.id"], name=op.f("fk_user_data_licence_holds_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_data_licence_holds")),
        schema=S,
    )
    op.execute(
        "INSERT INTO app.user_data_licence_holds (user_id, paused_at) "
        "SELECT user_id, status_changed_at FROM app.user_data_licences "
        "WHERE deleted_at IS NULL AND status = 'paused_by_admin' "
        "ON CONFLICT (user_id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("user_data_licence_holds", schema=S)
