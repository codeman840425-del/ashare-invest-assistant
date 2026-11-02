"""复盘与数据快照（plan §3.3「复盘」「快照与共享行情」）。"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, Table, UniqueConstraint, text

from app.db.base import (
    APP,
    created_at,
    day,
    integer,
    jsonb,
    metadata,
    one_of,
    pk_uuid,
    text_array,
    txt,
    user_fk,
    uuid_array,
    uuid_col,
)

data_snapshots = Table(
    "data_snapshots",
    metadata,
    pk_uuid(),
    created_at(),
    txt("purpose", nullable=False),
    jsonb("items", nullable=False),
    jsonb("known_events"),
    txt("hash", nullable=False),
    # T-B16-core-r2（迁移 0013，plan §3.3/§7.3）：含持仓/成交/账户派生内容的快照必须填 user_id
    # （相关时填 licence_id）；删除用户数据时按它们物理删除。user_id 为空 → 只能存市场级内容。
    user_fk(nullable=True),
    uuid_col("licence_id", fk="app.user_data_licences.id"),
    one_of(
        "purpose",
        [
            "candidate",
            "plan",
            "alert",
            "review",
            "screen",
            "suggestion",
            "signal",
            "report",
            "horizon",  # 0017（T-B49，R8）：周期评估输入快照
        ],
    ),
    # 0017（T-B49）：本人画像 / 持仓 / 计划派生的快照必须带 user_id
    CheckConstraint(
        "purpose NOT IN ('candidate', 'plan', 'horizon') OR user_id IS NOT NULL",
        name="user_scoped",
    ),
    schema=APP,
    comment="不可变（触发器）",
)
Index(
    "ix_data_snapshots_user_id",
    data_snapshots.c.user_id,
    postgresql_where=text("user_id IS NOT NULL"),
)
Index(
    "ix_data_snapshots_licence_id",
    data_snapshots.c.licence_id,
    postgresql_where=text("licence_id IS NOT NULL"),
)

reviews = Table(
    "reviews",
    metadata,
    pk_uuid(),
    user_fk(),
    uuid_col("plan_id", fk="app.action_plans.id"),
    txt("security_code"),
    day("period_start"),
    day("period_end"),
    uuid_col("current_version_id", fk="app.review_versions.id", use_alter=True),
    created_at(),
    schema=APP,
)

review_versions = Table(
    "review_versions",
    metadata,
    pk_uuid(),
    uuid_col("review_id", nullable=False, fk="app.reviews.id"),
    integer("version_no", nullable=False),
    uuid_array("plan_version_ids"),
    uuid_array("trade_ids"),
    jsonb("outcome_metrics"),
    jsonb("attribution"),
    txt("lessons"),
    text_array("tags"),
    uuid_col("snapshot_id", fk="app.data_snapshots.id"),
    created_at(),
    UniqueConstraint("review_id", "version_no"),
    schema=APP,
    comment="不可变（触发器）",
)
