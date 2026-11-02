"""观察、研究、证据、行动计划与提醒。

对应 plan §3.3「观察与研究」「证据」「行动计划」「提醒」。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, Table, UniqueConstraint, text

from app.db.base import (
    APP,
    boolean,
    created_at,
    day,
    integer,
    jsonb,
    metadata,
    money,
    num,
    one_of,
    pk_uuid,
    ts,
    txt,
    union,
    user_fk,
    uuid_array,
    uuid_col,
)
from app.schemas.enums import (
    Action,
    CandidateDecision,
    EpistemicType,
    PlanOrigin,
    ResearchCandidateOrigin,
    ResearchCandidateStatus,
    Severity,
    SourceKind,
)

watchlist_items = Table(
    "watchlist_items",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("security_code", nullable=False),
    txt("group_name"),
    txt("note"),
    ts("added_at", nullable=False, default_now=True),
    ts("removed_at"),
    schema=APP,
)

strategy_runs = Table(
    "strategy_runs",
    metadata,
    pk_uuid(),
    user_fk(nullable=True),
    uuid_col("strategy_version_id", fk="app.strategy_versions.id"),
    txt("kind", nullable=False),
    jsonb("params"),
    day("trade_date"),
    jsonb("universe"),
    txt("feature_set_version"),
    uuid_array("strategy_version_ids"),
    integer("duration_ms"),
    integer("result_count"),
    jsonb("results"),
    uuid_col("snapshot_id", fk="app.data_snapshots.id"),
    ts("triggered_at"),
    created_at(),
    one_of("kind", ["screen"]),
    schema=APP,
    comment="plan §3.3 两处定义合并：扫描批次（取代 screen_runs）；逐股结果写 candidate_signals",
)

research_candidates = Table(
    "research_candidates",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("security_code", nullable=False),
    txt("origin", nullable=False),
    uuid_col("strategy_run_id", fk="app.strategy_runs.id"),
    uuid_col("suggestion_id", fk="app.suggestions.id"),
    txt("status", nullable=False),
    uuid_col("current_version_id", fk="app.candidate_versions.id", use_alter=True),
    created_at(),
    one_of("origin", ResearchCandidateOrigin),  # 契约 §3 research_candidate_origin（同值同序）
    one_of("status", ResearchCandidateStatus),  # 契约 §3 research_candidate_status
    schema=APP,
)
# 契约 v0.2.9 §7.7A（T-A11 验收 4，plan 第 9 节问题 66）：本人同一证券至多一条进行中的候选；
# dropped / planned 不算。并发 POST 时由它保证只有一个成功（迁移 0016）。
Index(
    "uq_research_candidates_user_security_open",
    research_candidates.c.user_id,
    research_candidates.c.security_code,
    unique=True,
    postgresql_where=text("status IN ('researching', 'watching')"),
)

candidate_versions = Table(
    "candidate_versions",
    metadata,
    pk_uuid(),
    uuid_col("candidate_id", nullable=False, fk="app.research_candidates.id"),
    integer("version_no", nullable=False),
    txt("thesis"),
    jsonb("conditions_to_hold"),
    jsonb("counter_evidence"),
    jsonb("fit_assessment"),
    txt("decision"),
    txt("decision_reason"),
    uuid_col("snapshot_id", fk="app.data_snapshots.id"),
    created_at(),
    uuid_col("created_by", fk="app.users.id"),
    one_of("decision", CandidateDecision),  # 契约 §3 candidate_decision
    UniqueConstraint("candidate_id", "version_no"),
    schema=APP,
    comment="不可变（触发器）",
)

claims = Table(
    "claims",
    metadata,
    pk_uuid(),
    user_fk(nullable=True),
    txt("security_code"),
    txt("statement", nullable=False),
    txt("epistemic_type", nullable=False),
    txt("source_kind", nullable=False),
    jsonb("source_ref"),
    jsonb("value"),
    txt("method_note"),
    day("verify_by"),
    num("confidence"),
    uuid_col("supersedes_claim_id", fk="app.claims.id"),
    created_at(),
    one_of("epistemic_type", EpistemicType),
    one_of("source_kind", SourceKind),
    schema=APP,
    comment="不可变（更正 = 新 claim + supersedes_claim_id）",
)

claim_links = Table(
    "claim_links",
    metadata,
    pk_uuid(),
    uuid_col("claim_id", nullable=False, fk="app.claims.id"),
    txt("target_type", nullable=False),
    uuid_col("target_id", nullable=False),
    txt("role", nullable=False),
    one_of("target_type", ["candidate_version", "plan_version", "review_version", "alert"]),
    one_of("role", ["reason", "counter", "risk", "invalidation", "outcome"]),
    UniqueConstraint("claim_id", "target_type", "target_id", "role"),
    schema=APP,
)

#: plan 头表状态 + §3.3「对已有表的修改」的 pending_review
#: + 契约 /plans/{id}/close 的 done/cancelled
PLAN_STATUS = union(
    ["draft", "pending_review", "active", "triggered", "executed", "invalidated", "closed"],
    ["done", "cancelled"],
)

action_plans = Table(
    "action_plans",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("security_code", nullable=False),
    uuid_col("account_id", fk="app.accounts.id"),
    uuid_col("candidate_id", fk="app.research_candidates.id"),
    txt("status", nullable=False),
    uuid_col("current_version_id", fk="app.plan_versions.id", use_alter=True),
    txt("origin", nullable=False, server_default=text("'manual'")),
    uuid_col("plan_draft_id", fk="app.plan_drafts.id"),
    uuid_array("candidate_signal_ids"),
    created_at(),
    one_of("status", PLAN_STATUS),
    one_of("origin", PlanOrigin),
    # 契约 §7.7：只有确认草案能创建 origin=plan_draft 的计划；手工计划不能引用候选信号
    CheckConstraint(
        "(origin = 'plan_draft') = (plan_draft_id IS NOT NULL)"
        " AND (origin = 'plan_draft' OR candidate_signal_ids IS NULL"
        " OR cardinality(candidate_signal_ids) = 0)",
        name="origin_link",
    ),
    schema=APP,
)

plan_versions = Table(
    "plan_versions",
    metadata,
    pk_uuid(),
    uuid_col("plan_id", nullable=False, fk="app.action_plans.id"),
    integer("version_no", nullable=False),
    txt("action", nullable=False),
    txt("rationale"),
    money("size_amount"),
    num("size_pct_of_assets"),
    money("max_loss_amount"),
    txt("risks"),
    day("review_date"),
    txt("change_reason"),
    jsonb("completeness"),
    uuid_col("snapshot_id", fk="app.data_snapshots.id"),
    uuid_col("market_rule_version_id", fk="app.market_rule_versions.id"),
    created_at(),
    # plan 写 exit；契约 action 用 sell（契约为准）
    one_of("action", Action),
    UniqueConstraint("plan_id", "version_no"),
    schema=APP,
    comment="不可变（触发器）",
)

plan_conditions = Table(
    "plan_conditions",
    metadata,
    pk_uuid(),
    uuid_col("plan_version_id", nullable=False, fk="app.plan_versions.id"),
    txt("kind", nullable=False),
    txt("type", nullable=False),
    jsonb("params"),
    txt("description"),
    txt("epistemic_type", nullable=False, server_default=text("'hypothesis'")),
    one_of("kind", ["trigger", "invalidation"]),
    one_of(
        "type",
        ["price_above", "price_below", "pct_change", "indicator", "event", "date", "custom"],
    ),
    one_of("epistemic_type", EpistemicType),
    schema=APP,
    comment="随 plan_versions 不可变（触发器）",
)

alert_rules = Table(
    "alert_rules",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("origin", nullable=False),
    uuid_col("plan_condition_id", fk="app.plan_conditions.id"),
    txt("security_code"),
    txt("type", nullable=False),
    jsonb("params"),
    boolean("enabled", nullable=False, server_default=text("true")),
    integer("cooldown_minutes"),
    created_at(),
    one_of("origin", ["plan_condition", "holding_event", "user_custom"]),
    schema=APP,
)

alerts = Table(
    "alerts",
    metadata,
    pk_uuid(),
    user_fk(),
    uuid_col("rule_id", fk="app.alert_rules.id"),
    txt("security_code"),
    txt("severity", nullable=False),
    jsonb("what_happened"),
    jsonb("affected"),
    jsonb("checklist"),
    txt("status", nullable=False, server_default=text("'new'")),
    ts("triggered_at", nullable=False),
    ts("data_as_of"),
    uuid_col("snapshot_id", fk="app.data_snapshots.id"),
    txt("dedup_key"),
    one_of("severity", Severity),
    one_of("status", ["new", "read", "checked", "acted", "dismissed"]),
    UniqueConstraint("user_id", "dedup_key"),
    schema=APP,
)
