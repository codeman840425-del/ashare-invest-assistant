"""评估 schema ``evaluation``（仅管理员，第三阶段启用；plan §3.3）。"""

from __future__ import annotations

from sqlalchemy import Table, text

from app.db.base import EVALUATION, integer, jsonb, metadata, one_of, pk_uuid, ts, txt, uuid_col

eval_runs = Table(
    "eval_runs",
    metadata,
    pk_uuid(),
    txt("kind", nullable=False),
    jsonb("target"),
    jsonb("params"),
    jsonb("data_range"),
    txt("status", nullable=False, server_default=text("'queued'")),
    integer("cost_calls"),
    ts("started_at"),
    ts("finished_at"),
    one_of("kind", ["factor_ic", "event_study", "param_robustness", "daily_revalidation"]),
    one_of("status", ["queued", "running", "done", "failed", "cancelled"]),
    schema=EVALUATION,
)

eval_results = Table(
    "eval_results",
    metadata,
    pk_uuid(),
    uuid_col("run_id", nullable=False, fk="evaluation.eval_runs.id"),
    jsonb("metrics", comment="全部附 n"),
    jsonb("folds"),
    jsonb("robustness"),
    schema=EVALUATION,
)
