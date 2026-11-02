"""T-B10：研究候选（契约 v0.2.9 §7.7A，T-A11）

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-02 12:00:00+08:00

- ``app.research_candidates`` 加部分唯一索引 ``uq_research_candidates_user_security_open``
  ``(user_id, security_code) WHERE status IN ('researching', 'watching')``：本人同一证券至多一条
  进行中的候选（``dropped``、``planned`` 不算；plan 第 9 节问题 66），并发 ``POST /candidates``
  时只有一个成功，另一个由接口转成 ``409 CONFLICT{field:"security_code", existing_id}``。
- 表、CHECK（status / origin / decision 的取值与顺序）与 ``candidate_versions`` 不可变触发器
  在 0001 已有，本迁移不改。

注意：库中若已有同一用户同一证券多条 researching/watching 的行，建索引会失败；V1 之前没有
写入研究候选的接口，正常不会出现，失败时先人工处理重复行再升级。

downgrade：删除该索引。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_research_candidates_user_security_open"


def upgrade() -> None:
    op.create_index(
        INDEX,
        "research_candidates",
        ["user_id", "security_code"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("status IN ('researching', 'watching')"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="research_candidates", schema="app")
