"""T-B133（M1）：minute_bars 来源扩展与 5 分钟线新表 minute5_bars。

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-10 10:55:00-07:00

契约：``git show 362ad41:docs/contracts/intraday-bars.md`` §1.3、§2.2、§5.1 M1。
upgrade：
- ``market.minute_bars`` 的 source CHECK 加入 mairui 与 tdx_local
  （保留基线 pro_latest、pro_history）；
- 加可空列 source_licence_id（口径同日线 0032，无外键）；不改主键、不改已有行；
- 新表 ``market.minute5_bars``：列与 minute_bars 相同，主键 (code, ts)，
  hypertable 每 7 天一个 chunk。
压缩策略不在迁移里建（基线 0001 同样只建 hypertable，压缩由运维脚本负责）。
downgrade：minute_bars 有 mairui 或 tdx_local 行，或 minute5_bars 非空时拒绝。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "market"
MINUTE = "minute_bars"
MINUTE5 = "minute5_bars"
CHECK = "ck_minute_bars_source"
_BASE_SOURCES = "source IN ('pro_latest', 'pro_history')"
_NEW_SOURCES = "source IN ('pro_latest', 'pro_history', 'mairui', 'tdx_local')"


def upgrade() -> None:
    op.drop_constraint(CHECK, MINUTE, schema=SCHEMA)
    op.create_check_constraint("source", MINUTE, _NEW_SOURCES, schema=SCHEMA)
    op.add_column(
        MINUTE,
        sa.Column("source_licence_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_table(
        MINUTE5,
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="bar 结束时间：09:35 表示 09:30–09:35",
        ),
        sa.Column("open", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("high", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("low", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("close", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("volume", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("source_licence_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_NEW_SOURCES, name=op.f("ck_minute5_bars_source")),
        sa.PrimaryKeyConstraint("code", "ts", name=op.f("pk_minute5_bars")),
        schema=SCHEMA,
        comment="hypertable（ts，chunk 7 天）；ts 为 bar 结束时间；只存通达信 .lc5 历史",
    )
    op.execute(
        "SELECT create_hypertable('market.minute5_bars', by_range('ts', INTERVAL '7 days'), "
        "create_default_indexes => false, if_not_exists => true)"
    )


def downgrade() -> None:
    conn = op.get_bind()
    sourced = conn.execute(
        sa.text("SELECT count(*) FROM market.minute_bars WHERE source IN ('mairui', 'tdx_local')")
    ).scalar_one()
    five = conn.execute(sa.text("SELECT count(*) FROM market.minute5_bars")).scalar_one()
    if int(sourced) > 0 or int(five) > 0:
        raise RuntimeError(
            f"refusing downgrade 0034: minute_bars mairui/tdx_local rows={int(sourced)}, "
            f"minute5_bars rows={int(five)}"
        )
    op.drop_table(MINUTE5, schema=SCHEMA)
    op.drop_column(MINUTE, "source_licence_id", schema=SCHEMA)
    op.drop_constraint(CHECK, MINUTE, schema=SCHEMA)
    op.create_check_constraint("source", MINUTE, _BASE_SOURCES, schema=SCHEMA)
