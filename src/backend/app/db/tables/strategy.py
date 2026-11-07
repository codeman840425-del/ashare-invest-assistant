"""策略库、策略三层（L1 卡片 / L2 模板 / L3 实例）、风控与生命周期（plan §3.3、§2.5）。

不可变约定（plan §3.3）：头表可变，版本正文不可变（触发器见迁移），状态变化写只追加事件表。
字段名：plan §3.3 部分写 ``security_id``；契约 v0.2 只有 ``security_code``（文本代码），
``market.securities`` 主键也是文本代码，故 app 表统一用 ``security_code``
（见报告「T-O08 §13 对接」）。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, PrimaryKeyConstraint, Table, UniqueConstraint, text

from app.config_files import SEMVER_PATTERN
from app.db.base import (
    APP,
    array_subset,
    boolean,
    created_at,
    day,
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
from app.db.tables.signals import EVIDENCE_BAD_ITEM
from app.schemas.enums import (
    BarAdjust,
    CardCompleteness,
    Dimension,
    FeatureStatus,
    Horizon,
    HorizonAssessmentTrigger,
    InstanceOrigin,
    InstancePausedBy,
    InstanceStatus,
    Lifecycle,
    ReasonCode,
    RiskControl,
    RiskLevel,
    RuleRole,
)

dimension_definitions = Table(
    "dimension_definitions",
    metadata,
    txt("key", nullable=False, primary_key=True),
    txt("name", nullable=False),
    txt("description"),
    jsonb("sources"),
    jsonb("coverage_gaps"),
    ts("updated_at", nullable=False, default_now=True),
    one_of("key", Dimension),
    schema=APP,
)

strategies = Table(
    "strategies",
    metadata,
    pk_uuid(),
    txt("key", nullable=False, unique=True),
    uuid_col("owner_user_id", fk="app.users.id"),
    txt("name", nullable=False),
    text_array("horizons"),
    uuid_col("copied_from_version_id", fk="app.strategy_versions.id", use_alter=True),
    uuid_col("current_version_id", fk="app.strategy_versions.id", use_alter=True),
    txt("status", nullable=False, server_default=text("'active'")),
    created_at(),
    one_of("status", ["active", "archived"]),
    array_subset("horizons", Horizon),
    schema=APP,
    comment="L2 模板头表（即 strategy_templates）",
)

strategy_versions = Table(
    "strategy_versions",
    metadata,
    pk_uuid(),
    uuid_col("strategy_id", nullable=False, fk="app.strategies.id"),
    integer("version_no", nullable=False),
    jsonb("config", nullable=False),
    txt("config_hash", nullable=False),
    txt("changelog"),
    uuid_col("published_by", fk="app.users.id"),
    ts("published_at"),
    uuid_col("card_version_id", fk="app.strategy_card_versions.id"),
    txt("kind", nullable=False, server_default=text("'rule_template'")),
    txt("code_entry"),
    uuid_col("parent_version_id", fk="app.strategy_versions.id"),
    txt("param_hash"),
    jsonb("params_schema"),
    jsonb("rule_snippet_refs"),
    txt("feature_set_version"),
    txt("lifecycle", nullable=False, server_default=text("'draft'")),
    uuid_col("lifecycle_changed_by", fk="app.users.id"),
    ts("lifecycle_changed_at"),
    created_at(),
    one_of("kind", ["rule_template", "code"]),
    one_of("lifecycle", Lifecycle),
    UniqueConstraint("strategy_id", "version_no"),
    schema=APP,
    comment="L2 版本：published_at 非空后正文不可变，只允许生命周期列变化（触发器）",
)

engine_policies = Table(
    "engine_policies",
    metadata,
    pk_uuid(),
    integer("version_no", nullable=False, unique=True),
    jsonb("config", nullable=False),
    ts("published_at"),
    created_at(),
    schema=APP,
    comment="不可变（触发器）",
)

#: HorizonCap.kind（契约 v0.2.3；enums 未单列，只用于 CHECK）。
#: v0.2.6（T-A07 / T006e 裁定 2，迁移 0006）：删 ``requires``、加 ``gate``——HG1–HG6 命中为
#: ``gate``（rule_id 为 HGn，inputs_missing 为 []）；LG0/LG0B 的 else_cap 为 ``data_missing``；
#: IT0 的 else_score: 0 是分数，不进 caps
HORIZON_CAP_KINDS = ("gate", "data_missing")

horizon_classifier_versions = Table(
    "horizon_classifier_versions",
    metadata,
    pk_uuid(),
    integer("version_no", nullable=False, unique=True),
    #: 契约 classifier_version（plan §3.3 T-A03；迁移 0003）
    txt("semver", nullable=False, unique=True),
    jsonb("config", nullable=False),
    ts("published_at"),
    created_at(),
    CheckConstraint(f"semver ~ '{SEMVER_PATTERN}'", name="semver_format"),
    schema=APP,
    comment="不可变（触发器）",
)

#: HorizonCap（契约 v0.2.3 §5.1）：{horizon, cap 0–100 整数, kind, rule_id 字符串或 null,
#: inputs_missing 字符串数组}；SQL/JSON path 过滤谓词，命中即为坏元素（先判类型再比值）
HORIZON_CAP_BAD_ITEM = (
    '@.type() != "object"'
    ' || !(@.horizon.type() == "string")'
    f" || !{jsonpath_one_of('@.horizon', Horizon)}"
    ' || !(@.cap.type() == "number") || @.cap < 0 || @.cap > 100 || @.cap != @.cap.floor()'
    ' || !(@.kind.type() == "string")'
    f" || !{jsonpath_one_of('@.kind', HORIZON_CAP_KINDS)}"
    ' || !(@.rule_id.type() == "string" || @.rule_id.type() == "null")'
    ' || !(@.inputs_missing.type() == "array")'
    # v0.2.6：gate 的 rule_id 必须是 HG1–HG6，且 inputs_missing 为空数组
    ' || (@.kind == "gate"'
    ' && !(@.rule_id.type() == "string" && @.rule_id like_regex "^HG[1-6]$"))'
    ' || (@.kind == "gate" && @.inputs_missing.size() != 0)'
)

#: HorizonHint（契约 v0.2.5 §5.1）：{horizon, rule_id 非空字符串, text 非空字符串}
HORIZON_HINT_BAD_ITEM = (
    '@.type() != "object"'
    ' || !(@.horizon.type() == "string")'
    f" || !{jsonpath_one_of('@.horizon', Horizon)}"
    ' || !(@.rule_id.type() == "string") || @.rule_id == ""'
    ' || !(@.text.type() == "string") || @.text == ""'
)

symbol_horizon_assessments = Table(
    "symbol_horizon_assessments",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("security_code", nullable=False),
    uuid_col("classifier_version_id", nullable=False, fk="app.horizon_classifier_versions.id"),
    uuid_col("snapshot_id", fk="app.data_snapshots.id"),
    jsonb("scores"),
    text_array("suitable_horizons"),
    jsonb("reasons"),
    uuid_array("recommended_strategy_version_ids"),
    txt("trigger"),
    #: 缺失的 f.* 输入键（契约 v0.2.3：只含 feature_catalog 键，去重升序，无缺失为空数组）
    text_array("inputs_missing", nullable=False, server_default=text("'{}'::text[]")),
    #: 每个周期的封顶原因 HorizonCap[]（契约 v0.2.3；迁移 0003）
    jsonb("caps", nullable=False, server_default=text("'[]'::jsonb")),
    #: 理由引用的证据 Evidence[]（契约 v0.2.3；plan 未写 NOT NULL，可空；迁移 0003）
    jsonb("evidence"),
    #: 画像类 mode: hint 规则的提示 HorizonHint[]（契约 v0.2.5 / T-A06；迁移 0005）
    jsonb("hints", nullable=False, server_default=text("'[]'::jsonb")),
    created_at(),
    array_subset("suitable_horizons", Horizon),
    one_of("trigger", HorizonAssessmentTrigger),
    # plan §3.3 T-A03：每项匹配 ^f\.[a-z0-9_]+$（写成 [.] 免转义）；NULL 元素也拒绝
    CheckConstraint(
        "NOT jsonb_path_exists(to_jsonb(inputs_missing),"
        ' \'$[*] ? (@.type() != "string" || !(@ like_regex "^f[.][a-z0-9_]+$"))\')',
        name="inputs_missing_keys",
    ),
    CheckConstraint(jsonb_array_items("caps", HORIZON_CAP_BAD_ITEM), name="caps_shape"),
    CheckConstraint(jsonb_array_items("hints", HORIZON_HINT_BAD_ITEM), name="hints_shape"),
    CheckConstraint(
        jsonb_array_items("evidence", EVIDENCE_BAD_ITEM, nullable=True), name="evidence_shape"
    ),
    schema=APP,
    comment="只追加（触发器）",
)

risk_control_settings = Table(
    "risk_control_settings",
    metadata,
    pk_uuid(),
    txt("scope", nullable=False),
    user_fk(nullable=True),
    txt("control", nullable=False),
    boolean("enabled", nullable=False, server_default=text("true")),
    jsonb("params"),
    ts("updated_at", nullable=False, default_now=True),
    one_of("scope", ["system", "user"]),
    one_of("control", RiskControl),
    UniqueConstraint("scope", "user_id", "control", postgresql_nulls_not_distinct=True),
    schema=APP,
)

risk_control_settings_history = Table(
    "risk_control_settings_history",
    metadata,
    pk_uuid(),
    uuid_col("setting_id", nullable=False, fk="app.risk_control_settings.id"),
    txt("scope", nullable=False),
    uuid_col("user_id"),
    txt("control", nullable=False),
    boolean("enabled"),
    jsonb("params"),
    uuid_col("changed_by", fk="app.users.id"),
    ts("changed_at", nullable=False, default_now=True),
    schema=APP,
    comment="plan 只写「变更写历史表」未给表名；本表名为后端拟定。只追加",
)

risk_events = Table(
    "risk_events",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("control", nullable=False),
    txt("level", nullable=False),
    txt("subject", nullable=False),
    txt("security_code"),
    jsonb("detail"),
    uuid_col("suggestion_id", fk="app.suggestions.id"),
    uuid_col("trade_id", fk="app.trades.id"),
    created_at(),
    one_of("control", RiskControl),
    one_of("level", RiskLevel),
    one_of("subject", ["account", "security", "strategy"]),
    schema=APP,
    comment="只追加（触发器）",
)

strategy_tracking_stats = Table(
    "strategy_tracking_stats",
    metadata,
    pk_uuid(),
    uuid_col("strategy_version_id", nullable=False, fk="app.strategy_versions.id"),
    txt("horizon", nullable=False),
    txt("scope", nullable=False),
    user_fk(nullable=True),
    integer("window_days", nullable=False),
    day("as_of_date", nullable=False),
    integer("n", nullable=False),
    integer("wins"),
    num("win_rate"),
    num("avg_return_pct"),
    num("avg_excess_pct"),
    num("profit_loss_ratio"),
    integer("max_loss_streak"),
    jsonb("recent"),
    one_of("horizon", Horizon),
    one_of("scope", ["user", "global"]),
    CheckConstraint("window_days IN (1, 5, 20)", name="window_days"),
    UniqueConstraint(
        "strategy_version_id",
        "horizon",
        "scope",
        "user_id",
        "window_days",
        "as_of_date",
        postgresql_nulls_not_distinct=True,
    ),
    schema=APP,
)

user_strategy_weights = Table(
    "user_strategy_weights",
    metadata,
    user_fk(),
    uuid_col("strategy_version_id", nullable=False, fk="app.strategy_versions.id"),
    txt("horizon", nullable=False),
    day("as_of_date", nullable=False),
    num("weight", nullable=False),
    num("raw"),
    integer("n"),
    jsonb("params"),
    jsonb("sample_range"),
    boolean("enabled_at_calc"),
    one_of("horizon", Horizon),
    PrimaryKeyConstraint("user_id", "strategy_version_id", "horizon", "as_of_date"),
    schema=APP,
    comment="原 strategy_priority_weights",
)

strategy_cards = Table(
    "strategy_cards",
    metadata,
    pk_uuid(),
    txt("key", nullable=False, unique=True),
    txt("title", nullable=False),
    uuid_col("current_version_id", fk="app.strategy_card_versions.id", use_alter=True),
    txt("completeness", nullable=False, server_default=text("'draft'")),
    uuid_col("owner_user_id", fk="app.users.id"),
    txt("source_kind", nullable=False),
    created_at(),
    one_of("completeness", CardCompleteness),
    one_of("source_kind", ["builtin", "admin", "user", "llm_draft", "reference"]),
    schema=APP,
    comment="L1 头表",
)

strategy_card_versions = Table(
    "strategy_card_versions",
    metadata,
    pk_uuid(),
    uuid_col("card_id", nullable=False, fk="app.strategy_cards.id"),
    integer("version_no", nullable=False),
    uuid_col("parent_version_id", fk="app.strategy_card_versions.id"),
    jsonb("fields", nullable=False),
    jsonb("field_epistemic"),
    jsonb("references"),
    jsonb("performance_log"),
    txt("changelog"),
    uuid_col("created_by", fk="app.users.id"),
    created_at(),
    UniqueConstraint("card_id", "version_no"),
    schema=APP,
    comment="L1 版本，不可变（触发器）",
)

rule_snippets = Table(
    "rule_snippets",
    metadata,
    pk_uuid(),
    txt("key", nullable=False),
    integer("version_no", nullable=False),
    txt("role", nullable=False),
    txt("expr", nullable=False),
    jsonb("params_schema"),
    text_array("required_features"),
    txt("description"),
    uuid_col("card_version_id", fk="app.strategy_card_versions.id"),
    created_at(),
    # plan 列 entry/exit/filter/veto/counter/invalidation；契约 rule_role 为超集（契约为准）
    one_of("role", RuleRole),
    UniqueConstraint("key", "version_no"),
    schema=APP,
    comment="不可变（触发器）",
)

feature_catalog = Table(
    "feature_catalog",
    metadata,
    txt("feature_key", nullable=False, primary_key=True),
    txt("description"),
    txt("dimension"),
    integer("warmup_bars"),
    txt("epistemic_type"),
    jsonb("source"),
    txt("derivation"),
    txt("unit"),
    txt("adjust"),
    txt("frequency"),
    jsonb("pit_rule"),
    txt("status", nullable=False, server_default=text("'declared'")),
    txt("pipeline_version"),
    txt("owner"),
    ts("updated_at", nullable=False, default_now=True),
    one_of("adjust", BarAdjust),
    one_of("frequency", ["1m", "daily", "quarterly", "event"]),
    # 契约 feature_status 比 plan 多 gap（契约为准）
    one_of("status", FeatureStatus),
    schema=APP,
    comment="DSL 白名单（G2、G3）",
)

strategy_promotion_reviews = Table(
    "strategy_promotion_reviews",
    metadata,
    pk_uuid(),
    uuid_col("card_version_id", fk="app.strategy_card_versions.id"),
    uuid_col("target_strategy_version_id", fk="app.strategy_versions.id"),
    jsonb("gate_results"),
    jsonb("fixture_runs"),
    jsonb("g6_report"),
    uuid_col("internal_eval_report_id"),
    jsonb("compliance_lint"),
    txt("decision", nullable=False, server_default=text("'pending'")),
    uuid_col("reviewer_id", fk="app.users.id"),
    ts("reviewed_at"),
    txt("note"),
    created_at(),
    one_of("decision", ["pending", "approved", "rejected", "changes_requested"]),
    schema=APP,
)

strategy_lifecycle_events = Table(
    "strategy_lifecycle_events",
    metadata,
    pk_uuid(),
    uuid_col("strategy_version_id", nullable=False, fk="app.strategy_versions.id"),
    txt("from_state"),
    txt("to_state", nullable=False),
    txt("reason"),
    txt("trigger", nullable=False),
    uuid_col("actor_id", fk="app.users.id"),
    ts("at", nullable=False, default_now=True),
    one_of("from_state", Lifecycle),
    one_of("to_state", Lifecycle),
    one_of("trigger", ["admin", "health_machine"]),
    schema=APP,
    comment="只追加（触发器）",
)

strategy_health_baselines = Table(
    "strategy_health_baselines",
    metadata,
    pk_uuid(),
    uuid_col("strategy_version_id", nullable=False, fk="app.strategy_versions.id"),
    ts("set_at", nullable=False, default_now=True),
    jsonb("tracking_baseline"),
    jsonb("oos_robustness_baseline"),
    schema=APP,
)

strategy_health_daily = Table(
    "strategy_health_daily",
    metadata,
    uuid_col("strategy_version_id", nullable=False, fk="app.strategy_versions.id"),
    day("as_of_date", nullable=False),
    integer("n"),
    num("weight"),
    num("raw"),
    jsonb("oos_robustness"),
    txt("state", nullable=False),
    txt("proposed_action", nullable=False, server_default=text("'none'")),
    jsonb("detail"),
    one_of("state", ["published", "observing"]),
    one_of("proposed_action", ["none", "review", "retire"]),
    PrimaryKeyConstraint("strategy_version_id", "as_of_date"),
    schema=APP,
)

strategy_instances = Table(
    "strategy_instances",
    metadata,
    pk_uuid(),
    user_fk(),
    uuid_col("strategy_version_id", nullable=False, fk="app.strategy_versions.id"),
    txt("scope", nullable=False),
    uuid_col("account_id", fk="app.accounts.id"),
    txt("security_code", comment="plan 写 security_id；按契约用文本代码"),
    txt("status", nullable=False, server_default=text("'proposed'")),
    txt("origin", nullable=False),
    jsonb("param_overrides"),
    uuid_col("derived_strategy_version_id", fk="app.strategy_versions.id"),
    jsonb("risk_settings_snapshot"),
    money("budget_amount"),
    boolean("auto_downweight", nullable=False, server_default=text("true")),
    created_at(),
    ts("confirmed_at"),
    # v0.2.7（契约 §5.1 StrategyInstance、§6.0A；迁移 0009）
    txt("horizon"),  # 旧行为空；T-B32 写入时必填
    txt("paused_by"),
    txt("pause_reason_code"),
    ts("paused_until"),
    ts("updated_at", nullable=False, default_now=True),
    ts("archived_at"),
    one_of("scope", ["account", "security", "watch_group"]),
    one_of("status", InstanceStatus),
    one_of("origin", InstanceOrigin),
    one_of("horizon", Horizon),
    one_of("paused_by", InstancePausedBy),
    one_of("pause_reason_code", ReasonCode),
    CheckConstraint(
        "(status = 'paused' AND paused_by IS NOT NULL"
        " AND (paused_by = 'system' OR (pause_reason_code IS NULL AND paused_until IS NULL)))"
        " OR (status <> 'paused' AND paused_by IS NULL AND pause_reason_code IS NULL"
        " AND paused_until IS NULL)",
        name="pause_fields",
    ),
    CheckConstraint("(status = 'archived') = (archived_at IS NOT NULL)", name="archived_at"),
    schema=APP,
    comment="L3 头表",  # security_code 只能是 stock/cdr（迁移 0009 触发器，ETF 不运行策略）
)
Index(
    "ix_strategy_instances_user_status_created",
    strategy_instances.c.user_id,
    strategy_instances.c.status,
    strategy_instances.c.created_at.desc(),
    strategy_instances.c.id.desc(),
)

strategy_instance_events = Table(
    "strategy_instance_events",
    metadata,
    pk_uuid(),
    uuid_col("instance_id", nullable=False, fk="app.strategy_instances.id"),
    txt("kind", nullable=False),
    jsonb("detail"),
    uuid_col("actor_id", fk="app.users.id"),
    ts("at", nullable=False, default_now=True),
    one_of("kind", ["created", "confirmed", "paused", "resumed", "params_changed", "archived"]),
    schema=APP,
    comment="只追加（触发器）",
)

market_rule_versions = Table(
    "market_rule_versions",
    metadata,
    pk_uuid(),
    day("effective_from", nullable=False),
    jsonb("rules", nullable=False),
    txt("source_note"),
    created_at(),
    UniqueConstraint("effective_from"),
    schema=APP,
    comment="按日期取当时有效版本；不可变（触发器）",
)

event_definitions = Table(
    "event_definitions",
    metadata,
    pk_uuid(),
    txt("key", nullable=False),
    integer("version_no", nullable=False),
    jsonb("source_rule", nullable=False),
    txt("direction"),
    txt("severity"),
    txt("dedup_window"),
    created_at(),
    UniqueConstraint("key", "version_no"),
    schema=APP,
    comment="不可变（触发器）",
)

llm_strategy_drafts = Table(
    "llm_strategy_drafts",
    metadata,
    pk_uuid(),
    uuid_col("requested_by", nullable=False, fk="app.users.id"),
    txt("input_text_hash", nullable=False),
    jsonb("output_json"),
    integer("correction_rounds", nullable=False, server_default=text("0")),
    jsonb("validation_errors"),
    txt("status", nullable=False, server_default=text("'draft'")),
    uuid_col("reviewer_id", fk="app.users.id"),
    uuid_array("llm_call_ids"),
    created_at(),
    one_of("status", ["draft", "rejected", "approved_to_card"]),
    CheckConstraint("correction_rounds BETWEEN 0 AND 3", name="correction_rounds"),
    schema=APP,
    comment="第三阶段启用",
)
