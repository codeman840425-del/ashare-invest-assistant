"""baseline：plan §3 全部表、不可变触发器、market schema、分区与 hypertable（T-B02）

Revision ID: 0001
Revises:
Create Date: 2026-11-01 20:17:06.023277+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# 手写部分：扩展、schema、触发器函数、不可变触发器、分区、hypertable、物化视图。
# 表结构本身见文件末尾 _create_tables()（autogenerate 产出，未手改）。
# ---------------------------------------------------------------------------

SCHEMAS = ("app", "market", "ops", "evaluation")

#: hypertable：(表, 时间列, chunk 间隔)。与 deploy/db/timescale/policies.conf 保持一致；
#: 压缩 / 保留 / 连续聚合由运维脚本 deploy/scripts/db-apply-timescale.sh 负责（迁移后运行）。
HYPERTABLES = (
    ("market.minute_bars", "ts", "1 day"),
    ("market.realtime_quotes", "ts", "1 day"),
    ("market.daily_bars", "trade_date", "1 year"),
    ("market.factor_values", "trade_date", "1 month"),
    ("market.feature_bars_daily", "trade_date", "1 year"),
    ("market.fund_flows", "trade_date", "1 year"),
    ("ops.ingest_request_log", "requested_at", "1 day"),
)

#: 环形引用的「当前版本」外键（元数据里 use_alter=True）：op.create_table 会跳过它们，
#: 建完全部表后单独添加。(表, 列, 被引用表)
USE_ALTER_FKS = (
    ("action_plans", "current_version_id", "plan_versions"),
    ("research_candidates", "current_version_id", "candidate_versions"),
    ("reviews", "current_version_id", "review_versions"),
    ("strategies", "current_version_id", "strategy_versions"),
    ("strategies", "copied_from_version_id", "strategy_versions"),
    ("strategy_cards", "current_version_id", "strategy_card_versions"),
    ("suggestion_threads", "current_suggestion_id", "suggestions"),
)

#: 按月声明式分区的表（plan §3A.6）：(表, 分区键)
MONTHLY_PARTITIONED = (("app.audit_logs", "at"), ("app.candidate_signals", "created_at"))

#: 只追加 / 版本正文不可变：禁止 UPDATE 与 DELETE
APPEND_ONLY = (
    "account_reviews",
    "user_profiles",
    "consents",
    "audit_logs",
    "broker_position_snapshots",
    "broker_position_snapshot_items",
    "candidate_versions",
    "claims",
    "plan_versions",
    "plan_conditions",
    "engine_policies",
    "horizon_classifier_versions",
    "symbol_horizon_assessments",
    "risk_control_settings_history",
    "risk_events",
    "strategy_card_versions",
    "rule_snippets",
    "strategy_lifecycle_events",
    "strategy_instance_events",
    "market_rule_versions",
    "event_definitions",
    "candidate_signal_events",
    "reason_status_events",
    "plan_draft_confirmations",
    "signal_events",
    "suggestion_user_actions",
    "daily_report_items",
    "realtime_settings",
    "data_snapshots",
    "review_versions",
)

#: 只允许改列出的列；DELETE 一律拒绝
RESTRICTED_UPDATE = {
    "trades": ("voided_at", "void_reason", "plan_version_id"),
    "candidate_signals": ("state", "state_changed_at"),
    "plan_drafts": ("status", "status_changed_at"),
    "suggestions": ("status", "superseded_by_id"),
}

FUNCTIONS_SQL = r"""
CREATE OR REPLACE FUNCTION app.reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '%.% 只追加/不可变：禁止 %', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'restrict_violation';
END $$;

-- 参数：允许变化的列名。其余列有任何变化即拒绝。
CREATE OR REPLACE FUNCTION app.restrict_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  changed text[];
BEGIN
  SELECT coalesce(array_agg(n.key ORDER BY n.key), '{}') INTO changed
    FROM jsonb_each(to_jsonb(NEW)) n
    JOIN jsonb_each(to_jsonb(OLD)) o USING (key)
   WHERE n.value IS DISTINCT FROM o.value AND NOT (n.key = ANY (TG_ARGV));
  IF cardinality(changed) > 0 THEN
    RAISE EXCEPTION '%.% 正文不可变：不允许修改列 %（只允许 %）',
      TG_TABLE_SCHEMA, TG_TABLE_NAME, changed, TG_ARGV
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;

-- 模板版本：published_at 为空（草稿）时可改；发布后只允许生命周期列变化，且不能撤销发布
CREATE OR REPLACE FUNCTION app.guard_strategy_versions() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.published_at IS NOT NULL THEN
      RAISE EXCEPTION 'app.strategy_versions 已发布版本不可删除' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.published_at IS NOT NULL AND
     (to_jsonb(NEW) - '{lifecycle,lifecycle_changed_by,lifecycle_changed_at}'::text[])
       IS DISTINCT FROM
     (to_jsonb(OLD) - '{lifecycle,lifecycle_changed_by,lifecycle_changed_at}'::text[]) THEN
    RAISE EXCEPTION 'app.strategy_versions 已发布版本正文不可变（只允许生命周期列）'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;

-- 提示词模板：draft 可改可删；激活后正文不可变，状态只能 active→retired
CREATE OR REPLACE FUNCTION app.guard_prompt_templates() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = 'draft' THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  IF TG_OP = 'DELETE'
     OR (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status')
     OR NOT (NEW.status = OLD.status OR (OLD.status = 'active' AND NEW.status = 'retired')) THEN
    RAISE EXCEPTION 'app.prompt_templates 激活后不可修改（只允许 active→retired）'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;

-- 日报：building 期间可写；ready/partial/failed 后不可变（重跑生成新 revision）
CREATE OR REPLACE FUNCTION app.guard_daily_reports() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'building' THEN
    RAISE EXCEPTION 'app.daily_reports 生成后不可变：禁止 %（重跑请生成新 revision）', TG_OP
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

-- 按月声明式分区：为 parent 建 [start_month, start_month + months) 的月分区与 DEFAULT 分区。
-- 分区名 <表>_pYYYYMM / <表>_default（alembic env 的 include_object 据此忽略子表）。
-- 注意：DEFAULT 分区里已有某月数据时，再建该月分区会失败（需先迁出），定时任务应提前建好下月分区。
CREATE OR REPLACE FUNCTION app.ensure_monthly_partitions(parent regclass, start_month date, months int)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE
  sch text; tbl text; m date; part text; created int := 0;
BEGIN
  SELECT n.nspname, c.relname INTO sch, tbl
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.oid = parent;
  FOR i IN 0 .. months - 1 LOOP
    m := (date_trunc('month', start_month) + make_interval(months => i))::date;
    part := format('%s_p%s', tbl, to_char(m, 'YYYYMM'));
    IF to_regclass(format('%I.%I', sch, part)) IS NULL THEN
      EXECUTE format('CREATE TABLE %I.%I PARTITION OF %s FOR VALUES FROM (%L) TO (%L)',
                     sch, part, parent, m::timestamptz AT TIME ZONE 'UTC',
                     (m + interval '1 month')::timestamptz AT TIME ZONE 'UTC');
      created := created + 1;
    END IF;
  END LOOP;
  IF to_regclass(format('%I.%I', sch, tbl || '_default')) IS NULL THEN
    EXECUTE format('CREATE TABLE %I.%I PARTITION OF %s DEFAULT', sch, tbl || '_default', parent);
    created := created + 1;
  END IF;
  RETURN created;
END $$;
"""

STRATEGY_RULES_SQL = r"""
CREATE MATERIALIZED VIEW app.strategy_rules AS
SELECT v.id                    AS strategy_version_id,
       r.value ->> 'id'        AS rule_id,
       r.value ->> 'dimension' AS dimension,
       r.value ->> 'role'      AS role,
       r.value ->> 'expr'      AS expr,
       (r.value ->> 'weight')::numeric AS weight,
       r.value -> 'required_data'      AS required_data
  FROM app.strategy_versions v
 CROSS JOIN LATERAL jsonb_array_elements(
       CASE WHEN jsonb_typeof(v.config -> 'rules') = 'array' THEN v.config -> 'rules'
            ELSE '[]'::jsonb END) AS r(value)
WITH NO DATA;
CREATE UNIQUE INDEX ux_strategy_rules_version_rule ON app.strategy_rules (strategy_version_id, rule_id);
CREATE INDEX ix_strategy_rules_dimension ON app.strategy_rules (dimension);
COMMENT ON MATERIALIZED VIEW app.strategy_rules IS
  '由 strategy_versions.config.rules 展开（plan §3.3），供检索哪些策略用到某因子/维度；发布新版本后 REFRESH ... CONCURRENTLY';
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.execute(FUNCTIONS_SQL)

    _create_tables()
    for table, column, referred in USE_ALTER_FKS:
        op.create_foreign_key(
            f"fk_{table}_{column}_{referred}",
            table,
            referred,
            [column],
            ["id"],
            source_schema="app",
            referent_schema="app",
        )

    # 不可变 / 只追加触发器
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_mutation()"
        )
    for table, cols in RESTRICTED_UPDATE.items():
        args = ", ".join(f"'{c}'" for c in cols)
        op.execute(
            f"CREATE TRIGGER trg_{table}_restrict_update BEFORE UPDATE ON app.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION app.restrict_update({args})"
        )
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_mutation()"
        )
    for table in ("strategy_versions", "prompt_templates", "daily_reports"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_guard BEFORE UPDATE OR DELETE ON app.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION app.guard_{table}()"
        )

    # 按月分区：当月起 3 个月 + DEFAULT（之后由定时任务按月调用 ensure_monthly_partitions）
    for table, _key in MONTHLY_PARTITIONED:
        op.execute(
            f"SELECT app.ensure_monthly_partitions('{table}'::regclass, "
            "(date_trunc('month', now() AT TIME ZONE 'UTC'))::date, 3)"
        )

    # hypertable（空表转换；不建默认索引，主键已含时间列）
    for table, time_col, chunk in HYPERTABLES:
        op.execute(
            f"SELECT create_hypertable('{table}', by_range('{time_col}', INTERVAL '{chunk}'), "
            "create_default_indexes => false, if_not_exists => true)"
        )

    op.execute(STRATEGY_RULES_SQL)


