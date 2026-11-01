"""T-B02a / 契约 v0.2.3：三层表 CHECK、周期分类器 semver 与封顶、建议卡部分唯一索引、TRUNCATE 防护

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01 21:30:00+00:00

- ``app.candidate_signals``（按月分区，约束建在父表上，自动下沉到全部分区）：
  ``confidence`` ∈ [0, 1]；``rule_refs`` 每项为 RuleRef（rule_id 非空、role ∈ rule_role、
  dimension ∈ dimension（v0.2.3 所有 role 必填）、passed 为布尔或 null）；``evidence`` 每项
  id 非空且 provider ∈ data_provider；``counter_evidence`` / ``invalidation`` 每项 text 非空。
  基线的「四个数组非空」「model_refs 只能 auxiliary」不变。
- ``app.horizon_classifier_versions.semver``（契约 ``classifier_version``，plan §3.3 T-A03）：
  NOT NULL、唯一、semver 正则。表是只追加的，不能回填，**要求升级时表为空**（否则升级明确失败）。
- ``app.symbol_horizon_assessments``：``caps jsonb NOT NULL DEFAULT '[]'``（HorizonCap[]）、
  ``evidence jsonb``（Evidence[]，plan 未写 NOT NULL）；``inputs_missing`` 每项匹配 ``^f\\.[a-z0-9_]+$``。
- ``app.suggestions``：部分唯一索引 ``(user_id, security_code) WHERE status = 'active'``（契约 #18）。
- TRUNCATE 防护：0001 的不可变触发器只拦 UPDATE/DELETE，``TRUNCATE`` 可绕过。新增语句级
  ``app.reject_truncate()``，挂在全部只追加 / 受限更新 / 守卫表上（分区表的父表与现有子分区都挂）；
  ``app.ensure_monthly_partitions`` 改为：父表有防护时新建分区也挂上。
- 0001、0002 不改。review-T-B02 F11：0002 对只追加表 drop column 的写法，生产库有数据后禁止，
  届时改为「新增列 + 视图过渡」；本迁移只加列 / 约束 / 索引 / 触发器，downgrade 才删列。
- downgrade：删除上述全部对象并恢复 0001 的 ``ensure_monthly_partitions``。若已有数据违反
  0002 的结构（无），或 suggestions 中有重复 active 行（升级前就有会导致升级失败），需人工处理。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "app"

CHECKS = (
    ('candidate_signals', 'ck_candidate_signals_confidence_range', 'confidence >= 0 AND confidence <= 1'),
    ('candidate_signals', 'ck_candidate_signals_rule_refs_shape', 'jsonb_typeof(rule_refs) = \'array\' AND NOT jsonb_path_exists(rule_refs, \'$[*] ? (@.type() != "object" || !(@.rule_id.type() == "string") || @.rule_id == "" || !(@.role.type() == "string") || !(@.role == "entry" || @.role == "hold" || @.role == "weakening" || @.role == "exit" || @.role == "filter" || @.role == "veto" || @.role == "counter" || @.role == "invalidation") || !(@.dimension.type() == "string") || !(@.dimension == "technical" || @.dimension == "capital" || @.dimension == "fundamental" || @.dimension == "sentiment" || @.dimension == "sector_market" || @.dimension == "news") || !(@.passed.type() == "boolean" || @.passed.type() == "null"))\')'),
    ('candidate_signals', 'ck_candidate_signals_evidence_shape', 'jsonb_typeof(evidence) = \'array\' AND NOT jsonb_path_exists(evidence, \'$[*] ? (@.type() != "object" || !(@.id.type() == "string") || @.id == "" || !(@.provider.type() == "string") || !(@.provider == "mairui" || @.provider == "user_import" || @.provider == "user_input" || @.provider == "system"))\')'),
    ('candidate_signals', 'ck_candidate_signals_counter_evidence_shape', 'jsonb_typeof(counter_evidence) = \'array\' AND NOT jsonb_path_exists(counter_evidence, \'$[*] ? (@.type() != "object" || !(@.text.type() == "string") || @.text == "")\')'),
    ('candidate_signals', 'ck_candidate_signals_invalidation_shape', 'jsonb_typeof(invalidation) = \'array\' AND NOT jsonb_path_exists(invalidation, \'$[*] ? (@.type() != "object" || !(@.text.type() == "string") || @.text == "")\')'),
    ('symbol_horizon_assessments', 'ck_symbol_horizon_assessments_inputs_missing_keys', 'NOT jsonb_path_exists(to_jsonb(inputs_missing), \'$[*] ? (@.type() != "string" || !(@ like_regex "^f[.][a-z0-9_]+$"))\')'),
    ('symbol_horizon_assessments', 'ck_symbol_horizon_assessments_caps_shape', 'jsonb_typeof(caps) = \'array\' AND NOT jsonb_path_exists(caps, \'$[*] ? (@.type() != "object" || !(@.horizon.type() == "string") || !(@.horizon == "intraday_t" || @.horizon == "short" || @.horizon == "swing" || @.horizon == "long") || !(@.cap.type() == "number") || @.cap < 0 || @.cap > 100 || @.cap != @.cap.floor() || !(@.kind.type() == "string") || !(@.kind == "data_missing" || @.kind == "requires") || !(@.rule_id.type() == "string" || @.rule_id.type() == "null") || !(@.inputs_missing.type() == "array"))\')'),
    ('symbol_horizon_assessments', 'ck_symbol_horizon_assessments_evidence_shape', '(evidence IS NULL OR (jsonb_typeof(evidence) = \'array\' AND NOT jsonb_path_exists(evidence, \'$[*] ? (@.type() != "object" || !(@.id.type() == "string") || @.id == "" || !(@.provider.type() == "string") || !(@.provider == "mairui" || @.provider == "user_import" || @.provider == "user_input" || @.provider == "system"))\')))'),
    ('horizon_classifier_versions', 'ck_horizon_classifier_versions_semver_format', "semver ~ '^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$'"),
)

#: 挂 TRUNCATE 防护的表（= 0001 的 APPEND_ONLY ∪ RESTRICTED_UPDATE ∪ 三张守卫表；冻结在本迁移里）
TRUNCATE_GUARDED = (
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
    "trades",
    "candidate_signals",
    "plan_drafts",
    "suggestions",
    "strategy_versions",
    "prompt_templates",
    "daily_reports",
)

REJECT_TRUNCATE_SQL = r"""
CREATE FUNCTION app.reject_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '%.% 只追加/不可变：禁止 TRUNCATE', TG_TABLE_SCHEMA, TG_TABLE_NAME
    USING ERRCODE = 'restrict_violation';
