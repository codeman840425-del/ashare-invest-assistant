"""T-B16-core：删除用户数据的数据状态门（plan §7.3「删除用户数据 CLI 规则」）

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-02 07:24:29+08:00

不设维护会话旁路（无会话变量、无 session_replication_role、无专用角色）。改为“数据状态门”：

- ``app.users.status`` 新增 ``purging``（契约 account_status 不含它；API 不写这个值）。
- 可延迟约束触发器 ``trg_users_purging_not_committed``：提交时只要存在 ``status='purging'`` 的行
  就报错 → CLI 必须在同一事务内「置 purging → 处理子表 → 删除 users 行」。
- ``app.reject_mutation()`` / ``app.guard_daily_reports()`` 先问 ``app.purge_permits(...)``：
  只有行的属主是 purging 用户时才放行 DELETE（物理删除表），或放行规定的匿名化 UPDATE
  （``audit_logs`` / ``account_reviews`` / ``ops.data_licence_events``：只允许指向该用户的
  user_id/actor_id/target_id 置 NULL、detail 去除 PII 键、ip_hash 置 NULL，其余列不变）。
  其他情况行为与 0010 完全一致。
- ``account_reviews.user_id/admin_id``、``ops.data_licence_events.user_id/licence_id`` 改为可空。
- 新表 ``ops.pending_file_purges``（path、attempts、last_error；不含 user_id）。

downgrade：恢复原函数体、删门与新表；若已有 NULL（匿名化过的行）则 NOT NULL 无法恢复，
downgrade 会失败（有意：不能凭空恢复被删除的身份）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUS = "status IN ('pending', 'approved', 'rejected', 'disabled')"
NEW_STATUS = "status IN ('pending', 'approved', 'rejected', 'disabled', 'purging')"

#: 有 user_id 列、物理删除且原本被触发器保护的表（分区表按父表名匹配）
DIRECT_OWNER_TABLES = (
    "app.trades",
    "app.suggestions",
    "app.candidate_signals",
    "app.plan_drafts",
    "app.plan_draft_confirmations",
    "app.daily_reports",
    "app.user_profiles",
    "app.claims",
    "app.signal_events",
    "app.risk_events",
    "app.suggestion_user_actions",
    "app.symbol_horizon_assessments",
)

PURGE_FUNCTIONS = r"""
CREATE FUNCTION app.purge_pii_key(k text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT lower(k) ~ ('(^|_)(security_code|symbol|symbols|name|username|email|path|filename|file'
    || '|mask|masked|suffix|last4|amount|qty|quantity|price|cost|fee|fees|cash|balance'
    || '|market_value|user_agent|ip|apply_note|note)$')
$$;

CREATE FUNCTION app.purge_scrub_json(j jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE r jsonb;
BEGIN
  IF j IS NULL THEN RETURN NULL; END IF;
  IF jsonb_typeof(j) = 'object' THEN
    SELECT coalesce(jsonb_object_agg(e.key, app.purge_scrub_json(e.value)), '{}'::jsonb)
      INTO r FROM jsonb_each(j) e WHERE NOT app.purge_pii_key(e.key);
    RETURN r;
  ELSIF jsonb_typeof(j) = 'array' THEN
    SELECT coalesce(jsonb_agg(app.purge_scrub_json(e.value) ORDER BY e.ord), '[]'::jsonb)
      INTO r FROM jsonb_array_elements(j) WITH ORDINALITY e(value, ord);
    RETURN r;
  END IF;
  RETURN j;
END $$;

CREATE FUNCTION app.purge_user_ids() RETURNS uuid[]
LANGUAGE sql STABLE AS $$
  SELECT array_agg(id) FROM app.users WHERE status = 'purging'
$$;

-- 行属主（只用于物理删除表）；未知表返回 NULL → 不放行
CREATE FUNCTION app.purge_row_owner(tbl text, o jsonb) RETURNS uuid
LANGUAGE plpgsql STABLE AS $$
DECLARE
  base text := regexp_replace(tbl, '_(p[0-9]{6}|default)$', '');
  r uuid;
BEGIN
  CASE base
  WHEN __DIRECT__ THEN
    RETURN (o->>'user_id')::uuid;
  WHEN 'app.broker_position_snapshots' THEN
    SELECT a.user_id INTO r FROM app.accounts a WHERE a.id = (o->>'account_id')::uuid;
  WHEN 'app.broker_position_snapshot_items' THEN
    SELECT a.user_id INTO r FROM app.broker_position_snapshots s
      JOIN app.accounts a ON a.id = s.account_id WHERE s.id = (o->>'snapshot_id')::uuid;
  WHEN 'app.daily_report_items' THEN
    SELECT d.user_id INTO r FROM app.daily_reports d WHERE d.id = (o->>'report_id')::uuid;
  WHEN 'app.plan_versions' THEN
    SELECT p.user_id INTO r FROM app.action_plans p WHERE p.id = (o->>'plan_id')::uuid;
  WHEN 'app.plan_conditions' THEN
    SELECT p.user_id INTO r FROM app.plan_versions v
      JOIN app.action_plans p ON p.id = v.plan_id WHERE v.id = (o->>'plan_version_id')::uuid;
  WHEN 'app.review_versions' THEN
    SELECT v.user_id INTO r FROM app.reviews v WHERE v.id = (o->>'review_id')::uuid;
  WHEN 'app.reason_status_events' THEN
    SELECT n.user_id INTO r FROM app.non_executable_reasons n WHERE n.id = (o->>'reason_id')::uuid;
  WHEN 'app.candidate_versions' THEN
    SELECT c.user_id INTO r FROM app.research_candidates c WHERE c.id = (o->>'candidate_id')::uuid;
  WHEN 'app.strategy_instance_events' THEN
    SELECT i.user_id INTO r FROM app.strategy_instances i WHERE i.id = (o->>'instance_id')::uuid;
  WHEN 'app.risk_control_settings_history' THEN
    SELECT coalesce((o->>'user_id')::uuid, s.user_id) INTO r FROM app.risk_control_settings s
      WHERE s.id = (o->>'setting_id')::uuid;
  WHEN 'app.candidate_signal_events' THEN
    SELECT s.user_id INTO r FROM app.candidate_signals s WHERE s.id = (o->>'signal_id')::uuid;
  ELSE
    RETURN NULL;
  END CASE;
  RETURN r;
END $$;

-- audit_logs.target_id（text）是否指向 purging 用户或其证书/画像行
CREATE FUNCTION app.purge_target_ref(t text, uids uuid[]) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT t IS NOT NULL AND (
    t = ANY (uids::text[])
    OR EXISTS (SELECT 1 FROM app.user_data_licences l
                WHERE l.id::text = t AND l.user_id = ANY (uids))
    OR EXISTS (SELECT 1 FROM app.user_profiles p WHERE p.id::text = t AND p.user_id = ANY (uids))
  )
$$;

-- 规定的匿名化 UPDATE：NEW 必须恰好等于由 OLD 推出的值
CREATE FUNCTION app.purge_anonymize_ok(tbl text, o jsonb, n jsonb, uids uuid[]) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE
  base text := regexp_replace(tbl, '_(p[0-9]{6}|default)$', '');
  actor_hit boolean;
  target_hit boolean;
  expected jsonb;
BEGIN
  IF base = 'app.audit_logs' THEN
    actor_hit := coalesce((o->>'actor_id')::uuid = ANY (uids), false);
    target_hit := app.purge_target_ref(o->>'target_id', uids);
    IF NOT (actor_hit OR target_hit) THEN RETURN false; END IF;
    expected := o || jsonb_build_object(
      'actor_id', CASE WHEN actor_hit THEN NULL ELSE o->'actor_id' END,
      'target_id', CASE WHEN target_hit THEN NULL ELSE o->'target_id' END,
      'detail', app.purge_scrub_json(o->'detail'),
      'ip_hash', CASE WHEN actor_hit OR (o->>'actor_id') IS NULL THEN NULL ELSE o->'ip_hash' END);
  ELSIF base = 'app.account_reviews' THEN
    actor_hit := coalesce((o->>'admin_id')::uuid = ANY (uids), false);
    target_hit := coalesce((o->>'user_id')::uuid = ANY (uids), false);
    IF NOT (actor_hit OR target_hit) THEN RETURN false; END IF;
    expected := o || jsonb_build_object(
      'admin_id', CASE WHEN actor_hit THEN NULL ELSE o->'admin_id' END,
      'user_id', CASE WHEN target_hit THEN NULL ELSE o->'user_id' END);
  ELSIF base = 'ops.data_licence_events' THEN
    IF NOT coalesce((o->>'user_id')::uuid = ANY (uids), false) THEN RETURN false; END IF;
    expected := o || jsonb_build_object('user_id', NULL, 'licence_id', NULL);
  ELSE
    RETURN false;
  END IF;
  RETURN n = expected;
END $$;

CREATE FUNCTION app.purge_permits(tbl text, op text, o jsonb, n jsonb) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE uids uuid[] := app.purge_user_ids();
BEGIN
  IF uids IS NULL OR o IS NULL THEN RETURN false; END IF;
  IF op = 'DELETE' THEN
    RETURN coalesce(app.purge_row_owner(tbl, o) = ANY (uids), false);
  ELSIF op = 'UPDATE' THEN
    RETURN app.purge_anonymize_ok(tbl, o, n, uids);
  END IF;
  RETURN false;
END $$;

CREATE OR REPLACE FUNCTION app.reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP IN ('DELETE', 'UPDATE') AND app.purge_permits(
       TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, TG_OP, to_jsonb(OLD),
       CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(NEW) END) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  RAISE EXCEPTION '%.% 只追加/不可变：禁止 %', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'restrict_violation';
END $$;

CREATE OR REPLACE FUNCTION app.guard_daily_reports() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'building' AND NOT (TG_OP = 'DELETE'
       AND app.purge_permits('app.daily_reports', 'DELETE', to_jsonb(OLD), NULL)) THEN
    RAISE EXCEPTION 'app.daily_reports 生成后不可变：禁止 %（重跑请生成新 revision）', TG_OP
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE FUNCTION app.reject_purging_commit() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM app.users WHERE status = 'purging') THEN
    RAISE EXCEPTION 'app.users：存在 status=purging 的行，不允许提交'
      '（删除用户数据必须在同一事务内删除用户行）'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER trg_users_purging_not_committed
  AFTER INSERT OR UPDATE OF status ON app.users
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW WHEN (NEW.status = 'purging')
  EXECUTE FUNCTION app.reject_purging_commit();
""".replace("__DIRECT__", ", ".join(f"'{t}'" for t in DIRECT_OWNER_TABLES))

OLD_FUNCTIONS = r"""
DROP TRIGGER IF EXISTS trg_users_purging_not_committed ON app.users;
DROP FUNCTION IF EXISTS app.reject_purging_commit();

CREATE OR REPLACE FUNCTION app.reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '%.% 只追加/不可变：禁止 %', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'restrict_violation';
END $$;

CREATE OR REPLACE FUNCTION app.guard_daily_reports() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'building' THEN
    RAISE EXCEPTION 'app.daily_reports 生成后不可变：禁止 %（重跑请生成新 revision）', TG_OP
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

DROP FUNCTION IF EXISTS app.purge_permits(text, text, jsonb, jsonb);
DROP FUNCTION IF EXISTS app.purge_anonymize_ok(text, jsonb, jsonb, uuid[]);
DROP FUNCTION IF EXISTS app.purge_target_ref(text, uuid[]);
DROP FUNCTION IF EXISTS app.purge_row_owner(text, jsonb);
DROP FUNCTION IF EXISTS app.purge_user_ids();
DROP FUNCTION IF EXISTS app.purge_scrub_json(jsonb);
DROP FUNCTION IF EXISTS app.purge_pii_key(text);
"""


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_status"), "users", schema="app", type_="check")
    op.create_check_constraint(op.f("ck_users_status"), "users", NEW_STATUS, schema="app")
    op.alter_column("account_reviews", "user_id", nullable=True, schema="app")
    op.alter_column("account_reviews", "admin_id", nullable=True, schema="app")
    op.alter_column("data_licence_events", "user_id", nullable=True, schema="ops")
    op.alter_column("data_licence_events", "licence_id", nullable=True, schema="ops")
    op.create_table(
        "pending_file_purges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pending_file_purges")),
        sa.UniqueConstraint("path", name=op.f("uq_pending_file_purges_path")),
        schema="ops",
        comment="删除用户数据后未删成功的原始导入文件（plan §7.3）；不含 user_id，下次运行先重试",
    )
    op.execute(
        "CREATE TRIGGER trg_no_truncate BEFORE TRUNCATE ON ops.pending_file_purges "
        "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_truncate()"
    )
    op.execute(PURGE_FUNCTIONS)


def downgrade() -> None:
    op.execute(OLD_FUNCTIONS)
    op.drop_table("pending_file_purges", schema="ops")
    op.alter_column("data_licence_events", "licence_id", nullable=False, schema="ops")
    op.alter_column("data_licence_events", "user_id", nullable=False, schema="ops")
    op.alter_column("account_reviews", "admin_id", nullable=False, schema="app")
    op.alter_column("account_reviews", "user_id", nullable=False, schema="app")
    op.drop_constraint(op.f("ck_users_status"), "users", schema="app", type_="check")
    op.create_check_constraint(op.f("ck_users_status"), "users", OLD_STATUS, schema="app")
