"""T-B46：导入批次补列、成交价格精度（/imports、/trades、/portfolio）

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-02 08:05:00+08:00

- ``app.import_batches`` 加契约 §7.2 ``GET /imports/{id}`` 需要、旧表没有的列：
  ``kind``（trades / positions，默认 trades）、``encoding_confidence``、``format_score``、
  ``detected_columns``（text[]）。统计仍放在已有的 ``summary`` jsonb。
- ``app.trades.price``、``app.holdings.avg_cost``：numeric(20,4) → numeric（不限精度）
  （plan §3.5A：成交价格最多 8 位小数，不四舍五入；应用层按 8 位小数写入。数值列约定为
  numeric(20,4) 或不限精度，见 tests/backend/unit/test_db_metadata.py）。只放宽精度，不丢数据。
- ``app.import_rows.kind`` 加 ``snapshot_position``（持仓快照文件的明细行，expected.json）。
- ``app.trades`` 的去重唯一约束 ``uq_trades_account_id_dedup_key`` 改为只约束未作废记录的
  部分唯一索引 ``uq_trades_account_id_dedup_key_live``（``WHERE voided_at IS NULL``）：
  批次回滚只作废成交（触发器禁止删除），回滚后重新导入同一文件必须能写入。
- 可转债持仓展示（plan 第 9 节问题 63）不需要新列：
  按代码段在读取时判定（见 app/domain/portfolio.py）。

downgrade：已作废且与其他记录同键的成交把 dedup_key 置空后恢复整表唯一约束；
删除 snapshot_position 明细行后 kind 约束改回；删列；
精度改回 numeric(20,4)（PostgreSQL 会四舍五入到 4 位）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "app"


def upgrade() -> None:
    op.add_column(
        "import_batches",
        sa.Column("kind", sa.Text(), server_default=sa.text("'trades'"), nullable=False),
        schema=S,
    )
    op.add_column("import_batches", sa.Column("encoding_confidence", sa.Numeric()), schema=S)
    op.add_column("import_batches", sa.Column("format_score", sa.Numeric()), schema=S)
    op.add_column(
        "import_batches",
        sa.Column("detected_columns", postgresql.ARRAY(sa.Text())),
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_import_batches_kind"),
        "import_batches",
        "kind IN ('trades', 'positions')",
        schema=S,
    )
    op.alter_column(
        "trades",
        "price",
        type_=sa.Numeric(),
        existing_type=sa.Numeric(20, 4),
        existing_nullable=False,
        schema=S,
    )
    op.alter_column(
        "holdings",
        "avg_cost",
        type_=sa.Numeric(),
        existing_type=sa.Numeric(20, 4),
        existing_nullable=True,
        schema=S,
    )
    op.drop_constraint(op.f("ck_import_rows_kind"), "import_rows", schema=S, type_="check")
    op.create_check_constraint(
        op.f("ck_import_rows_kind"),
        "import_rows",
        "kind IN ('trade', 'event', 'ignored', 'snapshot_position')",
        schema=S,
    )
    op.drop_constraint(op.f("uq_trades_account_id_dedup_key"), "trades", schema=S, type_="unique")
    op.create_index(
        "uq_trades_account_id_dedup_key_live",
        "trades",
        ["account_id", "dedup_key"],
        unique=True,
        schema=S,
        postgresql_where=sa.text("voided_at IS NULL"),
    )


def downgrade() -> None:
    # 回滚重导会留下“已作废 + 未作废”同键的成交；整表唯一约束容不下它们。
    # 已作废记录的 dedup_key 只用于去重，置空不影响账目（trades 只允许改作废列，临时关掉该触发器）。
    op.execute("ALTER TABLE app.trades DISABLE TRIGGER trg_trades_restrict_update")
    op.execute(
        "UPDATE app.trades t SET dedup_key = NULL "
        "WHERE t.voided_at IS NOT NULL AND t.dedup_key IS NOT NULL AND EXISTS ("
        "SELECT 1 FROM app.trades o WHERE o.account_id = t.account_id "
        "AND o.dedup_key = t.dedup_key AND o.id <> t.id)"
    )
    op.execute("ALTER TABLE app.trades ENABLE TRIGGER trg_trades_restrict_update")
    # 0013 没有持仓快照明细行这一类；快照本身在 broker_position_snapshots，不受影响。
    op.execute("DELETE FROM app.import_rows WHERE kind = 'snapshot_position'")
    op.drop_index("uq_trades_account_id_dedup_key_live", table_name="trades", schema=S)
    op.create_unique_constraint(
        op.f("uq_trades_account_id_dedup_key"), "trades", ["account_id", "dedup_key"], schema=S
    )
    op.drop_constraint(op.f("ck_import_rows_kind"), "import_rows", schema=S, type_="check")
    op.create_check_constraint(
        op.f("ck_import_rows_kind"),
        "import_rows",
        "kind IN ('trade', 'event', 'ignored')",
        schema=S,
    )
    op.alter_column(
        "holdings",
        "avg_cost",
        type_=sa.Numeric(20, 4),
        existing_type=sa.Numeric(),
        existing_nullable=True,
        schema=S,
    )
    op.alter_column(
        "trades",
        "price",
        type_=sa.Numeric(20, 4),
        existing_type=sa.Numeric(),
        existing_nullable=False,
        schema=S,
    )
    op.drop_constraint(op.f("ck_import_batches_kind"), "import_batches", schema=S, type_="check")
    for col in ("detected_columns", "format_score", "encoding_confidence", "kind"):
        op.drop_column("import_batches", col, schema=S)