END $$;
"""

#: 按 relid 给一张表（含其现有子分区）挂 TRUNCATE 防护；已挂的跳过
GUARD_TREE_SQL = r"""
DO $$
DECLARE r regclass;
BEGIN
  -- 普通表 pg_partition_tree 不返回行，故并上表本身
  FOR r IN SELECT 'app.{table}'::regclass
           UNION SELECT relid FROM pg_partition_tree('app.{table}'::regclass) LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = r AND tgname = 'trg_no_truncate') THEN
      EXECUTE format('CREATE TRIGGER trg_no_truncate BEFORE TRUNCATE ON %s '
                     'FOR EACH STATEMENT EXECUTE FUNCTION app.reject_truncate()', r);
    END IF;
  END LOOP;
END $$;
"""

_PARTITIONS_HEAD = r"""
-- 按月声明式分区：为 parent 建 [start_month, start_month + months) 的月分区与 DEFAULT 分区。
-- 分区名 <表>_pYYYYMM / <表>_default（alembic env 的 include_object 据此忽略子表）。
-- 注意：DEFAULT 分区里已有某月数据时，再建该月分区会失败（需先迁出），定时任务应提前建好下月分区。
CREATE OR REPLACE FUNCTION app.ensure_monthly_partitions(parent regclass, start_month date, months int)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE
  sch text; tbl text; m date; part text; created int := 0;
