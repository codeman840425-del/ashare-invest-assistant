"""T-B49：data_snapshots 新增 purpose=horizon，用户级快照必须带 user_id

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-02 19:30:00+08:00

- ``ck_data_snapshots_purpose`` 加 ``horizon``（T-B46-47 裁定 R8：周期评估输入快照落库，
  ``symbol_horizon_assessments.snapshot_id`` 必须指向真实的快照行）。
- 新增 ``ck_data_snapshots_user_scoped``：``purpose IN ('candidate', 'plan', 'horizon')`` 时
  ``user_id IS NOT NULL``（这三类快照含本人画像 / 持仓 / 计划，删除用户数据按 user_id 物理删除）。

升级前先做预检查：库中已有违反新约束的行（上述三类且 user_id 为空）→ 迁移报错并给出行数，
**不自动修改或删除**；由运维按报告 T-B49.md 的预检查 SQL 查出、人工处理后再升级。

downgrade：先做预检查——库中有 ``purpose='horizon'`` 的快照行时直接报错（中文提示 + 行数），
不改任何约束、不自动删除数据（review-6670b10 m3）；
无此类行时删除新约束、purpose 检查恢复 0001 的取值。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_PURPOSES = ("candidate", "plan", "alert", "review", "screen", "suggestion", "signal", "report")
NEW_PURPOSES = (*OLD_PURPOSES, "horizon")
USER_SCOPED = ("candidate", "plan", "horizon")


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


#: 预检查（报告 T-B49.md 同一条 SQL，运维可在升级前单独执行）
PRECHECK_SQL = (
    "SELECT purpose, count(*) AS n FROM app.data_snapshots "
    "WHERE purpose IN ('candidate', 'plan', 'horizon') AND user_id IS NULL "
    "GROUP BY purpose ORDER BY purpose"
)


def upgrade() -> None:
    bad = op.get_bind().execute(sa.text(PRECHECK_SQL)).all()
    if bad:
        detail = ", ".join(f"{p}={n}" for p, n in bad)
        raise RuntimeError(
            "0017 预检查失败：app.data_snapshots 中有 user_id 为空的用户级快照（"
            + detail
            + "）。请按报告 T-B49.md 人工处理后再升级；本迁移不自动修改数据。"
        )
    op.drop_constraint(
        op.f("ck_data_snapshots_purpose"), "data_snapshots", schema="app", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_data_snapshots_purpose"),
        "data_snapshots",
        f"purpose IN ({_in(NEW_PURPOSES)})",
        schema="app",
    )
    op.create_check_constraint(
        op.f("ck_data_snapshots_user_scoped"),
        "data_snapshots",
        f"purpose NOT IN ({_in(USER_SCOPED)}) OR user_id IS NOT NULL",
        schema="app",
    )


#: 降级预检查：0016 及更早的 CHECK 不认识 horizon
HORIZON_ROWS = "SELECT count(*) FROM app.data_snapshots WHERE purpose = 'horizon'"


def downgrade() -> None:
    n = op.get_bind().execute(sa.text(HORIZON_ROWS)).scalar_one()
    if n:
        raise RuntimeError(
            f"0017 降级拒绝：app.data_snapshots 中有 {n} 行 purpose='horizon' 的快照；"
            "旧版本不认识该取值。请先按报告 T-B49.md 人工处理（例如对相关用户执行"
            "删除用户数据 CLI，或在确认无用后删除这些快照及引用它们的周期评估行），"
            "再降级；本迁移不自动修改数据。"
        )
    op.drop_constraint(
        op.f("ck_data_snapshots_user_scoped"), "data_snapshots", schema="app", type_="check"
    )
    op.drop_constraint(
        op.f("ck_data_snapshots_purpose"), "data_snapshots", schema="app", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_data_snapshots_purpose"),
        "data_snapshots",
        f"purpose IN ({_in(OLD_PURPOSES)})",
        schema="app",
    )
