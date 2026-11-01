"""用户与画像（plan §3.3「用户与画像」、§3.6）。"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, PrimaryKeyConstraint, Table, UniqueConstraint, text

from app.db.base import (
    APP,
    array_subset,
    boolean,
    created_at,
    integer,
    jsonb,
    metadata,
    num,
    one_of,
    pk_uuid,
    text_array,
    ts,
    txt,
    user_fk,
    uuid_col,
)
from app.schemas.enums import AccountStatus, Horizon, ProfileEffort, ProfileExperience, Role

users = Table(
    "users",
    metadata,
    pk_uuid(),
    txt("username", nullable=False),
    txt("password_hash", nullable=False),
    txt("display_name"),
    txt("role", nullable=False),
    txt("status", nullable=False),
    txt("apply_note"),
    txt("email"),
    integer("failed_login_count", nullable=False, server_default=text("0")),
    ts("locked_until"),
    ts("password_changed_at"),
    created_at(),
    ts("reviewed_at"),
    uuid_col("reviewed_by", fk="app.users.id"),
    ts("deleted_at"),
    UniqueConstraint("username"),
    # 小写归一后 4–32 位 [a-z0-9_]；保留词（admin/root/system）由应用层拒绝
    CheckConstraint("username ~ '^[a-z0-9_]{4,32}$'", name="username_format"),
    one_of("role", Role),
    # 契约 account_status 无 deleted（plan §3.3 有）→ 以契约为准；注销用 deleted_at 表示（见报告）
    one_of("status", AccountStatus),
    CheckConstraint("failed_login_count >= 0", name="failed_login_count_nonneg"),
    schema=APP,
)

account_reviews = Table(
    "account_reviews",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("action", nullable=False),
    txt("reason"),
    uuid_col("admin_id", nullable=False, fk="app.users.id"),
    created_at(),
    one_of("action", ["approve", "reject", "disable", "enable", "reset_password"]),
    schema=APP,
    comment="只追加：管理员审核历史（触发器禁止 UPDATE/DELETE）",
)

login_attempts = Table(
    "login_attempts",
    metadata,
    pk_uuid(),
    txt("username_tried"),
    user_fk(nullable=True),
    txt("ip_hash"),
    boolean("success", nullable=False),
    txt("failure_reason"),
    created_at("at"),
    schema=APP,
    comment="限速、锁定与审计；保留 180 天（由定时任务删除，故不加不可变触发器）",
)

# 邀请码（plan §3.3 / §6.1 invite.*，契约 §7.9，T-B03c）：只存 HMAC 摘要；状态由字段推导，不物理删除
invite_codes = Table(
    "invite_codes",
    metadata,
    pk_uuid(),
    txt("code_hash", nullable=False),
    uuid_col("created_by", nullable=False, fk="app.users.id"),
    created_at(),
    ts("expires_at", nullable=False),
    integer("max_uses", nullable=False, server_default=text("1")),
    integer("used_count", nullable=False, server_default=text("0")),
    uuid_col("used_by", fk="app.users.id"),
    ts("used_at"),
    ts("revoked_at"),
    uuid_col("revoked_by", fk="app.users.id"),
    txt("bound_username"),
    txt("note"),
    UniqueConstraint("code_hash"),
    CheckConstraint("max_uses = 1", name="max_uses_v1"),
    CheckConstraint("used_count >= 0 AND used_count <= max_uses", name="used_count_range"),
    CheckConstraint("expires_at > created_at", name="expires_after_created"),
    CheckConstraint("(revoked_at IS NULL) = (revoked_by IS NULL)", name="revoked_pair"),
    CheckConstraint("note IS NULL OR char_length(note) <= 200", name="note_len"),
    schema=APP,
    comment=(
        "邀请码：HMAC-SHA256(APP_MASTER_KEY, 归一化码)，明文不入库；"
        "状态 active/used/expired/revoked 由字段推导"
    ),
)

# 按月声明式分区（plan §3A.6）：分区键 at 必须在主键里
audit_logs = Table(
    "audit_logs",
    metadata,
    uuid_col("id", nullable=False, server_default=text("gen_random_uuid()")),
    uuid_col("actor_id"),
    txt("actor_role"),
    txt("action", nullable=False),
    txt("target_type"),
    txt("target_id"),
    jsonb("detail"),
    txt("ip_hash"),
    created_at("at"),
    PrimaryKeyConstraint("id", "at"),
    schema=APP,
    postgresql_partition_by="RANGE (at)",
    comment="全站审计；按月分区；行不可改删（保留期通过 DROP 分区实现）",
)

# consents：契约 v0.2.5（T-A06）作废，迁移 0005 删除。

user_profiles = Table(
    "user_profiles",
    metadata,
    pk_uuid(),
    user_fk(),
    integer("version_no", nullable=False),
    # 前五个字段与契约 /me/profile 一一对应（v0.2.2 / T-A02；迁移 0002）。只追加表、历史行可能
    # 不含这些字段，故列可空，非空由 PUT /me/profile 的请求模型保证。
    text_array("horizon_pref"),
    txt("effort"),
    integer("risk_tolerance"),
    txt("experience"),
    num("max_single_position_pct", comment="范围由 API 校验，以 risk_controls 为准"),
    # 选填（契约暂未暴露，仅内部使用）。capital_range 的存储编码未定 → TODO(架构师)，暂不加 CHECK
    txt("capital_range"),
    num("max_drawdown_pct"),
    text_array("focus_areas"),
    ts("confirmed_at"),
    created_at(),
    UniqueConstraint("user_id", "version_no"),
    array_subset("horizon_pref", Horizon),
    one_of("effort", ProfileEffort),
    one_of("experience", ProfileExperience),
    CheckConstraint("risk_tolerance BETWEEN 1 AND 5", name="risk_tolerance_range"),
    CheckConstraint(
        "max_single_position_pct > 0 AND max_single_position_pct <= 100",
        name="max_single_position_pct_range",
    ),
    schema=APP,
    comment="只追加：最新版本为当前画像（触发器禁止 UPDATE/DELETE）",
)
