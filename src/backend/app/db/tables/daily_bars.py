"""Durable daily-bar intents; entirely separate from the daily-name delivery tables."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Table, UniqueConstraint

from app.db.base import APP, day, integer, metadata, one_of, pk_uuid, ts, txt, user_fk, uuid_col

outbox = Table(
    "daily_bars_outbox",
    metadata,
    pk_uuid(),
    uuid_col("pipeline_run_id", nullable=False, fk="app.pipeline_runs.id"),
    txt("idempotency_key", nullable=False),
    txt("kind", nullable=False),
    day("trade_date", nullable=False),
    user_fk(),
    integer("window_trading_days"),
    txt("batch_kind", nullable=False),
    integer("batch_seq", nullable=False),
    uuid_col("source_licence_id", nullable=False),
    uuid_col("receipt_id", nullable=False),
    txt("receipt_digest", nullable=False),
    txt("status", nullable=False),
    ts("attempted_at"),
    ts("created_at", nullable=False, default_now=True),
    ts("finished_at"),
    txt("error_code"),
    UniqueConstraint("idempotency_key"),
    UniqueConstraint("pipeline_run_id"),
    one_of("kind", ["mairui_daily_bars"]),
    one_of("batch_kind", ["daily", "backfill"]),
    one_of("status", ["pending", "running", "done", "failed", "halted"]),
    CheckConstraint(
        "window_trading_days IS NULL OR window_trading_days > 0", name="window_positive"
    ),
    CheckConstraint("batch_seq >= 0", name="batch_seq_nonnegative"),
    schema=APP,
)
