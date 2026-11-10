"""T-B133（T1）：market.daily_bars 的 source CHECK 加入 tdx_local。

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-10 10:50:00-07:00

契约：``git show 362ad41:docs/contracts/daily-bars-tdx.md`` §6。
upgrade：``ck_daily_bars_source_allowed`` 改为 source 为 NULL 或属于 fake、mairui、tdx_local；
不改已有行，不加列。
downgrade：存在 source 为 tdx_local 的行时拒绝；否则恢复 0032 的约束。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "market"
TABLE = "daily_bars"
CHECK = "ck_daily_bars_source_allowed"
# op.create_check_constraint 经命名约定拼成 ck_daily_bars_<name>（同 0032）。
_NAME = "source_allowed"


def upgrade() -> None:
    op.drop_constraint(CHECK, TABLE, schema=SCHEMA)
    op.create_check_constraint(
        _NAME,
        TABLE,
        "source IS NULL OR source IN ('fake', 'mairui', 'tdx_local')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT count(*) FROM market.daily_bars WHERE source = 'tdx_local'")
    ).scalar_one()
    if int(rows) > 0:
        raise RuntimeError(
            f"refusing downgrade 0033: {int(rows)} daily_bars rows have source tdx_local"
        )
    op.drop_constraint(CHECK, TABLE, schema=SCHEMA)
    op.create_check_constraint(
        _NAME,
        TABLE,
        "source IS NULL OR source IN ('fake', 'mairui')",
        schema=SCHEMA,
    )
