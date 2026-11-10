"""T-B127：market.daily_bars 增加可空来源与停牌占位列。

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-10 21:10:00+08:00

新增可空列 ``pre_close``、``is_suspended``、``source``、``source_licence_id``（无外键，
不进主键）。``source`` 有 CHECK：NULL 或 ``fake`` / ``mairui``。不改已有行，不加默认值。

downgrade：若存在 ``source IS NOT NULL`` 的行则拒绝；否则删约束并删列。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "market"
TABLE = "daily_bars"
CHECK = "ck_daily_bars_source_allowed"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("pre_close", sa.Numeric(20, 4), nullable=True), schema=SCHEMA)
    op.add_column(TABLE, sa.Column("is_suspended", sa.Boolean(), nullable=True), schema=SCHEMA)
    op.add_column(TABLE, sa.Column("source", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column(
        TABLE,
        sa.Column("source_licence_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "source_allowed",
        TABLE,
        "source IS NULL OR source IN ('fake', 'mairui')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    conn = op.get_bind()
    sourced = conn.execute(
        sa.text("SELECT count(*) FROM market.daily_bars WHERE source IS NOT NULL")
    ).scalar_one()
    if int(sourced) > 0:
        raise RuntimeError(
            f"refusing downgrade 0032: {int(sourced)} daily_bars rows have source; "
            "clear sourced rows before downgrade"
        )
    op.drop_constraint(CHECK, TABLE, schema=SCHEMA)
    op.drop_column(TABLE, "source_licence_id", schema=SCHEMA)
    op.drop_column(TABLE, "source", schema=SCHEMA)
    op.drop_column(TABLE, "is_suspended", schema=SCHEMA)
    op.drop_column(TABLE, "pre_close", schema=SCHEMA)
