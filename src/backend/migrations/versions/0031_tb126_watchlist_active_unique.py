"""T-B126：自选有效行部分唯一索引 ``uq_watchlist_items_user_code_active``。

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-10 20:45:00+08:00

在 ``app.watchlist_items`` 上为 ``(user_id, security_code) WHERE removed_at IS NULL``
建立唯一索引。不加列、不改默认值、不改已有行。升级前若已有有效重复组则中止并报告组数
（不打印代码或用户标识），不自动去重。

downgrade：删除该索引。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_watchlist_items_user_code_active"


def upgrade() -> None:
    conn = op.get_bind()
    groups = conn.execute(
        sa.text(
            """
            SELECT count(*) FROM (
                SELECT 1
                FROM app.watchlist_items
                WHERE removed_at IS NULL
                GROUP BY user_id, security_code
                HAVING count(*) > 1
            ) duplicate_groups
            """
        )
    ).scalar_one()
    if int(groups) > 0:
        raise RuntimeError(
            f"refusing {INDEX}: {int(groups)} duplicate active groups; "
            "resolve duplicates before upgrade"
        )
    op.create_index(
        INDEX,
        "watchlist_items",
        ["user_id", "security_code"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("removed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="watchlist_items", schema="app")
