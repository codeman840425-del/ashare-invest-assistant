"""C2 durable daily-bar outbox, single successor of 0034."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_bars_outbox",
        sa.Column(
            "id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("pipeline_run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("window_trading_days", sa.Integer()),
        sa.Column("batch_kind", sa.Text(), nullable=False),
        sa.Column("batch_seq", sa.Integer(), nullable=False),
        sa.Column("source_licence_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_digest", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["app.pipeline_runs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["app.users.id"]),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("pipeline_run_id"),
        sa.CheckConstraint("kind IN ('mairui_daily_bars')", name="kind"),
        sa.CheckConstraint("batch_kind IN ('daily', 'backfill')", name="batch_kind"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed', 'halted')", name="status"
        ),
        sa.CheckConstraint(
            "window_trading_days IS NULL OR window_trading_days > 0", name="window_positive"
        ),
        sa.CheckConstraint("batch_seq >= 0", name="batch_seq_nonnegative"),
        schema="app",
    )


def downgrade() -> None:
    # Never drop pending work or its audit trail on an accidental downgrade.
    count = (
        op.get_bind().execute(sa.text("SELECT count(*) FROM app.daily_bars_outbox")).scalar_one()
    )
    if count:
        raise RuntimeError("refusing downgrade 0035: daily_bars_outbox is not empty")
    op.drop_table("daily_bars_outbox", schema="app")
