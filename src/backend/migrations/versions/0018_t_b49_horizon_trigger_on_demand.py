"""T-B49（T-T25 裁定 #7）：symbol_horizon_assessments.trigger 加 on_demand

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-02 20:30:00+08:00

迁移 0002 的 CHECK 漏了 ``on_demand``（契约 #31 ⑧：GET /horizon-assessments 同步计算落库时
``trigger='on_demand'``）。plan 3.3：库级 CHECK 必须与 trigger 列表完全一致。

downgrade：库中已有 ``on_demand`` 行时拒绝降级（报错并给出行数，不自动改数据）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "app"
T = "symbol_horizon_assessments"
OLD = "trigger IN ('import', 'watchlist_add', 'weekly', 'position_open_close')"
NEW = "trigger IN ('import', 'watchlist_add', 'weekly', 'position_open_close', 'on_demand')"
ON_DEMAND_ROWS = "SELECT count(*) FROM app.symbol_horizon_assessments WHERE trigger = 'on_demand'"


def _replace(expr: str) -> None:
    name = op.f("ck_symbol_horizon_assessments_trigger")
    op.drop_constraint(name, T, type_="check", schema=S)
    op.create_check_constraint(name, T, expr, schema=S)


def upgrade() -> None:
    _replace(NEW)


def downgrade() -> None:
    n = op.get_bind().execute(sa.text(ON_DEMAND_ROWS)).scalar_one()
    if n:
        raise RuntimeError(
            f"0018 降级拒绝：symbol_horizon_assessments 中有 {n} 行 trigger='on_demand'；"
            "请先人工处理（本迁移不自动修改数据）。"
        )
    _replace(OLD)
