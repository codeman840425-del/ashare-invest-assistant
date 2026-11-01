"""契约 v0.2.2 / T-A02：user_profiles 对齐 /me/profile；周期评估加 position_open_close 与 inputs_missing

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-01 21:00:00+00:00

- ``app.user_profiles``：``horizon(short/medium/long)`` → ``horizon_pref text[]``（取值为 ``horizon`` 枚举），
  ``weekly_hours`` → ``effort(low/medium/high)``；新增 ``experience``、``max_single_position_pct``
  （plan §3、契约 §7.1 ``/me/profile``）。旧列不做数据换算：两者语义不同（plan 明写“由 effort 取代”），
  且基线之后尚无生产数据；表为只追加，旧行如存在则新列为 NULL。
- ``app.symbol_horizon_assessments``：``trigger`` 增加 ``position_open_close``；新增
  ``inputs_missing text[] NOT NULL DEFAULT '{}'``（契约 v0.2.2 ``/horizon-assessments``）。
- 基线 0001 不改。downgrade 恢复 0001 的结构（若已有 ``trigger = 'position_open_close'`` 的行，
  恢复旧 CHECK 会失败，需人工处理；只追加表不允许脚本删改历史行）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "app"


def upgrade() -> None:
    # --- user_profiles ---
    op.drop_constraint(op.f("ck_user_profiles_horizon"), "user_profiles", type_="check", schema=S)
    op.drop_column("user_profiles", "horizon", schema=S)
    op.drop_column("user_profiles", "weekly_hours", schema=S)
    op.add_column(
        "user_profiles", sa.Column("horizon_pref", sa.ARRAY(sa.Text()), nullable=True), schema=S
    )
    op.add_column("user_profiles", sa.Column("effort", sa.Text(), nullable=True), schema=S)
    op.add_column("user_profiles", sa.Column("experience", sa.Text(), nullable=True), schema=S)
    op.add_column(
        "user_profiles", sa.Column("max_single_position_pct", sa.Numeric(), nullable=True), schema=S
    )
    op.create_check_constraint(
        op.f("ck_user_profiles_horizon_pref"),
        "user_profiles",
        "horizon_pref <@ ARRAY['intraday_t', 'short', 'swing', 'long']::text[]",
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_user_profiles_effort"),
        "user_profiles",
        "effort IN ('low', 'medium', 'high')",
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_user_profiles_experience"),
        "user_profiles",
        "experience IN ('novice', 'intermediate', 'advanced')",
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_user_profiles_max_single_position_pct_range"),
        "user_profiles",
        "max_single_position_pct > 0 AND max_single_position_pct <= 100",
        schema=S,
    )

    # --- symbol_horizon_assessments ---
    op.drop_constraint(
        op.f("ck_symbol_horizon_assessments_trigger"),
        "symbol_horizon_assessments",
        type_="check",
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_symbol_horizon_assessments_trigger"),
        "symbol_horizon_assessments",
        "trigger IN ('import', 'watchlist_add', 'weekly', 'position_open_close')",
        schema=S,
    )
    op.add_column(
        "symbol_horizon_assessments",
        sa.Column(
            "inputs_missing",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        schema=S,
    )


def downgrade() -> None:
    op.drop_column("symbol_horizon_assessments", "inputs_missing", schema=S)
    op.drop_constraint(
        op.f("ck_symbol_horizon_assessments_trigger"),
        "symbol_horizon_assessments",
        type_="check",
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_symbol_horizon_assessments_trigger"),
        "symbol_horizon_assessments",
        "trigger IN ('import', 'watchlist_add', 'weekly')",
        schema=S,
    )

    for name in (
        "ck_user_profiles_max_single_position_pct_range",
        "ck_user_profiles_experience",
        "ck_user_profiles_effort",
        "ck_user_profiles_horizon_pref",
    ):
        op.drop_constraint(op.f(name), "user_profiles", type_="check", schema=S)
    for col in ("max_single_position_pct", "experience", "effort", "horizon_pref"):
        op.drop_column("user_profiles", col, schema=S)
    op.add_column("user_profiles", sa.Column("horizon", sa.Text(), nullable=True), schema=S)
    op.add_column("user_profiles", sa.Column("weekly_hours", sa.Numeric(), nullable=True), schema=S)
    op.create_check_constraint(
        op.f("ck_user_profiles_horizon"),
        "user_profiles",
        "horizon IN ('short', 'medium', 'long')",
        schema=S,
    )
