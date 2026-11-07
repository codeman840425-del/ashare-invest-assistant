"""T-B61 原始0020定义快照；后续NULL作用域由0021升级，不引用活动模型。"""

from alembic import op
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    MetaData,
    Table,
    UniqueConstraint,
    select,
    text,
)

from app.db.base import (
    MARKET,
    NAMING_CONVENTION,
    boolean,
    integer,
    jsonb,
    one_of,
    pk_uuid,
    ts,
    txt,
    uuid_col,
)

metadata = MetaData(naming_convention=NAMING_CONVENTION)
Table("master_runs", metadata, Column("id", BigInteger, primary_key=True), schema=MARKET)

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

DATASETS = ("hslt_list", "bj_list", "kc_list", "hsrl_real")
STATUSES = ("requested", "fetched", "failed", "skipped", "reconciled", "expired", "superseded")

master_vendor_batches = Table(
    "master_vendor_batches",
    metadata,
    pk_uuid(),
    Column("master_run_id", BigInteger, nullable=False),
    uuid_col("source_licence_id", nullable=False),
    txt("status", nullable=False),
    integer("attempt", nullable=False),
    ts("requested_at", nullable=False),
    ts("deadline_at", nullable=False),
    ts("fetched_at"),
    ts("reconciled_at"),
    jsonb("datasets", nullable=False, server_default=text("'[]'::jsonb")),
    txt("error_code"),
    ForeignKeyConstraint(["master_run_id"], ["market.master_runs.id"]),
    UniqueConstraint("master_run_id", "source_licence_id", "attempt"),
    one_of("status", STATUSES),
    CheckConstraint("attempt BETWEEN 1 AND 3", name="attempt"),
    CheckConstraint("jsonb_typeof(datasets) = 'array'", name="datasets_array"),
    schema=MARKET,
)
master_vendor_list_rows = Table(
    "master_vendor_list_rows",
    metadata,
    uuid_col("batch_id", nullable=False, primary_key=True),
    txt("dataset", nullable=False, primary_key=True),
    txt("security_code", nullable=False, primary_key=True),
    txt("vendor_name"),
    boolean("dup_conflict", nullable=False, server_default=text("false")),
    ForeignKeyConstraint(["batch_id"], ["market.master_vendor_batches.id"], ondelete="CASCADE"),
    one_of("dataset", DATASETS),
    CheckConstraint("security_code ~ '^[0-9]{6}[.](SH|SZ|BJ)$'", name="code"),
    CheckConstraint("NOT dup_conflict OR dataset = 'hsrl_real'", name="conflict_only_real"),
    schema=MARKET,
)


def upgrade() -> None:
    master_vendor_batches.create(op.get_bind())
    master_vendor_list_rows.create(op.get_bind())


def downgrade() -> None:
    conn = op.get_bind()
    for table in (master_vendor_list_rows, master_vendor_batches):
        if conn.execute(select(table).limit(1)).first() is not None:
            raise RuntimeError("对账批次表仍有数据，拒绝降级，不自动删除")
    master_vendor_list_rows.drop(conn)
    master_vendor_batches.drop(conn)