"""

#: 0003 版：父表挂了 trg_no_truncate 时，新建的分区也挂上（TRUNCATE 子分区不会触发父表的触发器）
ENSURE_PARTITIONS_V3_SQL = _PARTITIONS_HEAD + r"""  guarded boolean;
BEGIN
  SELECT n.nspname, c.relname INTO sch, tbl
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.oid = parent;
  guarded := EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = parent AND tgname = 'trg_no_truncate');
  FOR i IN 0 .. months - 1 LOOP
    m := (date_trunc('month', start_month) + make_interval(months => i))::date;
    part := format('%s_p%s', tbl, to_char(m, 'YYYYMM'));
    IF to_regclass(format('%I.%I', sch, part)) IS NULL THEN
      EXECUTE format('CREATE TABLE %I.%I PARTITION OF %s FOR VALUES FROM (%L) TO (%L)',
                     sch, part, parent, m::timestamptz AT TIME ZONE 'UTC',
                     (m + interval '1 month')::timestamptz AT TIME ZONE 'UTC');
      IF guarded THEN
        EXECUTE format('CREATE TRIGGER trg_no_truncate BEFORE TRUNCATE ON %I.%I '
                       'FOR EACH STATEMENT EXECUTE FUNCTION app.reject_truncate()', sch, part);
      END IF;
      created := created + 1;
    END IF;
  END LOOP;
  IF to_regclass(format('%I.%I', sch, tbl || '_default')) IS NULL THEN
    EXECUTE format('CREATE TABLE %I.%I PARTITION OF %s DEFAULT', sch, tbl || '_default', parent);
    IF guarded THEN
      EXECUTE format('CREATE TRIGGER trg_no_truncate BEFORE TRUNCATE ON %I.%I '
                     'FOR EACH STATEMENT EXECUTE FUNCTION app.reject_truncate()',
                     sch, tbl || '_default');
    END IF;
    created := created + 1;
  END IF;
  RETURN created;
END $$;
"""

#: 0001 原版（downgrade 恢复用，逐字）
ENSURE_PARTITIONS_V1_SQL = _PARTITIONS_HEAD + r"""BEGIN
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


def upgrade() -> None:
    # --- horizon_classifier_versions.semver：只追加表不能回填，要求表为空 ---
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM app.horizon_classifier_versions) THEN "
        "RAISE EXCEPTION 'app.horizon_classifier_versions 已有数据，无法加 NOT NULL 的 semver 列"
        "（只追加表不能回填；需人工迁移）'; END IF; END $$"
    )
    op.add_column(
        "horizon_classifier_versions", sa.Column("semver", sa.Text(), nullable=False), schema=S
    )
    op.create_unique_constraint(
        op.f("uq_horizon_classifier_versions_semver"),
        "horizon_classifier_versions",
        ["semver"],
        schema=S,
    )

    # --- symbol_horizon_assessments：caps / evidence ---
    op.add_column(
        "symbol_horizon_assessments",
        sa.Column(
            "caps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema=S,
    )
    op.add_column(
        "symbol_horizon_assessments",
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=S,
    )

    # --- CHECK 约束（candidate_signals 建在分区父表上，PG 自动下沉到全部分区）---
    for table, name, sqltext in CHECKS:
        op.create_check_constraint(op.f(name), table, sqltext, schema=S)

    # --- suggestions：每个用户每只证券至多 1 张 active 建议卡 ---
    op.create_index(
        op.f("ux_suggestions_user_security_active"),
        "suggestions",
        ["user_id", "security_code"],
        unique=True,
        schema=S,
        postgresql_where=sa.text("status = 'active'"),
    )

    # --- TRUNCATE 防护 ---
    op.execute(REJECT_TRUNCATE_SQL)
    op.execute(ENSURE_PARTITIONS_V3_SQL)
    for table in TRUNCATE_GUARDED:
        op.execute(GUARD_TREE_SQL.replace("{table}", table))


def downgrade() -> None:
    op.execute(
        "DO $$ DECLARE r record; BEGIN "
        "FOR r IN SELECT t.tgrelid::regclass AS rel FROM pg_trigger t "
        "JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE t.tgname = 'trg_no_truncate' AND n.nspname = 'app' AND NOT t.tgisinternal LOOP "
        "EXECUTE format('DROP TRIGGER trg_no_truncate ON %s', r.rel); END LOOP; END $$"
    )
    op.execute(ENSURE_PARTITIONS_V1_SQL)
    op.execute("DROP FUNCTION app.reject_truncate()")

    op.drop_index(op.f("ux_suggestions_user_security_active"), table_name="suggestions", schema=S)
    for table, name, _sqltext in reversed(CHECKS):
        op.drop_constraint(op.f(name), table, type_="check", schema=S)
    op.drop_column("symbol_horizon_assessments", "evidence", schema=S)
    op.drop_column("symbol_horizon_assessments", "caps", schema=S)
    op.drop_constraint(
        op.f("uq_horizon_classifier_versions_semver"),
        "horizon_classifier_versions",
        type_="unique",
        schema=S,
    )
    op.drop_column("horizon_classifier_versions", "semver", schema=S)
