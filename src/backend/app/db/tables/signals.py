"""候选信号、不可执行原因、计划草案与用户限制。

对应 plan §3.3「策略三层…」、§2.5.7–2.5.13；契约 §6、§7.6–7.7。

``candidate_signals`` 按 ``created_at`` 按月声明式分区（plan §3A.6），主键为 ``(id, created_at)``；
PostgreSQL 不允许外键只引用分区表主键的一部分，因此 ``signal_id`` / ``signal_ids`` 不建外键，
由应用层与契约测试保证引用存在。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, PrimaryKeyConstraint, Table, text

from app.db.base import (
    APP,
    array_subset,
    boolean,
    created_at,
    integer,
    jsonb,
    jsonb_array_items,
    jsonpath_one_of,
    metadata,
    money,
    num,
    one_of,
    pk_uuid,
    text_array,
    ts,
    txt,
    user_fk,
    uuid_array,
    uuid_col,
)
from app.schemas.enums import (
    Action,
    CandidateSignalState,
    CheckOn,
    ConfidenceLevel,
    DataProvider,
    Dimension,
    EpistemicType,
    Horizon,
    PlanDraftStatus,
    ReasonCode,
    ReasonStatus,
    RestrictionKind,
    RuleRole,
    TLeg,
)

# 下面三个是 SQL/JSON path 过滤谓词（``@`` 为数组元素），命中即为坏元素。先判类型再比值：
# lax 模式下类型不符的比较得 unknown，``!unknown`` 仍是 unknown，单靠取值比较会漏判。
#: RuleRef（契约 §5.1 / v0.2.3 #15）：对象；rule_id 非空字符串；role ∈ rule_role；
#: dimension ∈ dimension（所有 role 必填）；passed 键必须存在且为布尔或 null
RULE_REF_BAD_ITEM = (
    '@.type() != "object"'
    ' || !(@.rule_id.type() == "string") || @.rule_id == ""'
    ' || !(@.role.type() == "string")'
    f" || !{jsonpath_one_of('@.role', RuleRole)}"
    ' || !(@.dimension.type() == "string")'
    f" || !{jsonpath_one_of('@.dimension', Dimension)}"
    ' || !(@.passed.type() == "boolean" || @.passed.type() == "null")'
)
#: Evidence（契约 §5.1 / v0.2.3 #1）：对象；id 非空字符串；provider ∈ data_provider（没有 local）
EVIDENCE_BAD_ITEM = (
    '@.type() != "object"'
    ' || !(@.id.type() == "string") || @.id == ""'
    ' || !(@.provider.type() == "string")'
    f" || !{jsonpath_one_of('@.provider', DataProvider)}"
)
#: TextWithEvidence（契约 §5.1）：对象；text 非空字符串
TEXT_WITH_EVIDENCE_BAD_ITEM = '@.type() != "object" || !(@.text.type() == "string") || @.text == ""'

candidate_signals = Table(
    "candidate_signals",
    metadata,
    uuid_col("id", nullable=False, server_default=text("gen_random_uuid()")),
    user_fk(),
    uuid_col("instance_id", fk="app.strategy_instances.id"),
    uuid_col("strategy_version_id", nullable=False, fk="app.strategy_versions.id"),
    txt("security_code", nullable=False, comment="plan 写 security_id；按契约用文本代码"),
    txt("horizon", nullable=False),
    txt("proposed_action", nullable=False),
    txt("t_leg"),
    integer("score"),
    txt("confidence_level"),
    num("confidence"),
    jsonb("stops"),
    jsonb("rule_refs", nullable=False),
    jsonb("evidence", nullable=False),
    jsonb("counter_evidence", nullable=False),
    jsonb("invalidation", nullable=False),
    jsonb("model_refs", nullable=False),
    jsonb("gate_results"),
    jsonb("risk_flags"),
    boolean("crowding_flag", nullable=False, server_default=text("false")),
    txt("feature_set_version"),
    uuid_col("snapshot_id", fk="app.data_snapshots.id"),
    ts("valid_until"),
    txt("cooldown_key"),
    created_at(),
    txt("state", nullable=False, server_default=text("'open'")),
    ts("state_changed_at", nullable=False, default_now=True),
    PrimaryKeyConstraint("id", "created_at"),
    one_of("horizon", Horizon),
    one_of("proposed_action", Action),
    one_of("t_leg", TLeg),
    one_of("confidence_level", ConfidenceLevel),
    one_of("state", CandidateSignalState),
    CheckConstraint("score BETWEEN 0 AND 100", name="score"),
    # 契约 §5.1 P1：四个数组非空；model_refs 只能是 auxiliary
    CheckConstraint(
        "jsonb_typeof(rule_refs) = 'array' AND jsonb_array_length(rule_refs) > 0"
        " AND jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) > 0"
        " AND jsonb_typeof(counter_evidence) = 'array'"
        " AND jsonb_array_length(counter_evidence) > 0"
        " AND jsonb_typeof(invalidation) = 'array' AND jsonb_array_length(invalidation) > 0",
        name="explainable",
    ),
    CheckConstraint(
        "jsonb_typeof(model_refs) = 'array' AND NOT jsonb_path_exists("
        "model_refs, '$[*] ? (@.role != \"auxiliary\")')",
        name="model_refs_auxiliary",
    ),
    # 契约 v0.2.3 §7.6 CandidateSignal 正式结构（迁移 0003）
    CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    CheckConstraint(jsonb_array_items("rule_refs", RULE_REF_BAD_ITEM), name="rule_refs_shape"),
    CheckConstraint(jsonb_array_items("evidence", EVIDENCE_BAD_ITEM), name="evidence_shape"),
    CheckConstraint(
        jsonb_array_items("counter_evidence", TEXT_WITH_EVIDENCE_BAD_ITEM),
        name="counter_evidence_shape",
    ),
    CheckConstraint(
        jsonb_array_items("invalidation", TEXT_WITH_EVIDENCE_BAD_ITEM),
        name="invalidation_shape",
    ),
    schema=APP,
    postgresql_partition_by="RANGE (created_at)",
    comment="正文不可变，只允许 state / state_changed_at 变化（触发器）；按月分区",
)
Index(
    "ix_candidate_signals_user_created",
    candidate_signals.c.user_id,
    candidate_signals.c.created_at.desc(),
    candidate_signals.c.id,
)
Index(
    "ix_candidate_signals_instance_created",
    candidate_signals.c.instance_id,
    candidate_signals.c.created_at.desc(),
)
Index(
    "ix_candidate_signals_security_created",
    candidate_signals.c.security_code,
    candidate_signals.c.created_at.desc(),
)

candidate_signal_events = Table(
    "candidate_signal_events",
    metadata,
    pk_uuid(),
    uuid_col("signal_id", nullable=False, comment="→ candidate_signals.id（分区表，无外键）"),
    txt("from_state"),
    txt("to_state", nullable=False),
    txt("cause", nullable=False),
    jsonb("detail"),
    ts("at", nullable=False, default_now=True),
    one_of("from_state", CandidateSignalState),
    one_of("to_state", CandidateSignalState),
    one_of(
        "cause",
        ["executability_check", "reason_released", "user", "expiry", "invalidation", "supersede"],
    ),
    schema=APP,
    comment="只追加（触发器）",
)

non_executable_reasons = Table(
    "non_executable_reasons",
    metadata,
    pk_uuid(),
    uuid_col("signal_id", nullable=False, comment="→ candidate_signals.id（分区表，无外键）"),
    user_fk(),
    txt("code", nullable=False),
    txt("description"),
    jsonb("evidence"),
    txt("epistemic_type", nullable=False, server_default=text("'fact'")),
    ts("detected_at", nullable=False, default_now=True),
    uuid_col("snapshot_id", fk="app.data_snapshots.id"),
    jsonb("release_condition"),
    text_array("check_on"),
    boolean("machine_checkable", nullable=False, server_default=text("true")),
    ts("next_check_at"),
    txt("status", nullable=False, server_default=text("'active'")),
    ts("released_at"),
    jsonb("release_evidence"),
    txt("released_by", comment="'system' 或 user_id"),
    one_of("code", ReasonCode),
    one_of("epistemic_type", EpistemicType),
    one_of("status", ReasonStatus),
    array_subset("check_on", CheckOn),
    schema=APP,
)
Index(
    "ix_non_executable_reasons_active_check",
    non_executable_reasons.c.check_on,
    non_executable_reasons.c.next_check_at,
    postgresql_where=text("status = 'active'"),
)

reason_status_events = Table(
    "reason_status_events",
    metadata,
    pk_uuid(),
    uuid_col("reason_id", nullable=False, fk="app.non_executable_reasons.id"),
    txt("from_status"),
    txt("to_status", nullable=False),
    jsonb("evaluated_value"),
    ts("at", nullable=False, default_now=True),
    one_of("from_status", ReasonStatus),
    one_of("to_status", ReasonStatus),
    schema=APP,
    comment="只追加（触发器）",
)

plan_drafts = Table(
    "plan_drafts",
    metadata,
    pk_uuid(),
    user_fk(),
    uuid_array("signal_ids", nullable=False),
    uuid_col("instance_id", fk="app.strategy_instances.id"),
    txt("security_code", nullable=False),
    txt("action", nullable=False),
    jsonb("qty_range"),
    jsonb("price_range"),
    jsonb("stops"),
    money("max_loss_amount"),
    num("max_loss_pct"),
    jsonb("fee_estimate"),
    jsonb("user_context_snapshot"),
    jsonb("risk_flags"),
    jsonb("judgment_checklist"),
    uuid_col("market_rule_version_id", fk="app.market_rule_versions.id"),
    uuid_col("snapshot_id", fk="app.data_snapshots.id"),
    ts("expires_at", nullable=False),
    created_at(),
    txt("status", nullable=False, server_default=text("'pending'")),
    ts("status_changed_at", nullable=False, default_now=True),
    one_of("action", Action),
    one_of("status", PlanDraftStatus),
    CheckConstraint("cardinality(signal_ids) >= 1", name="signal_ids_nonempty"),
    schema=APP,
    comment="正文不可变，只允许 status / status_changed_at 变化（触发器）",
)
Index(
    "ix_plan_drafts_user_status_expires",
    plan_drafts.c.user_id,
    plan_drafts.c.status,
    plan_drafts.c.expires_at,
)

plan_draft_confirmations = Table(
    "plan_draft_confirmations",
    metadata,
    pk_uuid(),
    uuid_col("draft_id", nullable=False, fk="app.plan_drafts.id", unique=True),
    user_fk(),
    jsonb("checklist_answers"),
    boolean("risk_ack", nullable=False),
    money("chosen_qty"),
    money("chosen_price"),
    jsonb("deviation"),
    uuid_col("plan_id", fk="app.action_plans.id"),
    created_at(),
    CheckConstraint("risk_ack", name="risk_ack_true"),
    schema=APP,
    comment="只追加（触发器）",
)

user_restrictions = Table(
    "user_restrictions",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("kind", nullable=False),
    txt("target_type", nullable=False),
    txt("target_id", nullable=False, comment="security_code 或实体 uuid（文本）"),
    ts("until"),
    txt("reason"),
    created_at(),
    ts("removed_at"),
    one_of("kind", RestrictionKind),
    one_of("target_type", ["security", "strategy", "instance"]),
    schema=APP,
)
