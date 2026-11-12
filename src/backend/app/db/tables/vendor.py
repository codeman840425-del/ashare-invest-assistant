"""plan §4.6.5A：对账批次和公开规范化行，不存证书/行情值。"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Table,
    UniqueConstraint,
    text,
)

from app.db.base import (
    MARKET,
    boolean,
    integer,
    jsonb,
    metadata,
    one_of,
    pk_uuid,
    ts,
    txt,
    uuid_col,
)

DATASETS = ("hslt_list", "bj_list", "kc_list", "hsrl_real")
STATUSES = ("requested", "fetched", "failed", "skipped", "reconciled", "expired", "superseded")

master_vendor_batches = Table(
    "master_vendor_batches",
    metadata,
    pk_uuid(),
    Column("master_run_id", BigInteger, nullable=False),
    # Active revision 0020 requires a licence; the nullable 0021 experiment is paused.
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