def downgrade() -> None:
    # 连续聚合（运维脚本建的 market.bars_*）、hypertable chunk、分区子表、触发器与函数
    # 都随 schema 一并删除；timescaledb 扩展保留（由镜像 / 运维管理）。
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def _create_tables() -> None:
    """autogenerate 产出（未手改）。"""
    op.create_table('audit_logs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_role', sa.Text(), nullable=True),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('target_type', sa.Text(), nullable=True),
    sa.Column('target_id', sa.Text(), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ip_hash', sa.Text(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', 'at', name=op.f('pk_audit_logs')),
    schema='app',
    comment='全站审计；按月分区；行不可改删（保留期通过 DROP 分区实现）',
    postgresql_partition_by='RANGE (at)'
    )
    op.create_table('candidate_signal_events',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('signal_id', sa.UUID(), nullable=False, comment='→ candidate_signals.id（分区表，无外键）'),
    sa.Column('from_state', sa.Text(), nullable=True),
    sa.Column('to_state', sa.Text(), nullable=False),
    sa.Column('cause', sa.Text(), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("cause IN ('executability_check', 'reason_released', 'user', 'expiry', 'invalidation', 'supersede')", name=op.f('ck_candidate_signal_events_cause')),
    sa.CheckConstraint("from_state IN ('open', 'drafted', 'blocked', 'released', 'confirmed', 'dismissed', 'expired', 'invalidated', 'superseded')", name=op.f('ck_candidate_signal_events_from_state')),
    sa.CheckConstraint("to_state IN ('open', 'drafted', 'blocked', 'released', 'confirmed', 'dismissed', 'expired', 'invalidated', 'superseded')", name=op.f('ck_candidate_signal_events_to_state')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_candidate_signal_events')),
    schema='app',
    comment='只追加（触发器）'
    )
    op.create_table('data_snapshots',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('known_events', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('hash', sa.Text(), nullable=False),
    sa.CheckConstraint("purpose IN ('candidate', 'plan', 'alert', 'review', 'screen', 'suggestion', 'signal', 'report')", name=op.f('ck_data_snapshots_purpose')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_data_snapshots')),
    schema='app',
    comment='不可变（触发器）'
    )
    op.create_table('dimension_definitions',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('coverage_gaps', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("key IN ('technical', 'capital', 'fundamental', 'sentiment', 'sector_market', 'news')", name=op.f('ck_dimension_definitions_key')),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_dimension_definitions')),
    schema='app'
    )
    op.create_table('engine_policies',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_engine_policies')),
    sa.UniqueConstraint('version_no', name=op.f('uq_engine_policies_version_no')),
    schema='app',
    comment='不可变（触发器）'
    )
    op.create_table('event_definitions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('source_rule', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('direction', sa.Text(), nullable=True),
    sa.Column('severity', sa.Text(), nullable=True),
    sa.Column('dedup_window', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_event_definitions')),
    sa.UniqueConstraint('key', 'version_no', name=op.f('uq_event_definitions_key_version_no')),
    schema='app',
    comment='不可变（触发器）'
    )
    op.create_table('feature_catalog',
    sa.Column('feature_key', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('source', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('derivation', sa.Text(), nullable=True),
    sa.Column('unit', sa.Text(), nullable=True),
    sa.Column('adjust', sa.Text(), nullable=True),
    sa.Column('frequency', sa.Text(), nullable=True),
    sa.Column('pit_rule', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'declared'"), nullable=False),
    sa.Column('pipeline_version', sa.Text(), nullable=True),
    sa.Column('owner', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("adjust IN ('none', 'qfq', 'hfq')", name=op.f('ck_feature_catalog_adjust')),
    sa.CheckConstraint("frequency IN ('1m', 'daily', 'quarterly', 'event')", name=op.f('ck_feature_catalog_frequency')),
    sa.CheckConstraint("status IN ('declared', 'verified_doc', 'verified_live', 'gap', 'deprecated')", name=op.f('ck_feature_catalog_status')),
    sa.PrimaryKeyConstraint('feature_key', name=op.f('pk_feature_catalog')),
    schema='app',
    comment='DSL 白名单（G2、G3）'
    )
    op.create_table('horizon_classifier_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_horizon_classifier_versions')),
    sa.UniqueConstraint('version_no', name=op.f('uq_horizon_classifier_versions_version_no')),
    schema='app',
    comment='不可变（触发器）'
    )
    op.create_table('intraday_universe',
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('tier', sa.Integer(), nullable=False),
    sa.Column('holders_count', sa.Integer(), nullable=True),
    sa.Column('watchers_count', sa.Integer(), nullable=True),
    sa.Column('focus_users_count', sa.Integer(), nullable=True),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('tier IN (1, 2, 3)', name=op.f('ck_intraday_universe_tier')),
    sa.PrimaryKeyConstraint('trade_date', 'security_code', name=op.f('pk_intraday_universe')),
    schema='app'
    )
    op.create_table('market_rule_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('rules', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_market_rule_versions')),
    sa.UniqueConstraint('effective_from', name=op.f('uq_market_rule_versions_effective_from')),
    schema='app',
    comment='按日期取当时有效版本；不可变（触发器）'
    )
    op.create_table('pipeline_runs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('run_date', sa.Date(), nullable=False),
    sa.Column('step', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.CheckConstraint("kind IN ('daily_batch', 'intraday_session', 'tracking')", name=op.f('ck_pipeline_runs_kind')),
    sa.CheckConstraint("status IN ('running', 'ok', 'partial', 'failed', 'skipped')", name=op.f('ck_pipeline_runs_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pipeline_runs')),
    schema='app'
    )
    op.create_table('plans',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('display_price_note', sa.Text(), nullable=True),
    sa.Column('sort', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'hidden', 'retired')", name=op.f('ck_plans_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plans')),
    sa.UniqueConstraint('code', name=op.f('uq_plans_code')),
    schema='app',
    comment='会员档位（不是行动计划；行动计划见 action_plans）'
    )
    op.create_table('users',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('username', sa.Text(), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('display_name', sa.Text(), nullable=True),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('apply_note', sa.Text(), nullable=True),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('failed_login_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("role IN ('user', 'admin')", name=op.f('ck_users_role')),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'disabled')", name=op.f('ck_users_status')),
    sa.CheckConstraint("username ~ '^[a-z0-9_]{4,32}$'", name=op.f('ck_users_username_format')),
    sa.CheckConstraint('failed_login_count >= 0', name=op.f('ck_users_failed_login_count_nonneg')),
    sa.ForeignKeyConstraint(['reviewed_by'], ['app.users.id'], name=op.f('fk_users_reviewed_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('username', name=op.f('uq_users_username')),
    schema='app'
    )
    op.create_table('eval_runs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('target', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('data_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'queued'"), nullable=False),
    sa.Column('cost_calls', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("kind IN ('factor_ic', 'event_study', 'param_robustness', 'daily_revalidation')", name=op.f('ck_eval_runs_kind')),
    sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed', 'cancelled')", name=op.f('ck_eval_runs_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eval_runs')),
    schema='evaluation'
    )
    op.create_table('announcements',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('level', sa.Text(), nullable=True),
    sa.Column('source', sa.Text(), server_default=sa.text("'mairui'"), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_announcements')),
    sa.UniqueConstraint('code', 'published_at', 'title', name=op.f('uq_announcements_code_published_at_title')),
    schema='market'
    )
    op.create_index('ix_announcements_code_published', 'announcements', ['code', sa.literal_column('published_at DESC')], unique=False, schema='market')
    op.create_table('daily_bars',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('adj_type', sa.Text(), server_default=sa.text("'none'"), nullable=False),
    sa.Column('open', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('high', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('low', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('close', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('volume', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("adj_type IN ('none', 'qfq', 'hfq')", name=op.f('ck_daily_bars_adj_type')),
    sa.PrimaryKeyConstraint('code', 'trade_date', 'adj_type', name=op.f('pk_daily_bars')),
    schema='market',
    comment='hypertable（trade_date，chunk 1 年）'
    )
    op.create_table('factor_values',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('factor_id', sa.Text(), nullable=False),
    sa.Column('value', sa.Numeric(), nullable=True),
    sa.Column('calc_version', sa.Text(), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('available_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('code', 'trade_date', 'factor_id', name=op.f('pk_factor_values')),
    schema='market',
    comment='hypertable（trade_date，chunk 1 个月：plan §3.3；§3A.6 写 1 年，内部冲突见报告）'
    )
    op.create_table('feature_bars_daily',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('feature_set_version', sa.Text(), nullable=False),
    sa.Column('values', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('code', 'trade_date', 'feature_set_version', name=op.f('pk_feature_bars_daily')),
    schema='market',
    comment='hypertable（trade_date，chunk 1 年）；唯一特征管线产出'
    )
    op.create_table('financial_reports',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('report_type', sa.Text(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('payload_hash', sa.Text(), nullable=False),
    sa.Column('announce_date', sa.Date(), nullable=True),
    sa.Column('available_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("report_type IN ('balance', 'income', 'cashflow', 'pershareindex')", name=op.f('ck_financial_reports_report_type')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_financial_reports')),
    sa.UniqueConstraint('code', 'report_type', 'period_end', 'payload_hash', name=op.f('uq_financial_reports_code_report_type_period_end_payload_hash')),
    schema='market',
    comment='数据变化时新增行（保留重述历史，按 first_seen_at / available_from 做 as-of）'
    )
    op.create_table('fund_flows',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('code', 'trade_date', name=op.f('pk_fund_flows')),
    schema='market',
    comment='hypertable（trade_date，chunk 1 年）'
    )
    op.create_table('minute_bars',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False, comment='bar 结束时间（契约 Bar.ts）：09:31 表示 09:30–09:31'),
    sa.Column('open', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('high', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('low', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('close', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('volume', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('pro_latest', 'pro_history')", name=op.f('ck_minute_bars_source')),
    sa.PrimaryKeyConstraint('code', 'ts', name=op.f('pk_minute_bars')),
    schema='market',
    comment='hypertable（ts，chunk 1 天）；ts 为 bar 结束时间'
    )
    op.create_table('qa_items',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=True),
    sa.Column('asked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_qa_items')),
    schema='market'
    )
    op.create_table('quotes_snapshot',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('price', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('pct_change', sa.Numeric(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('code', 'ts', name=op.f('pk_quotes_snapshot')),
    schema='market',
    comment='只保留当日 + 近 5 日（清理由后端定时任务做）'
    )
    op.create_table('raw_payloads',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('endpoint', sa.Text(), nullable=False, comment='接口路径模板，不含 licence'),
    sa.Column('params_hash', sa.Text(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.Text(), nullable=True),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('body_hash', sa.Text(), nullable=True),
    sa.Column('pinned', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_raw_payloads')),
    schema='market',
    comment='保留 90 天（被快照引用的 pinned=true 永久保留）'
    )
    op.create_index('ix_raw_payloads_endpoint_params', 'raw_payloads', ['endpoint', 'params_hash'], unique=False, schema='market')
    op.create_table('realtime_quotes',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('price', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('open', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('high', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('low', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('pre_close', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('volume', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('pct_change', sa.Numeric(), nullable=True),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('ssjy_more', 'ssjy_all', 'real_all')", name=op.f('ck_realtime_quotes_source')),
    sa.PrimaryKeyConstraint('code', 'ts', name=op.f('pk_realtime_quotes')),
    schema='market',
    comment='hypertable（ts=行情时间，chunk 1 天）；按分钟降采样'
    )
    op.create_table('securities',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('exchange', sa.Text(), nullable=False),
    sa.Column('board', sa.Text(), nullable=True),
    sa.Column('list_date', sa.Date(), nullable=True),
    sa.Column('status', sa.Text(), nullable=True),
    sa.Column('industry_codes', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("exchange IN ('SH', 'SZ', 'BJ')", name=op.f('ck_securities_exchange')),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_securities')),
    schema='market'
    )
    op.create_table('trading_calendar',
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('is_open', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('date', name=op.f('pk_trading_calendar')),
    schema='market'
    )
    op.create_table('ingest_leases',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('holder_host', sa.Text(), nullable=False),
    sa.Column('egress_ip', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_renewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_reason', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ingest_leases')),
    schema='ops',
    comment='单活锁历史（审计「任何时刻只有一个调用方」）'
    )
    op.create_table('ingest_request_log',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('requester', sa.Text(), nullable=False),
    sa.Column('priority', sa.Text(), nullable=False),
    sa.Column('dataset', sa.Text(), nullable=True),
    sa.Column('endpoint_key', sa.Text(), nullable=False),
    sa.Column('symbols_count', sa.Integer(), nullable=True),
    sa.Column('dedup_key', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('mairui_code', sa.Text(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("priority IN ('P0', 'P1', 'P2')", name=op.f('ck_ingest_request_log_priority')),
    sa.CheckConstraint("status IN ('queued', 'done', 'failed', 'dropped')", name=op.f('ck_ingest_request_log_status')),
    sa.PrimaryKeyConstraint('id', 'requested_at', name=op.f('pk_ingest_request_log')),
    schema='ops',
    comment='hypertable（requested_at，chunk 1 天，保留 30 天：运维策略）'
    )
    op.create_table('account_reviews',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('admin_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("action IN ('approve', 'reject', 'disable', 'enable', 'reset_password')", name=op.f('ck_account_reviews_action')),
    sa.ForeignKeyConstraint(['admin_id'], ['app.users.id'], name=op.f('fk_account_reviews_admin_id_users')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_account_reviews_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_account_reviews')),
    schema='app',
    comment='只追加：管理员审核历史（触发器禁止 UPDATE/DELETE）'
    )
    op.create_table('accounts',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('broker_label', sa.Text(), nullable=True, comment='自由文本，不存券商账号'),
    sa.Column('base_currency', sa.Text(), server_default=sa.text("'CNY'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_accounts_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_accounts')),
    schema='app'
    )
    op.create_table('claims',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('security_code', sa.Text(), nullable=True),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('epistemic_type', sa.Text(), nullable=False),
    sa.Column('source_kind', sa.Text(), nullable=False),
    sa.Column('source_ref', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('method_note', sa.Text(), nullable=True),
    sa.Column('verify_by', sa.Date(), nullable=True),
    sa.Column('confidence', sa.Numeric(), nullable=True),
    sa.Column('supersedes_claim_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("epistemic_type IN ('fact', 'estimate', 'hypothesis', 'execution')", name=op.f('ck_claims_epistemic_type')),
    sa.CheckConstraint("source_kind IN ('market_data', 'disclosure', 'user_input', 'system_calc')", name=op.f('ck_claims_source_kind')),
    sa.ForeignKeyConstraint(['supersedes_claim_id'], ['app.claims.id'], name=op.f('fk_claims_supersedes_claim_id_claims')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_claims_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_claims')),
    schema='app',
    comment='不可变（更正 = 新 claim + supersedes_claim_id）'
    )
    op.create_table('consents',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('doc_version', sa.Text(), nullable=False),
    sa.Column('granted', sa.Boolean(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ip_hash', sa.Text(), nullable=True),
    sa.CheckConstraint("kind IN ('privacy_policy', 'sensitive_financial_info', 'risk_disclosure', 'email_notification', 'signal_risk_disclosure')", name=op.f('ck_consents_kind')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_consents_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_consents')),
    schema='app'
    )
    op.create_table('entitlement_overrides',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['app.users.id'], name=op.f('fk_entitlement_overrides_created_by_users')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_entitlement_overrides_user_id_users')),
    sa.PrimaryKeyConstraint('user_id', 'key', name=op.f('pk_entitlement_overrides')),
    schema='app'
    )
    op.create_table('import_mappings',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('parser_id', sa.Text(), nullable=True),
    sa.Column('mapping', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_import_mappings_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_mappings')),
    schema='app'
    )
    op.create_table('llm_providers',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('base_url', sa.Text(), nullable=True),
    sa.Column('api_key_source', sa.Text(), server_default=sa.text("'db'"), nullable=False),
    sa.Column('api_key_ciphertext', postgresql.BYTEA(), nullable=True),
    sa.Column('key_version', sa.Integer(), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("api_key_source = 'db' OR api_key_ciphertext IS NULL", name=op.f('ck_llm_providers_env_key_not_stored')),
    sa.CheckConstraint("api_key_source IN ('env', 'db')", name=op.f('ck_llm_providers_api_key_source')),
    sa.CheckConstraint("kind IN ('openai_compatible', 'anthropic')", name=op.f('ck_llm_providers_kind')),
    sa.ForeignKeyConstraint(['created_by'], ['app.users.id'], name=op.f('fk_llm_providers_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_providers')),
    sa.UniqueConstraint('name', name=op.f('uq_llm_providers_name')),
    schema='app'
    )
    op.create_table('llm_strategy_drafts',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('requested_by', sa.UUID(), nullable=False),
    sa.Column('input_text_hash', sa.Text(), nullable=False),
    sa.Column('output_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('correction_rounds', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('validation_errors', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'draft'"), nullable=False),
    sa.Column('reviewer_id', sa.UUID(), nullable=True),
    sa.Column('llm_call_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'rejected', 'approved_to_card')", name=op.f('ck_llm_strategy_drafts_status')),
    sa.CheckConstraint('correction_rounds BETWEEN 0 AND 3', name=op.f('ck_llm_strategy_drafts_correction_rounds')),
    sa.ForeignKeyConstraint(['requested_by'], ['app.users.id'], name=op.f('fk_llm_strategy_drafts_requested_by_users')),
    sa.ForeignKeyConstraint(['reviewer_id'], ['app.users.id'], name=op.f('fk_llm_strategy_drafts_reviewer_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_strategy_drafts')),
    schema='app',
    comment='第三阶段启用'
    )
    op.create_table('login_attempts',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('username_tried', sa.Text(), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('ip_hash', sa.Text(), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_login_attempts_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_attempts')),
    schema='app',
    comment='限速、锁定与审计；保留 180 天（由定时任务删除，故不加不可变触发器）'
    )
    op.create_table('non_executable_reasons',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('signal_id', sa.UUID(), nullable=False, comment='→ candidate_signals.id（分区表，无外键）'),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('epistemic_type', sa.Text(), server_default=sa.text("'fact'"), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('release_condition', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('check_on', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('machine_checkable', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('next_check_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('release_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('released_by', sa.Text(), nullable=True, comment="'system' 或 user_id"),
    sa.CheckConstraint("check_on <@ ARRAY['tick', 'daily_close', 'schedule', 'holding_change', 'cash_update', 'import', 'plan_change', 'user_action']::text[]", name=op.f('ck_non_executable_reasons_check_on')),
    sa.CheckConstraint("code IN ('DATA_STALE', 'KEY_DATA_MISSING', 'LOW_CONFIDENCE', 'NON_TRADING_TIME', 'SUSPENDED', 'LIMIT_LOCKED', 'ST_OR_DELISTING', 'NEW_LISTING', 'INSUFFICIENT_CASH', 'T1_NOT_SELLABLE', 'NO_POSITION', 'POSITION_CAP_REACHED', 'STRATEGY_BUDGET_EXHAUSTED', 'SECTOR_EXPOSURE_EXCEEDED', 'REGIME_MISMATCH', 'SAME_DIRECTION_PLAN_EXISTS', 'CONFLICTS_CONFIRMED_PLAN', 'BLOCKLISTED', 'COOLING_OFF', 'LOSS_STREAK_PAUSE', 'STRATEGY_CONFLICT', 'USER_MUTED', 'PROFILE_OR_CONSENT_MISSING')", name=op.f('ck_non_executable_reasons_code')),
    sa.CheckConstraint("epistemic_type IN ('fact', 'estimate', 'hypothesis', 'execution')", name=op.f('ck_non_executable_reasons_epistemic_type')),
    sa.CheckConstraint("status IN ('active', 'released', 'obsolete')", name=op.f('ck_non_executable_reasons_status')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_non_executable_reasons_snapshot_id_data_snapshots')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_non_executable_reasons_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_non_executable_reasons')),
    schema='app'
    )
    op.create_index('ix_non_executable_reasons_active_check', 'non_executable_reasons', ['check_on', 'next_check_at'], unique=False, schema='app', postgresql_where=sa.text("status = 'active'"))
    op.create_table('notification_channel_bindings',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('target_ciphertext', postgresql.BYTEA(), nullable=True),
    sa.Column('target_masked', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending_verify'"), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('in_app', 'email', 'wecom_app')", name=op.f('ck_notification_channel_bindings_channel')),
    sa.CheckConstraint("status IN ('pending_verify', 'active', 'disabled', 'failed')", name=op.f('ck_notification_channel_bindings_status')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_notification_channel_bindings_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_channel_bindings')),
    schema='app'
    )
    op.create_table('notification_preferences',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('kinds', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('min_severity', sa.Text(), server_default=sa.text("'info'"), nullable=False),
    sa.Column('detail_level', sa.Text(), server_default=sa.text("'summary'"), nullable=False),
    sa.Column('quiet_hours', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('rate_per_min', sa.Integer(), nullable=True),
    sa.Column('rate_per_hour', sa.Integer(), nullable=True),
    sa.Column('digest_time', sa.Text(), nullable=True),
    sa.CheckConstraint("channel IN ('in_app', 'email', 'wecom_app')", name=op.f('ck_notification_preferences_channel')),
    sa.CheckConstraint("detail_level IN ('full', 'summary', 'ping')", name=op.f('ck_notification_preferences_detail_level')),
    sa.CheckConstraint("kinds <@ ARRAY['suggestion_change', 'invalidation', 'daily_report', 'alert', 'import', 'system', 'reason_released', 'plan_draft_ready', 'plan_triggered', 'strategy_health']::text[]", name=op.f('ck_notification_preferences_kinds')),
    sa.CheckConstraint("min_severity IN ('info', 'attention', 'important')", name=op.f('ck_notification_preferences_min_severity')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_notification_preferences_user_id_users')),
    sa.PrimaryKeyConstraint('user_id', 'channel', name=op.f('pk_notification_preferences')),
    schema='app'
    )
    op.create_table('notifications',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('severity', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('security_code', sa.Text(), nullable=True),
    sa.Column('target_type', sa.Text(), server_default=sa.text("'none'"), nullable=False),
    sa.Column('target_id', sa.Text(), nullable=True),
    sa.Column('target_route', sa.Text(), nullable=True),
    sa.Column('dedup_key', sa.Text(), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('suggestion_change', 'invalidation', 'daily_report', 'alert', 'import', 'system', 'reason_released', 'plan_draft_ready', 'plan_triggered', 'strategy_health')", name=op.f('ck_notifications_kind')),
    sa.CheckConstraint("severity IN ('info', 'attention', 'important')", name=op.f('ck_notifications_severity')),
    sa.CheckConstraint("target_type IN ('suggestion', 'candidate_signal', 'plan_draft', 'plan', 'daily_report', 'import_batch', 'reconciliation', 'strategy_version', 'none')", name=op.f('ck_notifications_target_type')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_notifications_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
    sa.UniqueConstraint('user_id', 'dedup_key', name=op.f('uq_notifications_user_id_dedup_key')),
    schema='app'
    )
    op.create_index('ix_notifications_user_read_created', 'notifications', ['user_id', sa.literal_column('read_at ASC NULLS FIRST'), sa.literal_column('created_at DESC')], unique=False, schema='app')
    op.create_table('plan_entitlements',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['app.plans.id'], name=op.f('fk_plan_entitlements_plan_id_plans')),
    sa.PrimaryKeyConstraint('plan_id', 'key', name=op.f('pk_plan_entitlements')),
    schema='app'
    )
    op.create_table('prompt_templates',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('system_text', sa.Text(), nullable=False),
    sa.Column('user_template', sa.Text(), nullable=False),
    sa.Column('output_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'draft'"), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'active', 'retired')", name=op.f('ck_prompt_templates_status')),
    sa.CheckConstraint("task IN ('suggestion_rationale', 'daily_report_stock', 'daily_report_summary', 'strategy_divergence', 'announcement_title_digest')", name=op.f('ck_prompt_templates_task')),
    sa.ForeignKeyConstraint(['created_by'], ['app.users.id'], name=op.f('fk_prompt_templates_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prompt_templates')),
    sa.UniqueConstraint('task', 'version_no', name=op.f('uq_prompt_templates_task_version_no')),
    schema='app',
    comment='激活后正文不可变，只允许 status active→retired（触发器）'
    )
    op.create_table('realtime_settings',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('changed_by', sa.UUID(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['changed_by'], ['app.users.id'], name=op.f('fk_realtime_settings_changed_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_realtime_settings')),
    sa.UniqueConstraint('version_no', name=op.f('uq_realtime_settings_version_no')),
    schema='app',
    comment='管理员配置历史（只追加）；默认值来自 config/realtime.yaml'
    )
    op.create_table('risk_control_settings',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('control', sa.Text(), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("control IN ('stop_take', 'position_cap', 'total_exposure', 'sector_concentration', 'loss_streak_drawdown', 'plan_violation')", name=op.f('ck_risk_control_settings_control')),
    sa.CheckConstraint("scope IN ('system', 'user')", name=op.f('ck_risk_control_settings_scope')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_risk_control_settings_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_control_settings')),
    sa.UniqueConstraint('scope', 'user_id', 'control', name=op.f('uq_risk_control_settings_scope_user_id_control'), postgresql_nulls_not_distinct=True),
    schema='app'
    )
    op.create_table('signal_events',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tick_id', sa.Text(), nullable=True),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('from_state', sa.Text(), nullable=True),
    sa.Column('to_state', sa.Text(), nullable=True),
    sa.Column('trigger_kind', sa.Text(), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('quote_ts', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(scope = 'user') = (user_id IS NOT NULL)", name=op.f('ck_signal_events_scope_user')),
    sa.CheckConstraint("scope IN ('shared', 'user')", name=op.f('ck_signal_events_scope')),
    sa.CheckConstraint("trigger_kind IN ('flip', 'invalidation', 'stale', 'resume')", name=op.f('ck_signal_events_trigger_kind')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_signal_events_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signal_events')),
    schema='app',
    comment='只追加（触发器）'
    )
    op.create_table('strategies',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('owner_user_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('horizons', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('copied_from_version_id', sa.UUID(), nullable=True),
    sa.Column('current_version_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("horizons <@ ARRAY['intraday_t', 'short', 'swing', 'long']::text[]", name=op.f('ck_strategies_horizons')),
    sa.CheckConstraint("status IN ('active', 'archived')", name=op.f('ck_strategies_status')),
    sa.ForeignKeyConstraint(['copied_from_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategies_copied_from_version_id_strategy_versions'), use_alter=True),
    sa.ForeignKeyConstraint(['current_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategies_current_version_id_strategy_versions'), use_alter=True),
    sa.ForeignKeyConstraint(['owner_user_id'], ['app.users.id'], name=op.f('fk_strategies_owner_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategies')),
    sa.UniqueConstraint('key', name=op.f('uq_strategies_key')),
    schema='app',
    comment='L2 模板头表（即 strategy_templates）'
    )
    op.create_table('strategy_cards',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('current_version_id', sa.UUID(), nullable=True),
    sa.Column('completeness', sa.Text(), server_default=sa.text("'draft'"), nullable=False),
    sa.Column('owner_user_id', sa.UUID(), nullable=True),
    sa.Column('source_kind', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("completeness IN ('draft', 'documented', 'runnable_candidate', 'promoted', 'retired')", name=op.f('ck_strategy_cards_completeness')),
    sa.CheckConstraint("source_kind IN ('builtin', 'admin', 'user', 'llm_draft', 'reference')", name=op.f('ck_strategy_cards_source_kind')),
    sa.ForeignKeyConstraint(['current_version_id'], ['app.strategy_card_versions.id'], name=op.f('fk_strategy_cards_current_version_id_strategy_card_versions'), use_alter=True),
    sa.ForeignKeyConstraint(['owner_user_id'], ['app.users.id'], name=op.f('fk_strategy_cards_owner_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_cards')),
    sa.UniqueConstraint('key', name=op.f('uq_strategy_cards_key')),
    schema='app',
    comment='L1 头表'
    )
    op.create_table('symbol_horizon_assessments',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('classifier_version_id', sa.UUID(), nullable=False),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('scores', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('suitable_horizons', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('recommended_strategy_version_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.Column('trigger', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("suitable_horizons <@ ARRAY['intraday_t', 'short', 'swing', 'long']::text[]", name=op.f('ck_symbol_horizon_assessments_suitable_horizons')),
    sa.CheckConstraint("trigger IN ('import', 'watchlist_add', 'weekly')", name=op.f('ck_symbol_horizon_assessments_trigger')),
    sa.ForeignKeyConstraint(['classifier_version_id'], ['app.horizon_classifier_versions.id'], name=op.f('fk_symbol_horizon_assessments_classifier_version_id_horizon_classifier_versions')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_symbol_horizon_assessments_snapshot_id_data_snapshots')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_symbol_horizon_assessments_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_symbol_horizon_assessments')),
    schema='app',
    comment='只追加（触发器）'
    )
    op.create_table('user_profiles',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('capital_range', sa.Text(), nullable=True),
    sa.Column('horizon', sa.Text(), nullable=True),
    sa.Column('risk_tolerance', sa.Integer(), nullable=True),
    sa.Column('max_drawdown_pct', sa.Numeric(), nullable=True),
    sa.Column('weekly_hours', sa.Numeric(), nullable=True),
    sa.Column('focus_areas', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("horizon IN ('short', 'medium', 'long')", name=op.f('ck_user_profiles_horizon')),
    sa.CheckConstraint('risk_tolerance BETWEEN 1 AND 5', name=op.f('ck_user_profiles_risk_tolerance_range')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_user_profiles_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_profiles')),
    sa.UniqueConstraint('user_id', 'version_no', name=op.f('uq_user_profiles_user_id_version_no')),
    schema='app',
    comment='只追加：最新版本为当前画像（触发器禁止 UPDATE/DELETE）'
    )
    op.create_table('user_realtime_prefs',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('notify_cadence', sa.Text(), server_default=sa.text("'1m'"), nullable=False),
    sa.Column('focus_codes', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("notify_cadence IN ('realtime', '1m', '3m', '5m')", name=op.f('ck_user_realtime_prefs_notify_cadence')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_user_realtime_prefs_user_id_users')),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_realtime_prefs')),
    schema='app'
    )
    op.create_table('user_restrictions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('target_type', sa.Text(), nullable=False),
    sa.Column('target_id', sa.Text(), nullable=False, comment='security_code 或实体 uuid（文本）'),
    sa.Column('until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("kind IN ('blocklist', 'cooling_off', 'mute')", name=op.f('ck_user_restrictions_kind')),
    sa.CheckConstraint("target_type IN ('security', 'strategy', 'instance')", name=op.f('ck_user_restrictions_target_type')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_user_restrictions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_restrictions')),
    schema='app'
    )
    op.create_table('user_signal_states',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('source_id', sa.UUID(), nullable=True),
    sa.Column('condition', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('state', sa.Text(), server_default=sa.text("'unknown'"), nullable=False),
    sa.Column('last_tick_id', sa.Text(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('suggestion_invalidation', 'plan_condition', 'user_rule')", name=op.f('ck_user_signal_states_source')),
    sa.CheckConstraint("state IN ('true', 'false', 'unknown')", name=op.f('ck_user_signal_states_state')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_user_signal_states_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_signal_states')),
    schema='app'
    )
    op.create_table('user_subscriptions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source', sa.Text(), server_default=sa.text("'manual_admin'"), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.CheckConstraint("source IN ('manual_admin', 'payment_reserved')", name=op.f('ck_user_subscriptions_source')),
    sa.CheckConstraint("status IN ('active', 'expired', 'cancelled')", name=op.f('ck_user_subscriptions_status')),
    sa.ForeignKeyConstraint(['created_by'], ['app.users.id'], name=op.f('fk_user_subscriptions_created_by_users')),
    sa.ForeignKeyConstraint(['plan_id'], ['app.plans.id'], name=op.f('fk_user_subscriptions_plan_id_plans')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_user_subscriptions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_subscriptions')),
    schema='app'
    )
    op.create_table('watchlist_items',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('group_name', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_watchlist_items_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_watchlist_items')),
    schema='app'
    )
    op.create_table('eval_results',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='全部附 n'),
    sa.Column('folds', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('robustness', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['evaluation.eval_runs.id'], name=op.f('fk_eval_results_run_id_eval_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eval_results')),
    schema='evaluation'
    )
    op.create_table('market_events',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('type', sa.Text(), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('event_definition_id', sa.UUID(), nullable=True),
    sa.Column('source', sa.Text(), server_default=sa.text("'rule'"), nullable=False),
    sa.Column('confidence', sa.Numeric(), nullable=True),
    sa.Column('original_title', sa.Text(), nullable=True),
    sa.Column('original_url', sa.Text(), nullable=True),
    sa.Column('review_status', sa.Text(), nullable=True),
    sa.CheckConstraint("source IN ('rule', 'llm')", name=op.f('ck_market_events_source')),
    sa.ForeignKeyConstraint(['event_definition_id'], ['app.event_definitions.id'], name=op.f('fk_market_events_event_definition_id_event_definitions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_market_events')),
    schema='market'
    )
    op.create_table('cash_movements',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.CheckConstraint("kind IN ('deposit', 'withdraw', 'dividend', 'fee', 'adjust')", name=op.f('ck_cash_movements_kind')),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_cash_movements_account_id_accounts')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cash_movements')),
    schema='app'
    )
    op.create_table('claim_links',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('claim_id', sa.UUID(), nullable=False),
    sa.Column('target_type', sa.Text(), nullable=False),
    sa.Column('target_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.CheckConstraint("role IN ('reason', 'counter', 'risk', 'invalidation', 'outcome')", name=op.f('ck_claim_links_role')),
    sa.CheckConstraint("target_type IN ('candidate_version', 'plan_version', 'review_version', 'alert')", name=op.f('ck_claim_links_target_type')),
    sa.ForeignKeyConstraint(['claim_id'], ['app.claims.id'], name=op.f('fk_claim_links_claim_id_claims')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_claim_links')),
    sa.UniqueConstraint('claim_id', 'target_type', 'target_id', 'role', name=op.f('uq_claim_links_claim_id_target_type_target_id_role')),
    schema='app'
    )
    op.create_table('holdings',
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=20, scale=4), nullable=False),
    sa.Column('avg_cost', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('realized_pnl', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('last_trade_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rebuilt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rebuild_batch_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_holdings_account_id_accounts')),
    sa.PrimaryKeyConstraint('account_id', 'security_code', name=op.f('pk_holdings')),
    schema='app',
    comment='派生表：由 opening_positions + trades + account_events 全量重放重建'
    )
    op.create_table('import_batches',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('parser_id', sa.Text(), nullable=True),
    sa.Column('parser_version', sa.Text(), nullable=True),
    sa.Column('detected_encoding', sa.Text(), nullable=True),
    sa.Column('encoding_override', sa.Text(), nullable=True),
    sa.Column('mapping', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('snapshot_as_of', sa.DateTime(timezone=True), nullable=True),
    sa.Column('file_findings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('committed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reverted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('uploaded', 'parsing', 'previewed', 'committed', 'failed', 'discarded', 'reverted')", name=op.f('ck_import_batches_status')),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_import_batches_account_id_accounts')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_import_batches_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_batches')),
    schema='app'
    )
    op.create_table('llm_models',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('provider_id', sa.UUID(), nullable=False),
    sa.Column('model_name', sa.Text(), nullable=False),
    sa.Column('context_window', sa.Integer(), nullable=True),
    sa.Column('price_input_per_1k', sa.Numeric(), nullable=True),
    sa.Column('price_output_per_1k', sa.Numeric(), nullable=True),
    sa.Column('currency', sa.Text(), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.ForeignKeyConstraint(['provider_id'], ['app.llm_providers.id'], name=op.f('fk_llm_models_provider_id_llm_providers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_models')),
    sa.UniqueConstraint('provider_id', 'model_name', name=op.f('uq_llm_models_provider_id_model_name')),
    schema='app'
    )
    op.create_table('notification_deliveries',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('notification_id', sa.UUID(), nullable=False),
    sa.Column('binding_id', sa.UUID(), nullable=True),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'queued'"), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('provider_msg_id', sa.Text(), nullable=True),
    sa.Column('error_code', sa.Text(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("channel IN ('in_app', 'email', 'wecom_app')", name=op.f('ck_notification_deliveries_channel')),
    sa.CheckConstraint("status IN ('queued', 'sent', 'failed', 'retrying', 'dropped')", name=op.f('ck_notification_deliveries_status')),
    sa.ForeignKeyConstraint(['binding_id'], ['app.notification_channel_bindings.id'], name=op.f('fk_notification_deliveries_binding_id_notification_channel_bindings')),
    sa.ForeignKeyConstraint(['notification_id'], ['app.notifications.id'], name=op.f('fk_notification_deliveries_notification_id_notifications')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_deliveries')),
    schema='app'
    )
    op.create_table('opening_positions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=20, scale=4), nullable=False),
    sa.Column('cost_price', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('epistemic_type', sa.Text(), server_default=sa.text("'fact'"), nullable=False),
    sa.Column('source_kind', sa.Text(), server_default=sa.text("'user_input'"), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_opening_positions_account_id_accounts')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_opening_positions')),
    schema='app'
    )
    op.create_table('reason_status_events',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('reason_id', sa.UUID(), nullable=False),
    sa.Column('from_status', sa.Text(), nullable=True),
    sa.Column('to_status', sa.Text(), nullable=False),
    sa.Column('evaluated_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("from_status IN ('active', 'released', 'obsolete')", name=op.f('ck_reason_status_events_from_status')),
    sa.CheckConstraint("to_status IN ('active', 'released', 'obsolete')", name=op.f('ck_reason_status_events_to_status')),
    sa.ForeignKeyConstraint(['reason_id'], ['app.non_executable_reasons.id'], name=op.f('fk_reason_status_events_reason_id_non_executable_reasons')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reason_status_events')),
    schema='app',
    comment='只追加（触发器）'
    )
    op.create_table('risk_control_settings_history',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('setting_id', sa.UUID(), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('control', sa.Text(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=True),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('changed_by', sa.UUID(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['changed_by'], ['app.users.id'], name=op.f('fk_risk_control_settings_history_changed_by_users')),
    sa.ForeignKeyConstraint(['setting_id'], ['app.risk_control_settings.id'], name=op.f('fk_risk_control_settings_history_setting_id_risk_control_settings')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_control_settings_history')),
    schema='app',
    comment='plan 只写「变更写历史表」未给表名；本表名为后端拟定。只追加'
    )
    op.create_table('strategy_card_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('card_id', sa.UUID(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('parent_version_id', sa.UUID(), nullable=True),
    sa.Column('fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('field_epistemic', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('references', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('performance_log', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('changelog', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['card_id'], ['app.strategy_cards.id'], name=op.f('fk_strategy_card_versions_card_id_strategy_cards')),
    sa.ForeignKeyConstraint(['created_by'], ['app.users.id'], name=op.f('fk_strategy_card_versions_created_by_users')),
    sa.ForeignKeyConstraint(['parent_version_id'], ['app.strategy_card_versions.id'], name=op.f('fk_strategy_card_versions_parent_version_id_strategy_card_versions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_card_versions')),
    sa.UniqueConstraint('card_id', 'version_no', name=op.f('uq_strategy_card_versions_card_id_version_no')),
    schema='app',
    comment='L1 版本，不可变（触发器）'
    )
    op.create_table('suggestion_threads',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=True),
    sa.Column('current_suggestion_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('user_decision', sa.Text(), server_default=sa.text("'none'"), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'superseded', 'invalidated', 'expired')", name=op.f('ck_suggestion_threads_status')),
    sa.CheckConstraint("user_decision IN ('none', 'accepted', 'dismissed', 'acted')", name=op.f('ck_suggestion_threads_user_decision')),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_suggestion_threads_account_id_accounts')),
    sa.ForeignKeyConstraint(['current_suggestion_id'], ['app.suggestions.id'], name=op.f('fk_suggestion_threads_current_suggestion_id_suggestions'), use_alter=True),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_suggestion_threads_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_suggestion_threads')),
    schema='app',
    comment='头表'
    )
    op.create_table('account_events',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('occurred_on', sa.Date(), nullable=False),
    sa.Column('import_batch_id', sa.UUID(), nullable=True),
    sa.Column('dedup_key', sa.Text(), nullable=True),
    sa.CheckConstraint("kind IN ('dividend', 'bonus_share', 'rights', 'transfer_in', 'transfer_out', 'ipo_allot', 'fee', 'interest', 'other')", name=op.f('ck_account_events_kind')),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_account_events_account_id_accounts')),
    sa.ForeignKeyConstraint(['import_batch_id'], ['app.import_batches.id'], name=op.f('fk_account_events_import_batch_id_import_batches')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_account_events')),
    sa.UniqueConstraint('account_id', 'dedup_key', name=op.f('uq_account_events_account_id_dedup_key')),
    schema='app'
    )
    op.create_table('broker_position_snapshots',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('import_batch_id', sa.UUID(), nullable=True),
    sa.Column('as_of', sa.DateTime(timezone=True), nullable=True),
    sa.Column('currency', sa.Text(), nullable=True),
    sa.Column('cash_balance', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('cash_available', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('cash_withdrawable', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('market_value_ref', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('total_assets_ref', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('pnl_ref', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_broker_position_snapshots_account_id_accounts')),
    sa.ForeignKeyConstraint(['import_batch_id'], ['app.import_batches.id'], name=op.f('fk_broker_position_snapshots_import_batch_id_import_batches')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_broker_position_snapshots')),
    sa.UniqueConstraint('account_id', 'version_no', name=op.f('uq_broker_position_snapshots_account_id_version_no')),
    schema='app',
    comment='券商口径快照（epistemic_type=fact），只追加'
    )
    op.create_table('import_files',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('batch_id', sa.UUID(), nullable=False),
    sa.Column('original_filename', sa.Text(), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('sha256', sa.Text(), nullable=True),
    sa.Column('storage_path', sa.Text(), nullable=True),
    sa.Column('retained_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['app.import_batches.id'], name=op.f('fk_import_files_batch_id_import_batches')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_files')),
    schema='app'
    )
    op.create_table('llm_calls',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('provider_id', sa.UUID(), nullable=True),
    sa.Column('model_id', sa.UUID(), nullable=True),
    sa.Column('prompt_template_id', sa.UUID(), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('validation_errors', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('cost_estimate', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('target_type', sa.Text(), nullable=True),
    sa.Column('target_id', sa.Text(), nullable=True),
    sa.Column('request_hash', sa.Text(), nullable=True),
    sa.Column('request_body', postgresql.BYTEA(), nullable=True, comment='加密；保留 90 天'),
    sa.Column('response_body', postgresql.BYTEA(), nullable=True, comment='加密；保留 90 天'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('ok', 'timeout', 'error', 'validation_failed', 'fallback_template')", name=op.f('ck_llm_calls_status')),
    sa.CheckConstraint("task IN ('suggestion_rationale', 'daily_report_stock', 'daily_report_summary', 'strategy_divergence', 'announcement_title_digest')", name=op.f('ck_llm_calls_task')),
    sa.ForeignKeyConstraint(['model_id'], ['app.llm_models.id'], name=op.f('fk_llm_calls_model_id_llm_models')),
    sa.ForeignKeyConstraint(['prompt_template_id'], ['app.prompt_templates.id'], name=op.f('fk_llm_calls_prompt_template_id_prompt_templates')),
    sa.ForeignKeyConstraint(['provider_id'], ['app.llm_providers.id'], name=op.f('fk_llm_calls_provider_id_llm_providers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_calls')),
    schema='app'
    )
    op.create_table('llm_task_routes',
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('primary_model_id', sa.UUID(), nullable=True),
    sa.Column('fallback_model_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.Column('timeout_s', sa.Integer(), nullable=True),
    sa.Column('max_retries', sa.Integer(), nullable=True),
    sa.Column('temperature', sa.Numeric(), nullable=True),
    sa.Column('max_output_tokens', sa.Integer(), nullable=True),
    sa.Column('daily_budget', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('prompt_template_id', sa.UUID(), nullable=True),
    sa.CheckConstraint("task IN ('suggestion_rationale', 'daily_report_stock', 'daily_report_summary', 'strategy_divergence', 'announcement_title_digest')", name=op.f('ck_llm_task_routes_task')),
    sa.ForeignKeyConstraint(['primary_model_id'], ['app.llm_models.id'], name=op.f('fk_llm_task_routes_primary_model_id_llm_models')),
    sa.ForeignKeyConstraint(['prompt_template_id'], ['app.prompt_templates.id'], name=op.f('fk_llm_task_routes_prompt_template_id_prompt_templates')),
    sa.PrimaryKeyConstraint('task', name=op.f('pk_llm_task_routes')),
    schema='app'
    )
    op.create_table('rule_snippets',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('expr', sa.Text(), nullable=False),
    sa.Column('params_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('required_features', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('card_version_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('entry', 'hold', 'weakening', 'exit', 'filter', 'veto', 'counter', 'invalidation')", name=op.f('ck_rule_snippets_role')),
    sa.ForeignKeyConstraint(['card_version_id'], ['app.strategy_card_versions.id'], name=op.f('fk_rule_snippets_card_version_id_strategy_card_versions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rule_snippets')),
    sa.UniqueConstraint('key', 'version_no', name=op.f('uq_rule_snippets_key_version_no')),
    schema='app',
    comment='不可变（触发器）'
    )
    op.create_table('strategy_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('strategy_id', sa.UUID(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('config_hash', sa.Text(), nullable=False),
    sa.Column('changelog', sa.Text(), nullable=True),
    sa.Column('published_by', sa.UUID(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('card_version_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.Text(), server_default=sa.text("'rule_template'"), nullable=False),
    sa.Column('code_entry', sa.Text(), nullable=True),
    sa.Column('parent_version_id', sa.UUID(), nullable=True),
    sa.Column('param_hash', sa.Text(), nullable=True),
    sa.Column('params_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('rule_snippet_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('feature_set_version', sa.Text(), nullable=True),
    sa.Column('lifecycle', sa.Text(), server_default=sa.text("'draft'"), nullable=False),
    sa.Column('lifecycle_changed_by', sa.UUID(), nullable=True),
    sa.Column('lifecycle_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('rule_template', 'code')", name=op.f('ck_strategy_versions_kind')),
    sa.CheckConstraint("lifecycle IN ('draft', 'simulating', 'published', 'observing', 'retired')", name=op.f('ck_strategy_versions_lifecycle')),
    sa.ForeignKeyConstraint(['card_version_id'], ['app.strategy_card_versions.id'], name=op.f('fk_strategy_versions_card_version_id_strategy_card_versions')),
    sa.ForeignKeyConstraint(['lifecycle_changed_by'], ['app.users.id'], name=op.f('fk_strategy_versions_lifecycle_changed_by_users')),
    sa.ForeignKeyConstraint(['parent_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategy_versions_parent_version_id_strategy_versions')),
    sa.ForeignKeyConstraint(['published_by'], ['app.users.id'], name=op.f('fk_strategy_versions_published_by_users')),
    sa.ForeignKeyConstraint(['strategy_id'], ['app.strategies.id'], name=op.f('fk_strategy_versions_strategy_id_strategies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_versions')),
    sa.UniqueConstraint('strategy_id', 'version_no', name=op.f('uq_strategy_versions_strategy_id_version_no')),
    schema='app',
    comment='L2 版本：published_at 非空后正文不可变，只允许生命周期列变化（触发器）'
    )
    op.create_table('broker_position_snapshot_items',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('snapshot_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('sellable_quantity', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('broker_cost_price', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('last_price_ref', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('market_value_ref', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('unrealized_pnl_ref', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('unrealized_pnl_pct_ref', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('shareholder_code_hmac', sa.Text(), nullable=True),
    sa.Column('shareholder_code_masked', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.broker_position_snapshots.id'], name=op.f('fk_broker_position_snapshot_items_snapshot_id_broker_position_snapshots')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_broker_position_snapshot_items')),
    schema='app',
    comment='随快照只追加'
    )
    op.create_table('daily_reports',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=True),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('revision', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'building'"), nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='契约 §5.3 DailyReport 全文'),
    sa.Column('explanation_text', sa.Text(), nullable=True),
    sa.Column('explanation_source', sa.Text(), nullable=True),
    sa.Column('llm_call_id', sa.UUID(), nullable=True),
    sa.Column('gaps', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("explanation_source IN ('template', 'llm')", name=op.f('ck_daily_reports_explanation_source')),
    sa.CheckConstraint("status IN ('building', 'ready', 'partial', 'failed')", name=op.f('ck_daily_reports_status')),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_daily_reports_account_id_accounts')),
    sa.ForeignKeyConstraint(['llm_call_id'], ['app.llm_calls.id'], name=op.f('fk_daily_reports_llm_call_id_llm_calls')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_daily_reports_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_daily_reports')),
    sa.UniqueConstraint('user_id', 'trade_date', 'revision', name=op.f('uq_daily_reports_user_id_trade_date_revision')),
    schema='app',
    comment='status 进入 ready/partial/failed 后不可变（触发器）；重跑生成新 revision'
    )
    op.create_table('reconciliation_runs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('trigger', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('matched', 'diff', 'not_imported')", name=op.f('ck_reconciliation_runs_status')),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_reconciliation_runs_account_id_accounts')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.broker_position_snapshots.id'], name=op.f('fk_reconciliation_runs_snapshot_id_broker_position_snapshots')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reconciliation_runs')),
    schema='app'
    )
    op.create_table('signal_states',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('strategy_version_id', sa.UUID(), nullable=False),
    sa.Column('params_hash', sa.Text(), nullable=False),
    sa.Column('rule_states', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('state', sa.Text(), nullable=True),
    sa.Column('last_tick_id', sa.Text(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_signal_states_strategy_version_id_strategy_versions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signal_states')),
    sa.UniqueConstraint('security_code', 'strategy_version_id', 'params_hash', name=op.f('uq_signal_states_security_code_strategy_version_id_params_hash')),
    schema='app',
    comment='全站共享的当前状态'
    )
    op.create_table('strategy_health_baselines',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('strategy_version_id', sa.UUID(), nullable=False),
    sa.Column('set_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tracking_baseline', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('oos_robustness_baseline', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategy_health_baselines_strategy_version_id_strategy_versions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_health_baselines')),
    schema='app'
    )
    op.create_table('strategy_health_daily',
    sa.Column('strategy_version_id', sa.UUID(), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('n', sa.Integer(), nullable=True),
    sa.Column('weight', sa.Numeric(), nullable=True),
    sa.Column('raw', sa.Numeric(), nullable=True),
    sa.Column('oos_robustness', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('proposed_action', sa.Text(), server_default=sa.text("'none'"), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("proposed_action IN ('none', 'review', 'retire')", name=op.f('ck_strategy_health_daily_proposed_action')),
    sa.CheckConstraint("state IN ('published', 'observing')", name=op.f('ck_strategy_health_daily_state')),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategy_health_daily_strategy_version_id_strategy_versions')),
    sa.PrimaryKeyConstraint('strategy_version_id', 'as_of_date', name=op.f('pk_strategy_health_daily')),
    schema='app'
    )
    op.create_table('strategy_instances',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('strategy_version_id', sa.UUID(), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=True),
    sa.Column('security_code', sa.Text(), nullable=True, comment='plan 写 security_id；按契约用文本代码'),
    sa.Column('status', sa.Text(), server_default=sa.text("'proposed'"), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('param_overrides', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('derived_strategy_version_id', sa.UUID(), nullable=True),
    sa.Column('risk_settings_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('fit_ack', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('budget_amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('auto_downweight', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("origin IN ('classifier', 'user')", name=op.f('ck_strategy_instances_origin')),
    sa.CheckConstraint("scope IN ('account', 'security', 'watch_group')", name=op.f('ck_strategy_instances_scope')),
    sa.CheckConstraint("status IN ('proposed', 'active', 'paused', 'archived')", name=op.f('ck_strategy_instances_status')),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_strategy_instances_account_id_accounts')),
    sa.ForeignKeyConstraint(['derived_strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategy_instances_derived_strategy_version_id_strategy_versions')),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategy_instances_strategy_version_id_strategy_versions')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_strategy_instances_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_instances')),
    schema='app',
    comment='L3 头表'
    )
    op.create_table('strategy_lifecycle_events',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('strategy_version_id', sa.UUID(), nullable=False),
    sa.Column('from_state', sa.Text(), nullable=True),
    sa.Column('to_state', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('trigger', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("from_state IN ('draft', 'simulating', 'published', 'observing', 'retired')", name=op.f('ck_strategy_lifecycle_events_from_state')),
    sa.CheckConstraint("to_state IN ('draft', 'simulating', 'published', 'observing', 'retired')", name=op.f('ck_strategy_lifecycle_events_to_state')),
    sa.CheckConstraint("trigger IN ('admin', 'health_machine')", name=op.f('ck_strategy_lifecycle_events_trigger')),
    sa.ForeignKeyConstraint(['actor_id'], ['app.users.id'], name=op.f('fk_strategy_lifecycle_events_actor_id_users')),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategy_lifecycle_events_strategy_version_id_strategy_versions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_lifecycle_events')),
    schema='app',
    comment='只追加（触发器）'
    )
    op.create_table('strategy_promotion_reviews',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('card_version_id', sa.UUID(), nullable=True),
    sa.Column('target_strategy_version_id', sa.UUID(), nullable=True),
    sa.Column('gate_results', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('fixture_runs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('g6_report', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('internal_eval_report_id', sa.UUID(), nullable=True),
    sa.Column('compliance_lint', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('decision', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('reviewer_id', sa.UUID(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("decision IN ('pending', 'approved', 'rejected', 'changes_requested')", name=op.f('ck_strategy_promotion_reviews_decision')),
    sa.ForeignKeyConstraint(['card_version_id'], ['app.strategy_card_versions.id'], name=op.f('fk_strategy_promotion_reviews_card_version_id_strategy_card_versions')),
    sa.ForeignKeyConstraint(['reviewer_id'], ['app.users.id'], name=op.f('fk_strategy_promotion_reviews_reviewer_id_users')),
    sa.ForeignKeyConstraint(['target_strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategy_promotion_reviews_target_strategy_version_id_strategy_versions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_promotion_reviews')),
    schema='app'
    )
    op.create_table('strategy_runs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('strategy_version_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('trade_date', sa.Date(), nullable=True),
    sa.Column('universe', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('feature_set_version', sa.Text(), nullable=True),
    sa.Column('strategy_version_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('result_count', sa.Integer(), nullable=True),
    sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('screen')", name=op.f('ck_strategy_runs_kind')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_strategy_runs_snapshot_id_data_snapshots')),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategy_runs_strategy_version_id_strategy_versions')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_strategy_runs_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_runs')),
    schema='app',
    comment='plan §3.3 两处定义合并：扫描批次（取代 screen_runs）；逐股结果写 candidate_signals'
    )
    op.create_table('strategy_tracking_stats',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('strategy_version_id', sa.UUID(), nullable=False),
    sa.Column('horizon', sa.Text(), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('window_days', sa.Integer(), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('n', sa.Integer(), nullable=False),
    sa.Column('wins', sa.Integer(), nullable=True),
    sa.Column('win_rate', sa.Numeric(), nullable=True),
    sa.Column('avg_return_pct', sa.Numeric(), nullable=True),
    sa.Column('avg_excess_pct', sa.Numeric(), nullable=True),
    sa.Column('profit_loss_ratio', sa.Numeric(), nullable=True),
    sa.Column('max_loss_streak', sa.Integer(), nullable=True),
    sa.Column('recent', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("horizon IN ('intraday_t', 'short', 'swing', 'long')", name=op.f('ck_strategy_tracking_stats_horizon')),
    sa.CheckConstraint("scope IN ('user', 'global')", name=op.f('ck_strategy_tracking_stats_scope')),
    sa.CheckConstraint('window_days IN (1, 5, 20)', name=op.f('ck_strategy_tracking_stats_window_days')),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_strategy_tracking_stats_strategy_version_id_strategy_versions')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_strategy_tracking_stats_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_tracking_stats')),
    sa.UniqueConstraint('strategy_version_id', 'horizon', 'scope', 'user_id', 'window_days', 'as_of_date', name=op.f('uq_strategy_tracking_stats_strategy_version_id_horizon_scope_user_id_window_days_as_of_date'), postgresql_nulls_not_distinct=True),
    schema='app'
    )
    op.create_table('suggestions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('thread_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('seq_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('strategies', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('executability', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('candidate_signal_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.Column('plan_draft_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.Column('consensus', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('dimension_matrix', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('divergence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('risk_flags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('strategy_version_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.Column('engine_policy_id', sa.UUID(), nullable=True),
    sa.Column('horizon_assessment_id', sa.UUID(), nullable=True),
    sa.Column('profile_version_id', sa.UUID(), nullable=True),
    sa.Column('holding_context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('feature_set_version', sa.Text(), nullable=True),
    sa.Column('data_status', sa.Text(), nullable=False),
    sa.Column('reference_price', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('reference_price_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('explanation_text', sa.Text(), nullable=True),
    sa.Column('explanation_source', sa.Text(), nullable=True),
    sa.Column('llm_call_id', sa.UUID(), nullable=True),
    sa.Column('prompt_template_id', sa.UUID(), nullable=True),
    sa.Column('generated_by', sa.Text(), nullable=True),
    sa.Column('supersedes_id', sa.UUID(), nullable=True),
    sa.Column('superseded_by_id', sa.UUID(), nullable=True),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("data_status IN ('fresh', 'stale', 'pending', 'partial', 'unavailable')", name=op.f('ck_suggestions_data_status')),
    sa.CheckConstraint("explanation_source IN ('template', 'llm')", name=op.f('ck_suggestions_explanation_source')),
    sa.CheckConstraint("origin IN ('daily_batch', 'intraday_event', 'manual_refresh')", name=op.f('ck_suggestions_origin')),
    sa.CheckConstraint("status IN ('active', 'superseded', 'invalidated', 'expired')", name=op.f('ck_suggestions_status')),
    sa.ForeignKeyConstraint(['engine_policy_id'], ['app.engine_policies.id'], name=op.f('fk_suggestions_engine_policy_id_engine_policies')),
    sa.ForeignKeyConstraint(['horizon_assessment_id'], ['app.symbol_horizon_assessments.id'], name=op.f('fk_suggestions_horizon_assessment_id_symbol_horizon_assessments')),
    sa.ForeignKeyConstraint(['llm_call_id'], ['app.llm_calls.id'], name=op.f('fk_suggestions_llm_call_id_llm_calls')),
    sa.ForeignKeyConstraint(['prompt_template_id'], ['app.prompt_templates.id'], name=op.f('fk_suggestions_prompt_template_id_prompt_templates')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_suggestions_snapshot_id_data_snapshots')),
    sa.ForeignKeyConstraint(['superseded_by_id'], ['app.suggestions.id'], name=op.f('fk_suggestions_superseded_by_id_suggestions')),
    sa.ForeignKeyConstraint(['supersedes_id'], ['app.suggestions.id'], name=op.f('fk_suggestions_supersedes_id_suggestions')),
    sa.ForeignKeyConstraint(['thread_id'], ['app.suggestion_threads.id'], name=op.f('fk_suggestions_thread_id_suggestion_threads')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_suggestions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_suggestions')),
    sa.UniqueConstraint('thread_id', 'seq_no', name=op.f('uq_suggestions_thread_id_seq_no')),
    schema='app',
    comment='除 status、superseded_by_id 外不可变（触发器）'
    )
    op.create_index('ix_suggestions_user_created', 'suggestions', ['user_id', sa.literal_column('created_at DESC')], unique=False, schema='app')
    op.create_table('user_strategy_weights',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('strategy_version_id', sa.UUID(), nullable=False),
    sa.Column('horizon', sa.Text(), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('weight', sa.Numeric(), nullable=False),
    sa.Column('raw', sa.Numeric(), nullable=True),
    sa.Column('n', sa.Integer(), nullable=True),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('sample_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('enabled_at_calc', sa.Boolean(), nullable=True),
    sa.CheckConstraint("horizon IN ('intraday_t', 'short', 'swing', 'long')", name=op.f('ck_user_strategy_weights_horizon')),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_user_strategy_weights_strategy_version_id_strategy_versions')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_user_strategy_weights_user_id_users')),
    sa.PrimaryKeyConstraint('user_id', 'strategy_version_id', 'horizon', 'as_of_date', name=op.f('pk_user_strategy_weights')),
    schema='app',
    comment='原 strategy_priority_weights'
    )
    op.create_table('candidate_signals',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('instance_id', sa.UUID(), nullable=True),
    sa.Column('strategy_version_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False, comment='plan 写 security_id；按契约用文本代码'),
    sa.Column('horizon', sa.Text(), nullable=False),
    sa.Column('proposed_action', sa.Text(), nullable=False),
    sa.Column('t_leg', sa.Text(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('confidence_level', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Numeric(), nullable=True),
    sa.Column('stops', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('rule_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('counter_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('invalidation', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('model_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('gate_results', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('risk_flags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('crowding_flag', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('feature_set_version', sa.Text(), nullable=True),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cooldown_key', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('state', sa.Text(), server_default=sa.text("'open'"), nullable=False),
    sa.Column('state_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("confidence_level IN ('high', 'medium', 'low')", name=op.f('ck_candidate_signals_confidence_level')),
    sa.CheckConstraint("horizon IN ('intraday_t', 'short', 'swing', 'long')", name=op.f('ck_candidate_signals_horizon')),
    sa.CheckConstraint("jsonb_typeof(rule_refs) = 'array' AND jsonb_array_length(rule_refs) > 0 AND jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) > 0 AND jsonb_typeof(counter_evidence) = 'array' AND jsonb_array_length(counter_evidence) > 0 AND jsonb_typeof(invalidation) = 'array' AND jsonb_array_length(invalidation) > 0", name=op.f('ck_candidate_signals_explainable')),
    sa.CheckConstraint("proposed_action IN ('buy', 'add', 'hold', 'reduce', 'sell', 'wait')", name=op.f('ck_candidate_signals_proposed_action')),
    sa.CheckConstraint("state IN ('open', 'drafted', 'blocked', 'released', 'confirmed', 'dismissed', 'expired', 'invalidated', 'superseded')", name=op.f('ck_candidate_signals_state')),
    sa.CheckConstraint("t_leg IN ('sell_first', 'buy_first')", name=op.f('ck_candidate_signals_t_leg')),
    sa.CheckConstraint('jsonb_typeof(model_refs) = \'array\' AND NOT jsonb_path_exists(model_refs, \'$[*] ? (@.role != "auxiliary")\')', name=op.f('ck_candidate_signals_model_refs_auxiliary')),
    sa.CheckConstraint('score BETWEEN 0 AND 100', name=op.f('ck_candidate_signals_score')),
    sa.ForeignKeyConstraint(['instance_id'], ['app.strategy_instances.id'], name=op.f('fk_candidate_signals_instance_id_strategy_instances')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_candidate_signals_snapshot_id_data_snapshots')),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['app.strategy_versions.id'], name=op.f('fk_candidate_signals_strategy_version_id_strategy_versions')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_candidate_signals_user_id_users')),
    sa.PrimaryKeyConstraint('id', 'created_at', name=op.f('pk_candidate_signals')),
    schema='app',
    comment='正文不可变，只允许 state / state_changed_at 变化（触发器）；按月分区',
    postgresql_partition_by='RANGE (created_at)'
    )
    op.create_index('ix_candidate_signals_instance_created', 'candidate_signals', ['instance_id', sa.literal_column('created_at DESC')], unique=False, schema='app')
    op.create_index('ix_candidate_signals_security_created', 'candidate_signals', ['security_code', sa.literal_column('created_at DESC')], unique=False, schema='app')
    op.create_index('ix_candidate_signals_user_created', 'candidate_signals', ['user_id', sa.literal_column('created_at DESC'), 'id'], unique=False, schema='app')
    op.create_table('daily_report_items',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('report_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('relation', sa.Text(), nullable=False),
    sa.Column('facts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('strategy_results', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('suggestion_id', sa.UUID(), nullable=True),
    sa.Column('explanation_text', sa.Text(), nullable=True),
    sa.CheckConstraint("relation IN ('holding', 'watchlist')", name=op.f('ck_daily_report_items_relation')),
    sa.ForeignKeyConstraint(['report_id'], ['app.daily_reports.id'], name=op.f('fk_daily_report_items_report_id_daily_reports')),
    sa.ForeignKeyConstraint(['suggestion_id'], ['app.suggestions.id'], name=op.f('fk_daily_report_items_suggestion_id_suggestions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_daily_report_items')),
    schema='app',
    comment='随日报不可变（触发器）'
    )
    op.create_table('plan_drafts',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('signal_ids', sa.ARRAY(sa.UUID()), nullable=False),
    sa.Column('instance_id', sa.UUID(), nullable=True),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('qty_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('price_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('stops', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('max_loss_amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('max_loss_pct', sa.Numeric(), nullable=True),
    sa.Column('fee_estimate', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('user_context_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('risk_flags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('judgment_checklist', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('market_rule_version_id', sa.UUID(), nullable=True),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('status_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("action IN ('buy', 'add', 'hold', 'reduce', 'sell', 'wait')", name=op.f('ck_plan_drafts_action')),
    sa.CheckConstraint("status IN ('pending', 'confirmed', 'discarded', 'expired', 'stale')", name=op.f('ck_plan_drafts_status')),
    sa.CheckConstraint('cardinality(signal_ids) >= 1', name=op.f('ck_plan_drafts_signal_ids_nonempty')),
    sa.ForeignKeyConstraint(['instance_id'], ['app.strategy_instances.id'], name=op.f('fk_plan_drafts_instance_id_strategy_instances')),
    sa.ForeignKeyConstraint(['market_rule_version_id'], ['app.market_rule_versions.id'], name=op.f('fk_plan_drafts_market_rule_version_id_market_rule_versions')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_plan_drafts_snapshot_id_data_snapshots')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_plan_drafts_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plan_drafts')),
    schema='app',
    comment='正文不可变，只允许 status / status_changed_at 变化（触发器）'
    )
    op.create_index('ix_plan_drafts_user_status_expires', 'plan_drafts', ['user_id', 'status', 'expires_at'], unique=False, schema='app')
    op.create_table('reconciliation_items',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=True),
    sa.Column('ours', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('broker', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('diff', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('possible_causes', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('suggested_actions', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('resolution', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("kind IN ('quantity_mismatch', 'missing_in_broker', 'missing_in_ours', 'cost_differs', 'cash_gap', 'cash_chain_break')", name=op.f('ck_reconciliation_items_kind')),
    sa.ForeignKeyConstraint(['run_id'], ['app.reconciliation_runs.id'], name=op.f('fk_reconciliation_items_run_id_reconciliation_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reconciliation_items')),
    schema='app'
    )
    op.create_table('research_candidates',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('strategy_run_id', sa.UUID(), nullable=True),
    sa.Column('suggestion_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('current_version_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("origin IN ('strategy_screen', 'suggestion', 'manual', 'from_stock')", name=op.f('ck_research_candidates_origin')),
    sa.CheckConstraint("status IN ('researching', 'watching', 'dropped', 'planned')", name=op.f('ck_research_candidates_status')),
    sa.ForeignKeyConstraint(['current_version_id'], ['app.candidate_versions.id'], name=op.f('fk_research_candidates_current_version_id_candidate_versions'), use_alter=True),
    sa.ForeignKeyConstraint(['strategy_run_id'], ['app.strategy_runs.id'], name=op.f('fk_research_candidates_strategy_run_id_strategy_runs')),
    sa.ForeignKeyConstraint(['suggestion_id'], ['app.suggestions.id'], name=op.f('fk_research_candidates_suggestion_id_suggestions')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_research_candidates_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_research_candidates')),
    schema='app'
    )
    op.create_table('strategy_instance_events',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('instance_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('created', 'confirmed', 'paused', 'resumed', 'params_changed', 'archived')", name=op.f('ck_strategy_instance_events_kind')),
    sa.ForeignKeyConstraint(['actor_id'], ['app.users.id'], name=op.f('fk_strategy_instance_events_actor_id_users')),
    sa.ForeignKeyConstraint(['instance_id'], ['app.strategy_instances.id'], name=op.f('fk_strategy_instance_events_instance_id_strategy_instances')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_instance_events')),
    schema='app',
    comment='只追加（触发器）'
    )
    op.create_table('suggestion_tracking',
    sa.Column('suggestion_id', sa.UUID(), nullable=False),
    sa.Column('horizon_days', sa.Integer(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('ref_price', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('close_price', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('return_pct', sa.Numeric(), nullable=True),
    sa.Column('benchmark_code', sa.Text(), nullable=True),
    sa.Column('benchmark_return_pct', sa.Numeric(), nullable=True),
    sa.Column('excess_pct', sa.Numeric(), nullable=True),
    sa.Column('max_drawdown_pct', sa.Numeric(), nullable=True),
    sa.Column('max_runup_pct', sa.Numeric(), nullable=True),
    sa.Column('invalidation_hit_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('direction_correct', sa.Boolean(), nullable=True),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'done', 'not_applicable')", name=op.f('ck_suggestion_tracking_status')),
    sa.CheckConstraint('horizon_days IN (1, 5, 20)', name=op.f('ck_suggestion_tracking_horizon_days')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_suggestion_tracking_snapshot_id_data_snapshots')),
    sa.ForeignKeyConstraint(['suggestion_id'], ['app.suggestions.id'], name=op.f('fk_suggestion_tracking_suggestion_id_suggestions')),
    sa.PrimaryKeyConstraint('suggestion_id', 'horizon_days', name=op.f('pk_suggestion_tracking')),
    schema='app'
    )
    op.create_table('action_plans',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=True),
    sa.Column('candidate_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('current_version_id', sa.UUID(), nullable=True),
    sa.Column('origin', sa.Text(), server_default=sa.text("'manual'"), nullable=False),
    sa.Column('plan_draft_id', sa.UUID(), nullable=True),
    sa.Column('candidate_signal_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(origin = 'plan_draft') = (plan_draft_id IS NOT NULL) AND (origin = 'plan_draft' OR candidate_signal_ids IS NULL OR cardinality(candidate_signal_ids) = 0)", name=op.f('ck_action_plans_origin_link')),
    sa.CheckConstraint("origin IN ('manual', 'plan_draft')", name=op.f('ck_action_plans_origin')),
    sa.CheckConstraint("status IN ('draft', 'pending_review', 'active', 'triggered', 'executed', 'invalidated', 'closed', 'done', 'cancelled')", name=op.f('ck_action_plans_status')),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_action_plans_account_id_accounts')),
    sa.ForeignKeyConstraint(['candidate_id'], ['app.research_candidates.id'], name=op.f('fk_action_plans_candidate_id_research_candidates')),
    sa.ForeignKeyConstraint(['current_version_id'], ['app.plan_versions.id'], name=op.f('fk_action_plans_current_version_id_plan_versions'), use_alter=True),
    sa.ForeignKeyConstraint(['plan_draft_id'], ['app.plan_drafts.id'], name=op.f('fk_action_plans_plan_draft_id_plan_drafts')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_action_plans_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_action_plans')),
    schema='app'
    )
    op.create_table('candidate_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('candidate_id', sa.UUID(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('thesis', sa.Text(), nullable=True),
    sa.Column('conditions_to_hold', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('counter_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('fit_assessment', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('decision', sa.Text(), nullable=True),
    sa.Column('decision_reason', sa.Text(), nullable=True),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.CheckConstraint("decision IN ('continue', 'watch', 'drop')", name=op.f('ck_candidate_versions_decision')),
    sa.ForeignKeyConstraint(['candidate_id'], ['app.research_candidates.id'], name=op.f('fk_candidate_versions_candidate_id_research_candidates')),
    sa.ForeignKeyConstraint(['created_by'], ['app.users.id'], name=op.f('fk_candidate_versions_created_by_users')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_candidate_versions_snapshot_id_data_snapshots')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_candidate_versions')),
    sa.UniqueConstraint('candidate_id', 'version_no', name=op.f('uq_candidate_versions_candidate_id_version_no')),
    schema='app',
    comment='不可变（触发器）'
    )
    op.create_table('plan_draft_confirmations',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('draft_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('checklist_answers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('risk_ack', sa.Boolean(), nullable=False),
    sa.Column('chosen_qty', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('chosen_price', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('deviation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('plan_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('risk_ack', name=op.f('ck_plan_draft_confirmations_risk_ack_true')),
    sa.ForeignKeyConstraint(['draft_id'], ['app.plan_drafts.id'], name=op.f('fk_plan_draft_confirmations_draft_id_plan_drafts')),
    sa.ForeignKeyConstraint(['plan_id'], ['app.action_plans.id'], name=op.f('fk_plan_draft_confirmations_plan_id_action_plans')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_plan_draft_confirmations_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plan_draft_confirmations')),
    sa.UniqueConstraint('draft_id', name=op.f('uq_plan_draft_confirmations_draft_id')),
    schema='app',
    comment='只追加（触发器）'
    )
    op.create_table('plan_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('size_amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('size_pct_of_assets', sa.Numeric(), nullable=True),
    sa.Column('max_loss_amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('risks', sa.Text(), nullable=True),
    sa.Column('review_date', sa.Date(), nullable=True),
    sa.Column('change_reason', sa.Text(), nullable=True),
    sa.Column('completeness', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('market_rule_version_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("action IN ('buy', 'add', 'hold', 'reduce', 'sell', 'wait')", name=op.f('ck_plan_versions_action')),
    sa.ForeignKeyConstraint(['market_rule_version_id'], ['app.market_rule_versions.id'], name=op.f('fk_plan_versions_market_rule_version_id_market_rule_versions')),
    sa.ForeignKeyConstraint(['plan_id'], ['app.action_plans.id'], name=op.f('fk_plan_versions_plan_id_action_plans')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_plan_versions_snapshot_id_data_snapshots')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plan_versions')),
    sa.UniqueConstraint('plan_id', 'version_no', name=op.f('uq_plan_versions_plan_id_version_no')),
    schema='app',
    comment='不可变（触发器）'
    )
    op.create_table('reviews',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('plan_id', sa.UUID(), nullable=True),
    sa.Column('security_code', sa.Text(), nullable=True),
    sa.Column('period_start', sa.Date(), nullable=True),
    sa.Column('period_end', sa.Date(), nullable=True),
    sa.Column('current_version_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['current_version_id'], ['app.review_versions.id'], name=op.f('fk_reviews_current_version_id_review_versions'), use_alter=True),
    sa.ForeignKeyConstraint(['plan_id'], ['app.action_plans.id'], name=op.f('fk_reviews_plan_id_action_plans')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_reviews_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reviews')),
    schema='app'
    )
    op.create_table('plan_conditions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('plan_version_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('type', sa.Text(), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('epistemic_type', sa.Text(), server_default=sa.text("'hypothesis'"), nullable=False),
    sa.CheckConstraint("epistemic_type IN ('fact', 'estimate', 'hypothesis', 'execution')", name=op.f('ck_plan_conditions_epistemic_type')),
    sa.CheckConstraint("kind IN ('trigger', 'invalidation')", name=op.f('ck_plan_conditions_kind')),
    sa.CheckConstraint("type IN ('price_above', 'price_below', 'pct_change', 'indicator', 'event', 'date', 'custom')", name=op.f('ck_plan_conditions_type')),
    sa.ForeignKeyConstraint(['plan_version_id'], ['app.plan_versions.id'], name=op.f('fk_plan_conditions_plan_version_id_plan_versions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plan_conditions')),
    schema='app',
    comment='随 plan_versions 不可变（触发器）'
    )
    op.create_table('review_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('review_id', sa.UUID(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('plan_version_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.Column('trade_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.Column('outcome_metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('attribution', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('lessons', sa.Text(), nullable=True),
    sa.Column('tags', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['review_id'], ['app.reviews.id'], name=op.f('fk_review_versions_review_id_reviews')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_review_versions_snapshot_id_data_snapshots')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_review_versions')),
    sa.UniqueConstraint('review_id', 'version_no', name=op.f('uq_review_versions_review_id_version_no')),
    schema='app',
    comment='不可变（触发器）'
    )
    op.create_table('trades',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=False),
    sa.Column('side', sa.Text(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=20, scale=4), nullable=False),
    sa.Column('price', sa.Numeric(precision=20, scale=4), nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('commission', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('stamp_tax', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('transfer_fee', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('other_fee', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('net_amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('traded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('broker_trade_no', sa.Text(), nullable=True),
    sa.Column('order_no', sa.Text(), nullable=True),
    sa.Column('declare_no', sa.Text(), nullable=True),
    sa.Column('cash_balance_after', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('shareholder_code_hmac', sa.Text(), nullable=True),
    sa.Column('shareholder_code_masked', sa.Text(), nullable=True),
    sa.Column('plan_version_id', sa.UUID(), nullable=True),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('import_batch_id', sa.UUID(), nullable=True),
    sa.Column('import_row_no', sa.Integer(), nullable=True),
    sa.Column('dedup_key', sa.Text(), nullable=True),
    sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('void_reason', sa.Text(), nullable=True),
    sa.Column('replaces_trade_id', sa.UUID(), nullable=True),
    sa.Column('epistemic_type', sa.Text(), server_default=sa.text("'execution'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("epistemic_type IN ('execution')", name=op.f('ck_trades_epistemic_type')),
    sa.CheckConstraint("side IN ('buy', 'sell')", name=op.f('ck_trades_side')),
    sa.CheckConstraint("source IN ('manual', 'import', 'csv_template')", name=op.f('ck_trades_source')),
    sa.ForeignKeyConstraint(['account_id'], ['app.accounts.id'], name=op.f('fk_trades_account_id_accounts')),
    sa.ForeignKeyConstraint(['import_batch_id'], ['app.import_batches.id'], name=op.f('fk_trades_import_batch_id_import_batches')),
    sa.ForeignKeyConstraint(['plan_version_id'], ['app.plan_versions.id'], name=op.f('fk_trades_plan_version_id_plan_versions')),
    sa.ForeignKeyConstraint(['replaces_trade_id'], ['app.trades.id'], name=op.f('fk_trades_replaces_trade_id_trades')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_trades_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trades')),
    sa.UniqueConstraint('account_id', 'dedup_key', name=op.f('uq_trades_account_id_dedup_key')),
    schema='app',
    comment='成交事实；只允许改 voided_at / void_reason / plan_version_id（触发器）'
    )
    op.create_table('alert_rules',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('plan_condition_id', sa.UUID(), nullable=True),
    sa.Column('security_code', sa.Text(), nullable=True),
    sa.Column('type', sa.Text(), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('cooldown_minutes', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("origin IN ('plan_condition', 'holding_event', 'user_custom')", name=op.f('ck_alert_rules_origin')),
    sa.ForeignKeyConstraint(['plan_condition_id'], ['app.plan_conditions.id'], name=op.f('fk_alert_rules_plan_condition_id_plan_conditions')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_alert_rules_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert_rules')),
    schema='app'
    )
    op.create_table('import_rows',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('batch_id', sa.UUID(), nullable=False),
    sa.Column('file_id', sa.UUID(), nullable=True),
    sa.Column('row_no', sa.Integer(), nullable=False),
    sa.Column('raw_line', sa.Text(), nullable=True, comment='应用层加密；对外只给掩码后的行'),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('normalized', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('findings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('dedup_key', sa.Text(), nullable=True),
    sa.Column('dedup_status', sa.Text(), nullable=True),
    sa.Column('committed_trade_id', sa.UUID(), nullable=True),
    sa.Column('committed_event_id', sa.UUID(), nullable=True),
    sa.CheckConstraint("dedup_status IN ('new', 'duplicate_in_db', 'duplicate_in_file', 'possible_duplicate_of_manual')", name=op.f('ck_import_rows_dedup_status')),
    sa.CheckConstraint("kind IN ('trade', 'event', 'ignored')", name=op.f('ck_import_rows_kind')),
    sa.CheckConstraint("status IN ('ok', 'warning', 'error', 'skipped')", name=op.f('ck_import_rows_status')),
    sa.ForeignKeyConstraint(['batch_id'], ['app.import_batches.id'], name=op.f('fk_import_rows_batch_id_import_batches')),
    sa.ForeignKeyConstraint(['committed_event_id'], ['app.account_events.id'], name=op.f('fk_import_rows_committed_event_id_account_events')),
    sa.ForeignKeyConstraint(['committed_trade_id'], ['app.trades.id'], name=op.f('fk_import_rows_committed_trade_id_trades')),
    sa.ForeignKeyConstraint(['file_id'], ['app.import_files.id'], name=op.f('fk_import_rows_file_id_import_files')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_rows')),
    schema='app'
    )
    op.create_table('risk_events',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('control', sa.Text(), nullable=False),
    sa.Column('level', sa.Text(), nullable=False),
    sa.Column('subject', sa.Text(), nullable=False),
    sa.Column('security_code', sa.Text(), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('suggestion_id', sa.UUID(), nullable=True),
    sa.Column('trade_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("control IN ('stop_take', 'position_cap', 'total_exposure', 'sector_concentration', 'loss_streak_drawdown', 'plan_violation')", name=op.f('ck_risk_events_control')),
    sa.CheckConstraint("level IN ('info', 'warning', 'critical')", name=op.f('ck_risk_events_level')),
    sa.CheckConstraint("subject IN ('account', 'security', 'strategy')", name=op.f('ck_risk_events_subject')),
    sa.ForeignKeyConstraint(['suggestion_id'], ['app.suggestions.id'], name=op.f('fk_risk_events_suggestion_id_suggestions')),
    sa.ForeignKeyConstraint(['trade_id'], ['app.trades.id'], name=op.f('fk_risk_events_trade_id_trades')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_risk_events_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_events')),
    schema='app',
    comment='只追加（触发器）'
    )
    op.create_table('suggestion_user_actions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('suggestion_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('trade_id', sa.UUID(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('viewed', 'dismissed', 'draft_requested', 'draft_confirmed', 'reason_manually_released', 'acted_trade_linked')", name=op.f('ck_suggestion_user_actions_kind')),
    sa.ForeignKeyConstraint(['suggestion_id'], ['app.suggestions.id'], name=op.f('fk_suggestion_user_actions_suggestion_id_suggestions')),
    sa.ForeignKeyConstraint(['trade_id'], ['app.trades.id'], name=op.f('fk_suggestion_user_actions_trade_id_trades')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_suggestion_user_actions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_suggestion_user_actions')),
    schema='app',
    comment='只追加（触发器）'
    )
    op.create_table('alerts',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('rule_id', sa.UUID(), nullable=True),
    sa.Column('security_code', sa.Text(), nullable=True),
    sa.Column('severity', sa.Text(), nullable=False),
    sa.Column('what_happened', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('affected', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('checklist', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'new'"), nullable=False),
    sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('data_as_of', sa.DateTime(timezone=True), nullable=True),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('dedup_key', sa.Text(), nullable=True),
    sa.CheckConstraint("severity IN ('info', 'attention', 'important')", name=op.f('ck_alerts_severity')),
    sa.CheckConstraint("status IN ('new', 'read', 'checked', 'acted', 'dismissed')", name=op.f('ck_alerts_status')),
    sa.ForeignKeyConstraint(['rule_id'], ['app.alert_rules.id'], name=op.f('fk_alerts_rule_id_alert_rules')),
    sa.ForeignKeyConstraint(['snapshot_id'], ['app.data_snapshots.id'], name=op.f('fk_alerts_snapshot_id_data_snapshots')),
    sa.ForeignKeyConstraint(['user_id'], ['app.users.id'], name=op.f('fk_alerts_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alerts')),
    sa.UniqueConstraint('user_id', 'dedup_key', name=op.f('uq_alerts_user_id_dedup_key')),
    schema='app'
    )
